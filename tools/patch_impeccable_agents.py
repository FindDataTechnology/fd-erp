#!/usr/bin/env python3
"""给 `impeccable install` 装出来的子代理补上实测出来的四个盲区。

为什么需要一个补丁器，而不是直接改 skill 包：
  `impeccable install` 是**联网拉包再整体覆盖**到项目的 `.claude/agents/`。它既不读
  `~/.agents/skills/impeccable/agents/*.toml`（本地那份是陈旧镜像，实测正文 14954 vs
  安装产物 15370 字符），也不从二进制里取明文。所以：改 toml 永远不生效，而重跑
  install 会把手工补丁冲掉。这个脚本就是冲掉之后重打的那一下。

用法：
  python3 tools/patch_impeccable_agents.py                # 就地补齐（幂等）
  python3 tools/patch_impeccable_agents.py --check        # 只判在不在位（给闸用）
  python3 tools/patch_impeccable_agents.py --dir <path>   # 指定 .claude/agents 目录

退出码：
  0 已到位 / 本次补齐成功
  1 --check 模式下有缺失
  2 找不到目标目录（没有装过 impeccable，不算失败也不算通过）
  3 上游改版了：锚点找不到，补丁不能盲打（必须先看新文案再改锚点）

每条补丁都来自 2026-11-11 重做 ERP 站点时的真实事故，锚点用原文整句，避免"差不多的
位置"这种会漂的定位。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[1] / ".claude" / "agents"

# ---------------------------------------------------------------- 补丁定义
# marker: 只有打上之后才存在的独有串（用来判幂等）
# edits:  [(anchor, replacement), ...]  anchor 必须在上游原文里恰好出现一次

FINISH_REVIEWER = {
    "file": "impeccable-finish-reviewer.md",
    "why": "截图看不见横向溢出 / 新增 GEOMETRY 行 / 审的字节必须是发出的字节",
    "marker": "GEOMETRY: at every captured width",
    "edits": [
        # 1) 证据检查：截图对横向溢出是结构性盲的
        (
            "A required capture that is absent fails exactly like one that is malformed: "
            "a viewport nobody captured is a viewport nobody inspected, and it cannot ship.",
            "A required capture that is absent fails exactly like one that is malformed: "
            "a viewport nobody captured is a viewport nobody inspected, and it cannot ship. "
            "A capture is also structurally blind to document overflow: a 390-wide image "
            "cropped from a 500-wide viewport and a genuinely overflowing page look the same, "
            "so require one measured line per captured width — "
            "`document.documentElement.scrollWidth` against `innerWidth`, plus every element "
            "whose right edge passes `innerWidth` — and treat a missing measurement as a "
            "missing capture. A reported viewport the capture does not actually use is a "
            "malformed capture, not a smaller one.",
        ),
        # 2) 矩阵三行 → 四行（新增 GEOMETRY）
        (
            "Three rows are mandatory in every matrix.",
            "Four rows are mandatory in every matrix.",
        ),
        (
            "GROUND: the page field's value and temperature against the comp's",
            "GEOMETRY: at every captured width, no element's box overlaps another element's "
            "text, no absolutely-positioned decoration escapes its containing block, and no "
            "text is clipped at the viewport edge. A detector samples declarations, not "
            "layout — a clean detector run says nothing here — and a stamp, badge, or tooltip "
            "sitting on a paragraph is a material fix whatever the comp shows.\n\n"
            "GROUND: the page field's value and temperature against the comp's",
        ),
        # 3) 产物同一性：生成物/多入口/仓自带文案闸
        (
            "6. **Floor.**",
            "5b. **Artifact identity.** When the artifact is generated or deployed, the bytes "
            "you reviewed must be the bytes that ship: run the repo's own "
            "regenerate-and-diff gate, and when the surface is served from more than one "
            "place, require a digest comparison across every entry point and treat any "
            "difference as a material fix. When the repo owns a copy or claims gate, run it "
            "and report its result; a factual string silently reworded while restyling is a "
            "material fix even when it reads better.\n\n"
            "6. **Floor.**",
        ),
    ],
}

DOCUMENTER = {
    "file": "impeccable-documenter.md",
    "why": "记测量不记形容词（并顺延编号）",
    "marker": "Record measurements, not adjectives",
    "edits": [
        (
            "4. Two ways a recorded rule goes wrong, both observed live:",
            "4. Record measurements, not adjectives. \"The muted text is legible\" is worthless "
            "to the next surface; \"`--ink-3` on `--paper-2` measures 4.9:1, raised from 4.42\" "
            "is a rule someone can keep or break. Same for type sizes, measure widths, and "
            "capture provenance: name the viewport each screenshot was taken at and the file "
            "it came from, because an unlabelled capture cannot be rechecked and a claimed "
            "viewport the image does not use is worse than no capture.\n\n"
            "5. Two ways a recorded rule goes wrong, both observed live:",
        ),
        (
            "5. Never canonize a craft-floor refusal into the system:",
            "6. Never canonize a craft-floor refusal into the system:",
        ),
    ],
}

PATCHES = [FINISH_REVIEWER, DOCUMENTER]


def apply_patch(target: Path, spec: dict, *, check: bool) -> tuple[str, str]:
    """返回 (状态, 说明)。状态：applied / missing / drifted / absent。"""
    path = target / spec["file"]
    if not path.is_file():
        return "absent", f"{spec['file']} 不在（没有装过 impeccable？）"

    text = path.read_text(encoding="utf-8")
    if spec["marker"] in text:
        return "applied", f"{spec['file']}：已在位（{spec['why']}）"

    if check:
        return "missing", f"{spec['file']}：缺补丁（{spec['why']}）"

    # 打之前先整份验证所有锚点，避免打一半留下半成品
    work = text
    for anchor, replacement in spec["edits"]:
        n = work.count(anchor)
        if n != 1:
            return ("drifted",
                    f"{spec['file']}：锚点命中 {n} 次（应为 1）——上游文案变了，"
                    f"先看新文案再改锚点：{anchor[:60]}…")
        work = work.replace(anchor, replacement)

    path.write_text(work, encoding="utf-8")
    return "applied", f"{spec['file']}：已补齐（{spec['why']}）"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(DEFAULT_DIR), help=".claude/agents 目录")
    ap.add_argument("--check", action="store_true", help="只判在位，不写入")
    args = ap.parse_args()

    target = Path(args.dir)
    if not target.is_dir():
        print(f"  SKIP 找不到 {target}（未安装 impeccable，不作为通过）")
        return 2

    states: list[tuple[str, str]] = []
    for spec in PATCHES:
        states.append(apply_patch(target, spec, check=args.check))

    for state, note in states:
        mark = {"applied": "PASS", "missing": "FAIL", "drifted": "FAIL", "absent": "SKIP"}[state]
        print(f"  {mark:<4} {note}")

    if any(s == "drifted" for s, _ in states):
        print("\nimpeccable 子代理补丁：上游改版，拒绝盲打")
        return 3
    if args.check and any(s == "missing" for s, _ in states):
        print("\nimpeccable 子代理补丁：缺失（重跑 install 后需要补）")
        return 1
    if all(s == "absent" for s, _ in states):
        return 2
    print("\nimpeccable 子代理补丁：到位")
    return 0


if __name__ == "__main__":
    sys.exit(main())
