#!/usr/bin/env python3
"""把 histogram 桶集从契约生成到两个服务仓（单一出处，change 3.5）。

为什么要生成而不是「两边各写一份、用闸盯着」：
`semantics-contract.json` 里原来那条 `declared_deviations` 写的就是病因——
「两处 histogram 各自手写桶集，无共同出处」。用闸盯着能让两份**暂时**相等，
但它挡不住「有人只改一处、闸当时没跑」；而生成式把「真源在哪」变成一个
可执行事实：`observability.py` 里**不再允许出现桶集字面量**，只能 import
这个生成文件。改口径＝改契约数组 + 重跑本脚本。

用法：
  python3 fd-erp/tools/gen_metrics_buckets.py            # 生成/覆盖两仓的生成文件
  python3 fd-erp/tools/gen_metrics_buckets.py --check    # 只比对：0 一致 / 1 漂移 / 2 判不出
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "fd-erp" / "shared" / "semantics-contract.json"

HEADER = '''"""histogram 秒级桶集 —— **生成文件，勿手改**。

真源：`fd-erp/shared/semantics-contract.json` → `metrics.canonical.histogram_seconds_buckets`
生成器：`python3 fd-erp/tools/gen_metrics_buckets.py`
为什么生成：两处 histogram 各自手写时，一边加了 10.0 上界、另一边没有，而两边**各自都
自洽**（单测绿、Prometheus 也不报错）——只有跨服务比才看得出，于是必须有单一出处。
"""
from __future__ import annotations

SECONDS_BUCKETS: tuple[float, ...] = (
'''


def render(values: list[float]) -> str:
    body = "".join(f"    {v!r},\n" for v in values)
    return HEADER + body + ")\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比对，不写")
    args = ap.parse_args(argv)

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    canon = ((contract.get("metrics") or {}).get("canonical") or {})
    values = canon.get("histogram_seconds_buckets")
    files = canon.get("generated_files") or {}
    if not values or not files:
        print("判不出：契约缺 metrics.canonical.histogram_seconds_buckets / generated_files")
        return 2

    want = render(values)
    rc = 0
    missing: list[str] = []
    drift: list[str] = []
    for svc, rel in sorted(files.items()):
        path = ROOT / rel
        if not path.parent.is_dir():
            # CI 单仓 checkout 时兄弟仓不在场：这是「判不出」，不是「一致」
            missing.append(f"{svc}（{path.parent} 不在）")
            continue
        if args.check:
            if not path.is_file():
                drift.append(f"{svc}: 生成文件不存在 {rel}")
                continue
            if path.read_text(encoding="utf-8") != want:
                drift.append(f"{svc}: {rel} 与契约不一致")
            continue
        path.write_text(want, encoding="utf-8")
        print(f"写入 {rel}（{len(values)} 个桶）")

    if not args.check:
        return 0
    if drift:
        print("桶集生成文件已漂移（改契约后重跑 gen_metrics_buckets.py）：")
        for d in drift:
            print("  -", d)
        return 1
    if missing:
        print("判不出：兄弟仓不在场，未比对 " + "、".join(missing))
        return 2
    print(f"histogram 桶集：{len(files)} 个生成文件与契约一致（{len(values)} 个桶）")
    return rc


if __name__ == "__main__":
    sys.exit(main())
