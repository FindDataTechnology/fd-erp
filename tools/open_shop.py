#!/usr/bin/env python3
"""给一家新商家开店（change establish-ai-native-ecommerce-stack，C6 判据）。

**开张 = 填一份清单 + 跑一次这个脚本**，不改代码。脚本做四件事：

  1. 校验清单（缺项直接拒，MUST NOT 用默认值补齐后静默上线）
  2. 建租户 schema（内核侧，幂等）
  3. 建店面数据根（主数据/取价/编排的 JSONL 事件档，按租户分文件）
  4. 打印这家店的**部署三件套**：数据根、环境变量、四步验收命令

它**不碰任何别人的租户**：租户 id 不合白名单时内核自己会拒（`tenant_<slug>` 映射
失败即报错，不会静默截断——那会让两家店混进同一 schema）。

用法：
  python3 fd-erp/tools/open_shop.py tenants/example-shop.json
  python3 fd-erp/tools/open_shop.py tenants/example-shop.json --dry-run

清单（JSON）：
{
  "tenant_id": "acme2",                     必填，[a-z0-9_]，≤32
  "shop_title": "某某商店",                   必填
  "retail_channel": "retail-online",        必填：店面只出该渠道可见的商品
  "settlement": "offline_transfer",         必填：offline_transfer | paypal
  "payee": "商家自有的收款账户说明",           必填（钱进这里，平台不经手）
  "fulfillment": "own_warehouse",           必填：履约方式
  "data_dir": "/data",                      可选，缺省 /data
  "note": "一句话介绍"                        可选
}
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FD_ERP = Path(__file__).resolve().parents[1]
ROOT = FD_ERP.parent
for p in (ROOT / "fd-erp-ledger-mcp", ROOT / "fd-erp-vertical-templates"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

TENANT_RE = re.compile(r"^[a-z0-9_]{1,32}$")
REQUIRED = ("tenant_id", "shop_title", "retail_channel", "settlement",
            "payee", "fulfillment")
SETTLEMENTS = ("offline_transfer", "paypal")


def load_manifest(path: Path) -> dict:
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"读不到清单：{path}（{exc}）") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"清单不是合法 JSON：{path}（{exc}）") from exc
    if not isinstance(body, dict):
        raise SystemExit(f"清单必须是 JSON 对象：{path}")
    return body


def validate(m: dict) -> list[str]:
    """缺项与非法值逐条列出——一次报全，别让人改一条跑一次。"""
    problems: list[str] = []
    for key in REQUIRED:
        if not str(m.get(key) or "").strip():
            problems.append(f"缺必填项 {key}")
    tenant = str(m.get("tenant_id") or "")
    if tenant and not TENANT_RE.match(tenant):
        problems.append(
            f"tenant_id 非法：{tenant!r} —— 只允许小写字母/数字/下划线、长度 1-32"
            "（内核按 tenant_<slug> 建 schema，非法字符会被拒，且不能静默截断）")
    if tenant == "default":
        problems.append("tenant_id 不得为 default —— 那是租户 0（生产库本体 public schema）")
    settlement = str(m.get("settlement") or "")
    if settlement and settlement not in SETTLEMENTS:
        problems.append(f"settlement 须为 {SETTLEMENTS}，收到 {settlement!r}")
    return problems


def provision_schema(tenant: str, dsn: str | None) -> dict:
    """建租户 schema（内核侧）。无 DSN 时如实报「未建」，不假装成功。"""
    if not dsn:
        return {"ok": False, "reason": "未配置 ERP_LEDGER_DATABASE_URL（内核 schema 未建）"}
    from fd_erp_ledger_mcp.config import Settings as KernelSettings
    from fd_erp_ledger_mcp.db import close_pool, create_schema, migrate

    ks = KernelSettings(tenant_id=tenant, database_url=dsn)
    try:
        schema = create_schema(ks)
        applied = migrate(ks)
        return {"ok": True, "schema": schema,
                "applied_migrations": applied.get("applied") or []}
    except Exception as exc:  # noqa: BLE001  内核对非法租户/DDL 失败一律如上报
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    finally:
        close_pool(ks)


def provision_data_root(tenant: str, data_dir: Path) -> dict:
    """店面数据根：建目录并确认四类事件档的落点（不预写空文件）。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    return {"ok": True, "dir": str(data_dir),
            "files": [f"{kind}-{tenant}.jsonl" for kind in
                      ("masterdata", "pricing-rules", "orchestration",
                       "fulfillment")]}


def next_steps(m: dict, data_dir: Path) -> str:
    tenant = m["tenant_id"]
    title = m["shop_title"]
    channel = m["retail_channel"]
    return f"""
==== 这家店的部署三件套（复制到部署清单）====

# 1) 环境变量
ERP_TENANT_ID={tenant}
ERP_RETAIL_CHANNEL={channel}
ERP_API_DATA_DIR={data_dir}
ERP_LEDGER_DATABASE_URL=<与其它租户同一个库；schema 由脚本已建>

# 2) 店面快照与静态产物（在能访问该 API 的机器上跑）
STOREFRONT_API_BASE=<对外可达的 API 基址> STOREFRONT_TENANT={tenant} \\
  STOREFRONT_TITLE="{title}" \\
  python3 fd-erp/tools/collect_storefront_snapshot.py
python3 fd-erp/tools/gen_storefront.py

# 3) 四步验收（全部真发生才算开张）
curl -s "$BASE/shop/{tenant}/products" | python3 -m json.tool
curl -s -X POST "$BASE/shop/{tenant}/orders" -H 'Content-Type: application/json' \\
  -H "Idempotency-Key: open-$(date +%s)" \\
  -d '{{"lines":[{{"productId":"<code>","qty":1}}],\\
       "shipTo":{{"name":"验收","phone":"13800000000"}}}}'
curl -s -X POST "$BASE/shop/{tenant}/orders/<order_ref>/payment" \\
  -H "X-ERP-Tenant: {tenant}" -H 'Content-Type: application/json' \\
  -d '{{"amount":"<金额>","proofRef":"<流水号>"}}'
# 第 4 步：确认门（未到账必须被拒；到账后 confirmed + handoff）

收款：{m["settlement"]}（{m["payee"]}）
履约：{m["fulfillment"]}
钱进商家自有账户，平台不经手、不留存、不冲应收。
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="给一家新商家开店（清单 + 一次执行）")
    ap.add_argument("manifest", help="租户清单 JSON 路径")
    ap.add_argument("--dry-run", action="store_true", help="只校验，不建任何东西")
    ap.add_argument("--dsn-env", default="ERP_LEDGER_DATABASE_URL",
                    help="读内核 DSN 的环境变量名")
    args = ap.parse_args(argv)

    import os
    m = load_manifest(Path(args.manifest))
    problems = validate(m)
    if problems:
        print(f"清单不合规（{len(problems)} 处）——未建任何东西：")
        for p in problems:
            print(f"  x {p}")
        return 1

    tenant = str(m["tenant_id"])
    data_dir = Path(str(m.get("data_dir") or "/data"))
    if args.dry_run:
        print(f"清单通过（tenants={tenant}）。--dry-run：未建 schema、未建目录。")
        print(next_steps(m, data_dir))
        return 0

    schema = provision_schema(tenant, os.environ.get(args.dsn_env))
    root = provision_data_root(tenant, data_dir)
    print(json.dumps({"tenant": tenant, "schema": schema, "data_root": root},
                     ensure_ascii=False, indent=1))
    if not schema.get("ok"):
        print("\n注意：内核 schema 未建（见上）。店面读面与下单在 schema 建好前无法落账——"
              "先把 DSN 配好再重跑本脚本（幂等）。")
        return 2
    print(next_steps(m, data_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
