#!/usr/bin/env python3
"""把一家已开张的店登记进目录（change establish-ai-native-trade-discovery 1.2）。

**类目与关键词从店面公开读面派生，不手写**：手写的东西必然与店面实际商品脱节，
而且脱节了没人会发现。本脚本向 `/shop/{tenant}/products` 取一次全量，聚合
`category` 与 `title`，再写进目录。

用法：
  python3 fd-erp/tools/register_shop.py --tenant acme \\
      --public-base https://erp.finddatatech.cloud/shop-api \\
      --directory http://127.0.0.1:8099 --token "$SHOP_DIRECTORY_WRITE_TOKEN"

  # 店面读面就在本机（不需要公网）
  python3 fd-erp/tools/register_shop.py --tenant acme \\
      --shop-api http://127.0.0.1:8088 --directory http://127.0.0.1:8099 --token t

四态退出码（与 chain-electrification 同口径）：0 成功 / 1 店面不可读（未登记，不留半条）/
2 参数缺失 / 3 目录不可达。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _get(url: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def _post(url: str, body: dict, token: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "x-directory-write-token": token},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def derive(shop_api: str, tenant: str) -> tuple[list[str], list[str], str]:
    """从店面公开读面派生类目/关键词/标题。读不到就抛——**绝不用空类目登记**。"""
    body = _get(f"{shop_api.rstrip('/')}/shop/{tenant}/products")
    rows = body.get("data") or []
    cats = sorted({str(r.get("category")).strip() for r in rows
                   if str(r.get("category") or "").strip()})
    kws = sorted({str(r.get("title")).strip() for r in rows
                  if str(r.get("title") or "").strip()})
    return cats, kws, (f"{tenant} 商店" if not kws else f"{tenant} 商店")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--shop-api", required=True,
                    help="店面 API 基址（用于派生类目与关键词）")
    ap.add_argument("--public-base", required=True,
                    help="对外可达的店面地址（检索结果里回给调用方）")
    ap.add_argument("--directory", required=True)
    ap.add_argument("--token", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--region", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if not a.token and not a.dry_run:
        print("缺 --token（目录写令牌）", file=sys.stderr)
        return 2

    try:
        cats, kws, auto_title = derive(a.shop_api, a.tenant)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        # 店面读不到 ⇒ 不登记。留一条空类目的记录会让这家店「存在但搜不到」，
        # 比不登记更难发现（设计 D2 / Risks）。
        print(f"店面公开读面不可读，未登记：{exc}", file=sys.stderr)
        return 1
    if not cats:
        print("店面没有任何已上架商品（无类目可派生），未登记", file=sys.stderr)
        return 1

    body = {"tenant": a.tenant, "title": a.title or auto_title,
            "public_base": a.public_base.rstrip("/"),
            "categories": cats, "keywords": kws, "region": a.region}
    if a.dry_run:
        print(json.dumps({"would_register": body}, ensure_ascii=False, indent=1))
        return 0
    try:
        out = _post(f"{a.directory.rstrip('/')}/directory/shops", body, a.token)
    except urllib.error.HTTPError as exc:
        print(f"目录拒绝：HTTP {exc.code} {exc.read()[:300]}", file=sys.stderr)
        return 3
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"目录不可达：{exc}", file=sys.stderr)
        return 3

    # 登记后立刻自查：检索必须能命中这家店（否则「登记成功」是纸面的）。
    try:
        hit = _get(f"{a.directory.rstrip('/')}/directory/search?tenant={a.tenant}")
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"登记已写入，但自查检索失败：{exc}", file=sys.stderr)
        return 3
    ok = hit.get("state") == "matched"
    print(json.dumps({"register": out, "verify": {"state": hit.get("state"),
                                                  "matched_count": hit.get("matched_count")}},
                     ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
