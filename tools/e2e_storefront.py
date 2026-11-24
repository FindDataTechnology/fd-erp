#!/usr/bin/env python3
"""店面全链 E2E（对**真实运行环境**跑，不 mock 任何业务层）。

与 `tests/test_storefront_e2e.py` 的区别：那个用 TestClient + 测试库，验证代码路径；
这个打真 HTTP + 真库，验证**部署出来的东西**能开一家店。两者都必要——前者抓逻辑错，
后者抓配置错（零售渠道没配、价目没生效、重启后数据丢了）。

用法（在目标 pod 内或能访问目标 API 的机器上）：
  python3 fd-erp/tools/e2e_storefront.py --base http://127.0.0.1:8100 --tenant acme

退出码 0 / 1（第几步红）/ 2（判不出）。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid

SHIP = {"name": "E2E 收货人", "phone": "13800000000", "address": "E2E 地址"}


def call(method, url, body=None, headers=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"} if body is not None else {}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except json.JSONDecodeError:
            return e.code, {}
    except (urllib.error.URLError, TimeoutError) as e:
        raise SystemExit(f"判不出：连不上 {url}（{e}）")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    base, tenant = a.base.rstrip("/"), a.tenant
    steps = []

    def step(name, ok, **detail):
        steps.append({"step": name, "ok": bool(ok), **detail})
        return ok

    # 1 匿名逛店
    st, body = call("GET", f"{base}/shop/{tenant}/products?limit=10")
    items = body.get("data") or []
    leaked = [k for k in ("entity_id", "supplier_id", "base_price", "cost")
              if k in json.dumps(items, ensure_ascii=False)]
    if not step("1-anonymous-browse", st == 200 and bool(items) and not leaked,
                status=st, count=len(items), leak=leaked or None):
        return _out(steps, a.json)

    # 2 匿名下单
    idem = f"e2e-{uuid.uuid4().hex[:12]}"
    code = items[0]["productId"]
    st, body = call("POST", f"{base}/shop/{tenant}/orders",
                    {"lines": [{"productId": code, "qty": 2}], "shipTo": SHIP},
                    {"Idempotency-Key": idem})
    d = body.get("data") or {}
    if not step("2-anonymous-order",
                st == 200 and d.get("settlement_mode") == "prepaid"
                and d.get("payment_state") == "awaiting_payment",
                status=st, order_ref=d.get("order_ref"),
                amount=d.get("amount_total"), settle=d.get("settlement_mode")):
        return _out(steps, a.json)
    ref = d["order_ref"]

    # 2b 同 key 重放
    st2, b2 = call("POST", f"{base}/shop/{tenant}/orders",
                   {"lines": [{"productId": code, "qty": 2}], "shipTo": SHIP},
                   {"Idempotency-Key": idem})
    step("2b-idempotent-replay",
         (b2.get("data") or {}).get("order_ref") == ref
         and (b2.get("data") or {}).get("duplicate") is True,
         status=st2)

    # 3 买家不能自己确认到账
    st, _ = call("POST", f"{base}/shop/{tenant}/orders/{ref}/payment",
                 {"amount": d.get("amount_total"), "proofRef": "x"}, {})
    step("3-buyer-cannot-pay", st == 401, status=st)

    # 4 未到账不可确认（服务端事实：payment_state 仍 awaiting）
    st, body = call("GET", f"{base}/shop/{tenant}/orders/{ref}")
    step("4-unpaid-blocks-fulfillment",
         st == 200 and (body.get("data") or {}).get("payment_state") == "awaiting_payment",
         status=st, payment_state=(body.get("data") or {}).get("payment_state"))

    # 5 商家登记到账
    st, body = call("POST", f"{base}/shop/{tenant}/orders/{ref}/payment",
                    {"amount": d.get("amount_total"), "proofRef": f"e2e-{idem}"},
                    {"X-ERP-Tenant": tenant})
    pd = body.get("data") or {}
    if not step("5-merchant-records-payment",
                st == 200 and pd.get("received") is True
                and pd.get("requires_posting") is False,
                status=st, requires_posting=pd.get("requires_posting")):
        return _out(steps, a.json)

    # 6 幂等
    st, body = call("POST", f"{base}/shop/{tenant}/orders/{ref}/payment",
                    {"amount": d.get("amount_total"), "proofRef": f"e2e-{idem}"},
                    {"X-ERP-Tenant": tenant})
    step("6-payment-idempotent", (body.get("data") or {}).get("duplicate") is True, status=st)

    # 7 到账后状态推进
    st, body = call("GET", f"{base}/shop/{tenant}/orders/{ref}")
    step("7-paid-order-received",
         st == 200 and (body.get("data") or {}).get("payment_state") == "received",
         status=st, payment_state=(body.get("data") or {}).get("payment_state"))

    # 8 跨店不可见
    st, body = call("GET", f"{base}/shop/{tenant}-other/products")
    step("8-cross-tenant-404",
         st == 404 and f"{tenant}-other" not in json.dumps(body, ensure_ascii=False),
         status=st)

    return _out(steps, a.json)


def _out(steps, as_json):
    ok = all(s["ok"] for s in steps)
    if as_json:
        print(json.dumps({"opened": ok, "steps": steps}, ensure_ascii=False, indent=1))
    else:
        print(f"{'E2E 全通' if ok else 'E2E 失败'} —— {len([s for s in steps if s['ok']])}/{len(steps)} 步")
        for s in steps:
            extra = {k: v for k, v in s.items() if k not in ("step", "ok")}
            print(f"  {'ok' if s['ok'] else 'x '} {s['step']}"
                  + (f"  {json.dumps(extra, ensure_ascii=False)}" if extra else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())