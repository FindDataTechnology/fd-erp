#!/usr/bin/env python3
"""从运行中的店面 API 拉公开读面快照（change establish-ai-native-ecommerce-stack 0.14）。

**只拉公开读面**：`GET /shop/{tenant}/products`。订单、买家信息、到账事实一律不拉——
它们不是公开数据，落进提交进仓的快照就是泄露。

三种退出码（与 `line-seam-proof` 同口径）：
  0  快照已写入
  1  API 返回错误（店面关着或被拒）
  2  **判不出**（没有配置地址 / 连不上）——仍写快照，但写 `available: false` + 原因，
     让下游如实渲染「未取得」而不是空列表冒充「没有商品」。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

FD_ERP = Path(__file__).resolve().parents[1]
OUT = FD_ERP / "shared" / "storefront-snapshot.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="拉店面公开读面快照")
    ap.add_argument("--base-url", default=os.environ.get("STOREFRONT_API_BASE", ""))
    ap.add_argument("--tenant", default=os.environ.get("STOREFRONT_TENANT", "acme"))
    ap.add_argument("--title", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)

    out = Path(args.out)
    record = {"schema": "erp-storefront-snapshot/v1", "as_of": _now(),
              "tenant": args.tenant,
              # 页内下单表单要打这个地址（买家浏览器直连 API）。存的是**对外可达**的
              # 基址——不是集群内 ClusterIP，否则买家浏览器到不了。
              "api_base": args.base_url.rstrip("/") if args.base_url else "",
              "shop": {"title": args.title or "网上商店", "note": args.note}}

    if not args.base_url:
        record.update({"available": False, "products": [],
                       "reason": "未配置取数地址（STOREFRONT_API_BASE 为空）"})
        out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(f"判不出：未配置 STOREFRONT_API_BASE——已写快照（available=false）到 {out}")
        return 2

    url = (f"{args.base_url.rstrip('/')}/shop/{args.tenant}/products"
           "?limit=500")
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        record.update({"available": False, "products": [],
                       "reason": f"店面读面返回 {exc.code}：{detail}"})
        out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(f"API 错误 {exc.code}——已写快照（available=false）到 {out}")
        return 1
    except (urllib.error.URLError, TimeoutError) as exc:
        record.update({"available": False, "products": [],
                       "reason": f"连不上店面读面：{exc}"})
        out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(f"判不出：连不上 {url}——已写快照（available=false）到 {out}")
        return 2

    products = body.get("data") or []
    record.update({
        "available": True,
        "products": [
            {"productId": p.get("productId"), "title": p.get("title"),
             "category": p.get("category"), "images": p.get("images") or [],
             "unit_price": p.get("unit_price"), "currency": p.get("currency"),
             "price_source": p.get("price_source")}
            for p in products
        ],
        "channel": body.get("channel"),
        "caliber_note": body.get("caliber_note"),
    })
    if not products:
        record["reason"] = ("该渠道当前没有已上架且有零售价的商品"
                            "（不是取数失败）")
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"写入 {out}（{len(products)} 件商品，channel={record.get('channel')}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
