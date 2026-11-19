#!/usr/bin/env python3
"""刷新营销事实读数快照（change prove-line-seams，`line-seam-proof` 的定时读者）。

**为什么单独一个脚本**：`gen_erp_docs.py` 是纯本地产物生成器，它的 `--check`
要在没有数据库的 CI 上跑得绿。把连库塞进生成器会让「生成物可复现」与「数字真不
真」互相绑架：有库的机器绿、没库的机器红，而两边跑的其实是同一份代码。

所以分工是：

    本脚本（连库，定时跑） → shared/marketing-volume.json（快照）
    gen_erp_docs.py（不连库） → README/site 从快照渲染

**账本库是每租户一个 schema**（`tenant_acme` 等），public 下没有表。2026-11-19
在真库上验过：不加 schema 限定就是 `UndefinedTable`，而测试库因为只有单 schema
而绿——那种绿是假绿。这里按 `pg_namespace` 枚举全部 `tenant_*` 再合并。

退出码（与 `line-seam-proof` 三值口径一致）：
  0  快照已写入
  2  判不出（无 DSN / psycopg 缺失 / 连不上）——**仍写快照**，但写的是
     `available: false` + 原因，好让下游如实渲染「未取得」而不是 0

用法：
  python3 tools/refresh_marketing_volume.py
  python3 tools/refresh_marketing_volume.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
#: 输出路径。默认落在仓库里；在 pod（ConfigMap 挂载、没有仓库）里由环境变量给。
OUT = Path(os.environ.get("MARKETING_VOLUME_OUT") or (ROOT / "fd-erp" / "shared" / "marketing-volume.json"))

#: 共享契约文件都带 schema 标签（`check_all.py` 的 CONTRACT_NO_SCHEMA 判据）。
SCHEMA = "erp-marketing-volume/v1"

DSN_ENV = "ERP_LEDGER_DATABASE_URL"

#: **按「有没有这张表」枚举，不按名字前缀。** 内核的租户 0 叫 `default` 且映射到
#: `public` schema（`tenancy.schema_for()`）——只认 `tenant_*` 会把 default 租户整个
#: 漏掉，而它的数据恰恰在 `public` 里。判据是事实（表存在），不是命名约定。
_TENANT_SCHEMA_SQL = (
    "SELECT schemaname FROM pg_tables "
    " WHERE tablename = 'business_events' "
    "   AND schemaname NOT IN ('pg_catalog', 'information_schema') "
    " ORDER BY (schemaname = 'public') DESC, schemaname"
)


def read_volume(dsn: str) -> tuple[dict | None, str | None]:
    """``(by_producer, reason)`` — exactly one is non-None."""
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        return None, "未取得：事件库（psycopg 不可用）"
    try:
        with psycopg.connect(dsn, connect_timeout=5) as conn, \
                conn.cursor(row_factory=dict_row) as cur:
            schemas = [r["schemaname"] for r in cur.execute(_TENANT_SCHEMA_SQL).fetchall()]
            if not schemas:
                return None, "未取得：事件库（库里没有 tenant_* schema）"
            rows: list[dict] = []
            for schema in schemas:
                # schema 来自 pg_namespace（不是用户输入）；仍走标识符引用。
                cur.execute(
                    "SELECT et.producer AS producer, e.event_type AS event_type, "
                    "       COUNT(*) AS n, MAX(e.occurred_at) AS last_at "
                    f'  FROM "{schema}".business_events e '
                    f'  JOIN "{schema}".event_types et ON et.event_type = e.event_type '
                    " GROUP BY et.producer, e.event_type"
                )
                rows.extend(cur.fetchall())
    except Exception as exc:  # noqa: BLE001 — 连不上是「判不出」，不是崩溃
        return None, f"未取得：事件库（{type(exc).__name__}）"

    by_producer: dict[str, list[dict]] = {}
    for r in rows:
        by_producer.setdefault(r["producer"], []).append({
            "event_type": r["event_type"],
            "count": r["n"],
            "last_at": r["last_at"].isoformat() if r.get("last_at") else None,
        })
    return by_producer, None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="刷新营销事实读数快照")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    dsn = os.environ.get(DSN_ENV, "").strip()
    as_of = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if not dsn:
        body = {"schema": SCHEMA, "available": False, "as_of": as_of,
                "reason": f"未取得：事件库（{DSN_ENV} 未配置）"}
        code = 2
    else:
        by_producer, reason = read_volume(dsn)
        if reason is not None:
            body = {"schema": SCHEMA, "available": False, "as_of": as_of, "reason": reason}
            code = 2
        else:
            body = {"schema": SCHEMA, "available": True, "as_of": as_of,
                    "by_producer": by_producer}
            code = 0

    text = json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if args.dry_run:
        sys.stdout.write(text)
    else:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text, encoding="utf-8")
        # 快照内容也上 stdout：在集群里跑时日志是唯一的读数通道，只写文件等于
        # 「跑了但没人看得见」——`line-seam-proof` 要求读数可从作业日志读到。
        sys.stdout.write(text)
        try:
            shown = OUT.relative_to(ROOT)
        except ValueError:
            shown = OUT            # pod 里 OUT 不在仓库内，照原样打
        print(f"wrote {shown}：{'可用' if body['available'] else body['reason']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
