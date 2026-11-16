#!/usr/bin/env python3
"""规格归属的**可复算**判据（不能靠「记住 19 条」）。

判据为什么不写死一个数：`erp-*`/`ecommerce-*` 的条数每加一个 capability 就变，
写死会让这条闸要么常年红、要么被人随手改数字改绿 —— 两种都会让「归属有没有边界」
这个问题重新变成没人回答。所以这里只做三件可复算的事：

1. 从 `openspec/specs` **现枚举**前缀命中的 spec（判据就是任务里写的那行
   `ls openspec/specs | grep -c '^erp-\\|^ecommerce-'`）；
2. 每个命中的名字必须是**含 spec.md 的目录**（防止把归档残留/空目录算进来，
   同族于「按目录枚举会让 flat 布局整个隐身」）；
3. 与 `manifest.json` 的 `specs.observed` 对账：
   - 变多 ⇒ 只打 FACTS 行并提示重跑（新加 capability 是常态，不该判红）；
   - 变少 ⇒ **退出 1**（spec 不见了是事故，不是常态）；
   - 读不到 openspec 根 ⇒ **退出 2 判不出**，绝不退化成「一致」。

退出码口径与 `check_all.py` 一致：0 通过 / 1 命中 / 2 判不出。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "fd-erp" / "manifest.json"


def main() -> int:
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    spec = m.get("specs") or {}
    root_rel = spec.get("openspec_root", "openspec/specs")
    prefixes = spec.get("name_prefixes") or []
    if not prefixes:
        print("判不出：manifest.specs.name_prefixes 为空 —— 没有枚举面就没有这条判据")
        return 2

    spec_dir = ROOT / root_rel
    if not spec_dir.is_dir():
        print(f"判不出：{root_rel} 不在（CI 单仓形态看不到工作区 openspec 根）—— 这不是「一致」")
        return 2

    hit = sorted(d for d in spec_dir.iterdir() if d.is_dir() and any(d.name.startswith(p) for p in prefixes))
    live = {p: sum(1 for d in hit if d.name.startswith(p)) for p in prefixes}
    live["total"] = len(hit)

    # ② 必须是含 spec.md 的目录
    bad = [d.name for d in hit if not (d / "spec.md").is_file()]
    if bad:
        print(f"✗ {len(bad)} 个命中目录没有 spec.md：{', '.join(bad[:6])}"
              f"{' …' if len(bad) > 6 else ''}")
        return 1

    observed = spec.get("observed") or {}
    parts = " ".join(f"{p.rstrip('-')}={live[p]}" for p in prefixes)
    print(f"✓ 规格归属：{root_rel} 下 {parts} 合计 {live['total']}，全部是含 spec.md 的目录")

    if not observed:
        print("· manifest.specs.observed 缺失 —— 无法对账（不是失败，但也没证明过）")
        return 0

    for p in prefixes:
        key = p.rstrip("-")
        was, now = observed.get(key), live[p]
        if was is None:
            continue
        if now < was:
            print(f"✗ {key} 类 spec 从 {was} 减到 {now} —— spec 消失是事故，不是常态；"
                  f"确认是退役（有 REMOVED 记录）后再改 manifest.specs.observed")
            return 1
        if now > was:
            print(f"· {key} 类 spec 从 {was} 增到 {now} —— 新加 capability 是常态，"
                  f"重生成文档后把 observed 更新到 {now} 即可（本闸不判红）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
