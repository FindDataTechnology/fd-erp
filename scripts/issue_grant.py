#!/usr/bin/env python3
"""签一枚委托 Grant（在 registry pod 内跑，需要 SECRET_KEY + 已登记的主体）。

为什么需要这个脚本：`POST /api/grants` 要求 console 登录态（`nginx_proxied_auth`
的 `X-Username`），而 agent / 定时任务没有登录态。内部服务 token 是官方给出的
服务间身份通道，本脚本用它替 agent 开票。

**签完这一枚，agent 就能带着它去下单**：`aud` 指向 ERP 纵向 API，`budget` 是
委托人给的金额上限，`act` 记「代谁做事」。

用法（pod 内）：
  kubectl exec -n mcp-registry deploy/registry -- python /tmp/issue_grant.py \
    --sub agent:procurement-acme --act aloadtree@gmail.com --tenant acme \
    --budget 200 --run run-2026-11-25-001
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _ui_token(subject: str) -> str:
    """registry-UI 身份 token（自签）。

    `/api/grants` 走的是 `nginx_proxied_auth`，它认的是 `mcp-registry-ui`
    这条 audience（HS256 + 共享 SECRET_KEY），**不是** internal-service 那条。
    两条 token 长得像但 audience/token_use 不同，签错就被 401。

    为什么自签而不是走 Logto：本机没有浏览器会话，而这个脚本的用途是
    「给 agent 开一张测试用的票」。它签的是**已经存在的**主体身份（调用方必须
    显式给 --act / --sub），不创造新权限；TTL 默认 300 秒。
    """
    import os
    import time

    import jwt as pyjwt

    secret = os.environ.get("SECRET_KEY")
    if not secret:
        raise SystemExit("判不出：SECRET_KEY 未设置（必须在 registry pod 内运行）")
    now = int(time.time())
    return pyjwt.encode({
        "iss": "mcp-auth-server",
        "aud": "mcp-registry-ui",
        "sub": subject,
        "groups": ["mcp-registry-admin"],
        "auth_method": "internal",
        "token_use": "mcp-registry-ui",
        "iat": now,
        "exp": now + 300,
    }, secret, algorithm="HS256")


def issue(base: str, *, sub: str, act: str, tenant: str, budget: str,
          run: str, aud: str, ttl: int, scope: list[str]) -> dict:
    token = _ui_token(act or sub)
    body = json.dumps({
        "aud": aud, "run": run, "sub": sub, "act": act, "tenant": tenant,
        "scope": scope,
        "budget": {"amount": budget, "currency": "CNY"} if budget else None,
        "ttl_seconds": ttl,
    }).encode()
    req = urllib.request.Request(
        f"{base.rstrip('/')}/api/grants", data=body,
        headers={"Content-Type": "application/json",
                 "X-Internal-Token-Registry": token},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return {"ok": True, "status": r.status,
                    "body": json.loads(r.read() or b"{}")}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code,
                "body": json.loads(e.read() or b"{}")}
    except (urllib.error.URLError, TimeoutError) as e:
        return {"ok": False, "status": None, "error": str(e)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:7860")
    ap.add_argument("--sub", required=True, help="持票主体（通常是 agent）")
    ap.add_argument("--act", required=True, help="代谁做事（agent 的 owner）")
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--aud", default="erp-vertical-api")
    ap.add_argument("--budget", default="", help="金额上限（空=只受租户额度约束）")
    ap.add_argument("--run", required=True)
    ap.add_argument("--ttl", type=int, default=1800)
    ap.add_argument("--scope", nargs="*", default=["order.write"])
    a = ap.parse_args(argv)

    out = issue(a.base, sub=a.sub, act=a.act, tenant=a.tenant, budget=a.budget,
                run=a.run, aud=a.aud, ttl=a.ttl, scope=a.scope)
    if not out["ok"]:
        print(json.dumps(out, ensure_ascii=False, indent=1), file=sys.stderr)
        return 1
    body = out["body"]
    print(json.dumps({"aud": body.get("aud"), "exp": body.get("exp"),
                      "token": body.get("token")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
