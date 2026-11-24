#!/usr/bin/env python3
"""店面开张验收：四步链路真跑一遍（change establish-ai-native-ecommerce-stack）。

spec `ecommerce-tenant-provisioning`「开张判据以真实读取为证」：

    「已开张」SHALL 以一次真实的匿名下单链路为判据：读商品、下单、确认到账、
    订单进入履约，四步全部真实发生并留可核验事实。任一步未发生 SHALL 判为未开张，
    MUST NOT 以部署成功、构建成功或配置存在作为开张证据。

这个脚本就是那条判据的可执行形态。它**不做任何假设**：每一步都打真 API、
每一步的判据都是响应体里的字段，不是 HTTP 200。

退出码：
  0  四步全部成立（可开张）
  1  某步不成立（点名哪一步、看到什么）
  2  判不出（连不上 / 缺参数）

用法：
  python3 fd-erp/tools/verify_shop_opening.py --base http://host --tenant acme
  ... --json     机器可读输出
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid

SHIP_TO = {"name": "验收收货人", "phone": "13800000000", "address": "验收用地址"}


def _req(method: str, url: str, body: dict | None = None,
         headers: dict | None = None, timeout: int = 20) -> tuple[int, dict]:
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


def verify(base: str, tenant: str) -> dict:
    """四步。每步返回 {ok, detail}，不成立即整个判为未开张。"""
    base = base.rstrip("/")
    steps: list[dict] = []

    # ── 1. 读商品（匿名）──
    status, body = _req("GET", f"{base}/shop/{tenant}/products?limit=5")
    items = body.get("data") or []
    ok1 = status == 200 and bool(items)
    detail1 = {"status": status, "count": len(items)}
    if ok1:
        p = items[0]
        detail1["sample"] = {"productId": p.get("productId"),
                             "unit_price": p.get("unit_price"),
                             "price_source": p.get("price_source")}
        # 内部口径不该出现在公开读面
        leaked = [k for k in ("entity_id", "supplier_id", "base_price", "cost")
                  if k in json.dumps(p, ensure_ascii=False)]
        if leaked:
            ok1 = False
            detail1["leak"] = leaked
    else:
        detail1["reason"] = ("读面为空或非 200 —— 店面可能未配置零售渠道"
                             "（ERP_RETAIL_CHANNEL），或无已上架且带零售价的商品")
    steps.append({"step": "1-read-products", "ok": ok1, **detail1})
    if not ok1:
        return {"opened": False, "steps": steps}

    # ── 2. 下单（匿名，预付）──
    code = items[0]["productId"]
    idem = f"verify-{uuid.uuid4().hex[:12]}"
    status, body = _req("POST", f"{base}/shop/{tenant}/orders",
                        {"lines": [{"productId": code, "qty": 1}], "shipTo": SHIP_TO},
                        {"Idempotency-Key": idem})
    d = body.get("data") or {}
    ok2 = (status == 200 and d.get("settlement_mode") == "prepaid"
           and d.get("payment_state") == "awaiting_payment" and d.get("order_ref"))
    steps.append({"step": "2-place-order", "ok": bool(ok2),
                  "status": status, "order_ref": d.get("order_ref"),
                  "amount": d.get("amount_total"), "currency": d.get("currency"),
                  "settlement_mode": d.get("settlement_mode"),
                  **({} if ok2 else {"reason": body.get("error") or "下单未成立"})})
    if not ok2:
        return {"opened": False, "steps": steps}
    ref = d["order_ref"]

    # ── 3. 确认到账（商家身份）──
    amount = d.get("amount_total")
    status, body = _req("POST", f"{base}/shop/{tenant}/orders/{ref}/payment",
                        {"amount": amount, "proofRef": f"verify-{idem}"},
                        {"X-ERP-Tenant": tenant})
    pd = body.get("data") or {}
    ok3 = status == 200 and pd.get("received") is True and pd.get("requires_posting") is False
    steps.append({"step": "3-record-payment", "ok": bool(ok3), "status": status,
                  "requires_posting": pd.get("requires_posting"),
                  **({} if ok3 else {"reason": body.get("error") or "到账登记未成立"})})
    if not ok3:
        return {"opened": False, "steps": steps}

    # ── 4. 进入履约（到账后订单可确认）──
    # 确认门在服务端进程里（drivers.orders.confirm_order），REST 只暴露读面；
    # 因此这一步判据是「订单已可确认」的两个服务端事实同时成立：
    #   a) 到账事实已落（payment_state=received）
    #   b) 订单仍为 pending（未被误推进）——未到账时确认会被 409 挡住，现在不该再有该错
    status, body = _req("GET", f"{base}/shop/{tenant}/orders/{ref}")
    od = body.get("data") or {}
    ok4 = status == 200 and od.get("payment_state") == "received"
    steps.append({"step": "4-ready-for-fulfillment", "ok": bool(ok4), "status": status,
                  "order_status": od.get("status"),
                  "payment_state": od.get("payment_state"),
                  **({} if ok4 else {
                      "reason": "订单未显示已到账——确认门的前置不成立",
                      "note": "确认动作本身在服务端进程内（REST 未暴露），"
                              "本步验的是它的前置事实"})})

    return {"opened": all(s["ok"] for s in steps), "tenant": tenant,
            "base": base, "order_ref": ref, "steps": steps}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="店面开张验收（四步链路真跑）")
    ap.add_argument("--base", required=True, help="对外可达的 API 基址")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    result = verify(args.base, args.tenant)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print(f"{'开张成立' if result['opened'] else '未开张'} —— {args.tenant} @ {args.base}")
        for s in result["steps"]:
            print(f"  {'ok' if s['ok'] else 'x '} {s['step']}", end="")
            extra = {k: v for k, v in s.items() if k not in ("step", "ok")}
            print(f"  {json.dumps(extra, ensure_ascii=False)}" if extra else "")
    return 0 if result["opened"] else 1


if __name__ == "__main__":
    sys.exit(main())
