#!/usr/bin/env python3
"""把 Shopify 真实订单灌进内核事件层（change establish-ai-native-ecommerce-stack 4.2）。

**做的是「生产事实」，不是「跑测试」**：从 Shopify Admin GraphQL 读已付款订单，
逐笔写成 `marketing.channel.order_paid` 事实（`requires_posting=false`，营销账不并入
ERP 账本），幂等键用订单的稳定标识，重跑不重复。

三条纪律：
1. **只读上游**：Shopify 侧只发 GraphQL query，零写操作（token 只有 read scope）。
2. **金额原样**：不换算、不四舍五入、不推算——`totalPriceSet.shopMoney` 是上游给的
   唯一权威金额；结算额不从订单加总推出。
3. **幂等**：同一订单重跑返回首次结果（内核按 (租户, 车道, stable_id) 去重）。

用法（在能同时访问 Shopify 与内核库的机器/pod 里）：
  SHOPIFY_TOKEN=shpua_... SHOPIFY_SHOP=xxx.myshopify.com \
    python3 scripts/ingest_shopify_orders.py
  ... --dry-run   只打印将写入的事实，不写库
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

# 本地工作区与本仓库同处一处；pod 里包已装好（/app），父目录不足 3 层时跳过。
_here = Path(__file__).resolve()
if len(_here.parents) > 2:
    _kernel = _here.parents[2] / "fd-erp-ledger-mcp"
    if _kernel.is_dir() and str(_kernel) not in sys.path:
        sys.path.insert(0, str(_kernel))

EVENT_TYPE = "marketing.channel.order_paid"

ORDERS_QUERY = """
{ orders(first: 50, sortKey: CREATED_AT) { edges { node {
    id name createdAt displayFinancialStatus
    totalPriceSet { shopMoney { amount currencyCode } }
} } } }
"""


def fetch_orders(token: str, shop: str) -> list[dict]:
    """只读上游：拿已付款订单。判据是 displayFinancialStatus == PAID。"""
    req = urllib.request.Request(
        f"https://{shop}/admin/api/2026-10/graphql.json",
        data=json.dumps({"query": ORDERS_QUERY}).encode(),
        headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.loads(r.read())
    if body.get("errors"):
        raise SystemExit(f"Shopify 读取失败：{json.dumps(body['errors'], ensure_ascii=False)[:400]}")
    edges = ((body.get("data") or {}).get("orders") or {}).get("edges") or []
    out = []
    for e in edges:
        n = e.get("node") or {}
        money = ((n.get("totalPriceSet") or {}).get("shopMoney") or {})
        out.append({
            "stable_id": str(n.get("id")),           # gid://shopify/Order/… 是稳定标识
            "order_ref": str(n.get("name")),          # #1001
            "occurred_at": str(n.get("createdAt")),
            "amount": str(money.get("amount")),
            "currency": str(money.get("currencyCode")),
            "financial_status": str(n.get("displayFinancialStatus")),
            "shop": shop,
        })
    return out


def to_payload(order: dict) -> dict:
    """载荷只填 schema required 的四个字段 + channel（上游真给的，不编值）。"""
    return {
        "order_ref": order["order_ref"],
        "amount": order["amount"],
        "currency": order["currency"],
        "channel": f"shopify:{order['shop']}",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Shopify 已付款订单 → 内核事实")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--tenant", default=os.environ.get("ERP_TENANT_ID", "acme"))
    args = ap.parse_args(argv)

    token = os.environ.get("SHOPIFY_TOKEN", "").strip()
    shop = os.environ.get("SHOPIFY_SHOP", "").strip()
    if not token or not shop:
        print("判不出：需要 SHOPIFY_TOKEN 与 SHOPIFY_SHOP")
        return 2

    orders = fetch_orders(token, shop)
    paid = [o for o in orders if o["financial_status"] == "PAID"]
    print(f"读到 {len(orders)} 笔订单，其中 PAID {len(paid)} 笔")

    if args.dry_run:
        for o in paid:
            print("  将写入", o["stable_id"], "→", json.dumps(to_payload(o), ensure_ascii=False))
        return 0

    from fd_erp_ledger_mcp.db import connection
    from fd_erp_ledger_mcp.events import append_event
    from fd_erp_ledger_mcp.config import Settings

    settings = Settings.from_env()
    written, deduped = 0, 0
    with connection(settings) as conn:
        for o in paid:
            res = append_event(
                conn, settings=settings, tenant_id=args.tenant,
                event_type=EVENT_TYPE, stable_id=o["stable_id"],
                occurred_at=o["occurred_at"], payload=to_payload(o),
                lane="ingest",
                source_ref=f"shopify:{shop}#order={o['order_ref']}",
                provenance={"source": "shopify_admin.orders", "shop": shop,
                            "order_ref": o["order_ref"],
                            "producer": "marketing"},
                actor="ingest-lane")
            if res.get("duplicate") is True:
                deduped += 1
            else:
                written += 1
    print(f"写入 {written} 条新事实，{deduped} 条幂等命中")
    return 0


if __name__ == "__main__":
    sys.exit(main())
