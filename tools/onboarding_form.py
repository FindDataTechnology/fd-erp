#!/usr/bin/env python3
"""待接入格子的接入表：列出 / 渲染 / 校验答案（只读，永不写盘）。

change: make-onboarding-intake-executable。

为什么要有这个入口：覆盖矩阵里 5 个格子停在 `needs_onboarding`，等客户给口径。散文 blocker
回答了「等什么」，但没回答「怎么问、答案长什么样、答完生成什么」。接入表把这三件事写进矩阵；
本工具让它能被念出来、被填、被当场验——客户答完，合法性当场就知道，不必等我们回去写代码才发现
答案对不上。

用法：
  python3 fd-erp/tools/onboarding_form.py list
  python3 fd-erp/tools/onboarding_form.py cost-accounting
  python3 fd-erp/tools/onboarding_form.py cost-accounting --answers answers.json

答案文件形如：
  {"cost_method": "weighted-average",
   "inputs": {"opening_inventory": "opening-2026-11.csv"}}

退出码：0 通过 / 1 校验不过 / 2 输入不可读（格子不存在、答案文件坏）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "fd-erp" / "shared" / "coverage-matrix.json"

DERIVED_KINDS = ("posting-rule", "rule", "schema", "projection", "report", "connector")


def load_matrix(path: Path = MATRIX) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pending_cells(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    return [m for m in matrix.get("modules") or []
            if m.get("state") == "needs_onboarding"]


def find_cell(matrix: dict[str, Any], mid: str) -> dict[str, Any]:
    for m in matrix.get("modules") or []:
        if m.get("id") == mid:
            return m
    raise KeyError(mid)


def _intake(cell: dict[str, Any]) -> dict[str, Any]:
    intake = cell.get("intake")
    if not isinstance(intake, dict):
        raise ValueError(f"{cell.get('id')} 没有 intake（needs_onboarding 必须写接入表）")
    return intake


# ---- list ----


def cmd_list(matrix: dict[str, Any]) -> int:
    rows = []
    for cell in pending_cells(matrix):
        intake = cell.get("intake") or {}
        qs = intake.get("questions") or []
        ins = intake.get("inputs") or []
        dv = intake.get("derived") or []
        rows.append((cell["id"], cell.get("name_zh") or "",
                     intake.get("kind") or "—", len(qs), len(ins), len(dv)))
    print(f"{'格子':<18}{'名称':<10}{'种类':<18}{'问项':>4}{'材料':>4}{'产物':>4}")
    for mid, zh, kind, nq, ni, nd in rows:
        print(f"{mid:<18}{zh:<10}{kind:<18}{nq:>4}{ni:>4}{nd:>4}")
    print(f"\n共 {len(rows)} 个待接入格（state=needs_onboarding）")
    return 0


# ---- render ----


def cmd_render(matrix: dict[str, Any], mid: str) -> int:
    cell = find_cell(matrix, mid)
    intake = _intake(cell)
    print(f"# {cell.get('name_zh')}（{mid}）· 接入表\n")
    print(f"种类：{intake.get('kind')}")
    if intake.get("note"):
        print(f"为什么需要：{intake['note']}")
    if intake.get("doc"):
        print(f"接入文档：{intake['doc']}")
    print()

    print("## 一、要客户做的选择（枚举，选一个）")
    for i, q in enumerate(intake.get("questions") or [], start=1):
        print(f"\n{i}. {q.get('ask')}  [{q.get('id')}]")
        if q.get("why"):
            print(f"   为什么必须定：{q['why']}")
        for opt in q.get("options") or []:
            print(f"   - {opt.get('zh')}（{opt.get('value')}）")
            print(f"     影响：{opt.get('impact')}")
        if q.get("other_allowed"):
            print(f"   - 其它（other）：{q.get('other_note') or '需补说明'}")

    inputs = intake.get("inputs") or []
    print("\n## 二、要客户交的材料")
    if not inputs:
        print("（无——本格没有材料要求）")
    for item in inputs:
        req = "必填" if item.get("required", True) else "选填"
        print(f"- {item.get('ask')}  [{item.get('id')}]  ({req})")
        print(f"  格式：{item.get('format')}")

    print("\n## 三、答案到位后生成")
    for d in intake.get("derived") or []:
        print(f"- {d}")
    print("\n提示：答案用 `--answers <file>` 提交校验，本工具只读、不落盘。")
    return 0


# ---- validate ----

DEFAULT_ANSWER_KEYS = ("inputs",)


def validate_answers(cell: dict[str, Any], answers: dict[str, Any]) -> list[str]:
    """校验答案；返回问题清单（空表示通过）。纯函数，便于直接单测。"""
    intake = _intake(cell)
    problems: list[str] = []
    questions = intake.get("questions") or []
    for q in questions:
        qid = str(q.get("id") or "")
        if qid not in answers:
            problems.append(f"[缺答案] {qid}：{q.get('ask')} 未作答")
            continue
        allowed = {str(o.get("value")) for o in (q.get("options") or [])}
        given = str(answers[qid])
        if given not in allowed:
            if given == "other" and q.get("other_allowed"):
                if not str(answers.get(f"{qid}_note") or "").strip():
                    problems.append(
                        f"[其它需说明] {qid}：选了 other 必须补 {qid}_note"
                        f"（{q.get('other_note') or '材料说明'}）")
                continue
            problems.append(
                f"[答案越界] {qid}={given!r} 不在候选 {sorted(allowed)} 内")

    given_inputs = answers.get("inputs") or {}
    if not isinstance(given_inputs, dict):
        problems.append("[材料格式] inputs 须为对象：{材料id: 值}")
        given_inputs = {}
    for item in intake.get("inputs") or []:
        iid = str(item.get("id") or "")
        required = item.get("required", True)
        val = str(given_inputs.get(iid) or "").strip()
        if required and not val:
            problems.append(
                f"[缺材料] {iid}：{item.get('ask')} 为必填（格式：{item.get('format')}）")
    unknown = sorted(set(given_inputs) - {str(i.get("id")) for i in intake.get("inputs") or []})
    if unknown:
        problems.append(f"[材料未知] 接入表里没有这些材料项：{', '.join(unknown)}")
    return problems


def cmd_validate(matrix: dict[str, Any], mid: str, answers_path: Path) -> int:
    try:
        cell = find_cell(matrix, mid)
        answers = json.loads(answers_path.read_text(encoding="utf-8"))
    except (KeyError, OSError, json.JSONDecodeError) as exc:
        print(f"✗ 输入不可读：{exc}", file=sys.stderr)
        return 2
    if not isinstance(answers, dict):
        print("✗ 答案文件须为 JSON 对象", file=sys.stderr)
        return 2
    problems = validate_answers(cell, answers)
    if problems:
        print(f"✗ {mid} 接入表校验不通过（{len(problems)} 项）：")
        for p_ in problems:
            print(f"  - {p_}")
        return 1
    print(f"✓ {mid} 接入表校验通过。答案到位后生成的产物：")
    for d in _intake(cell).get("derived") or []:
        print(f"  - {d}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="待接入格子的接入表（只读）")
    ap.add_argument("module", nargs="?", help="矩阵格子 id；省略则等价于 list")
    ap.add_argument("--answers", help="答案文件（JSON）；给了就进入校验模式")
    ap.add_argument("--matrix", default=str(MATRIX), help="覆盖矩阵路径")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出（list/渲染的结构化形式）")
    args = ap.parse_args(argv)

    try:
        matrix = load_matrix(Path(args.matrix))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"✗ 覆盖矩阵不可读：{exc}", file=sys.stderr)
        return 2

    if not args.module or args.module == "list":
        if args.json:
            print(json.dumps(
                [{"id": c["id"], "name": c.get("name_zh"),
                  "intake": c.get("intake")} for c in pending_cells(matrix)],
                ensure_ascii=False, indent=1))
            return 0
        return cmd_list(matrix)

    try:
        cell = find_cell(matrix, args.module)
    except KeyError:
        print(f"✗ 没有这个格子：{args.module}", file=sys.stderr)
        return 2
    if cell.get("state") != "needs_onboarding":
        print(f"✗ {args.module} 的 state 是 {cell.get('state')}，不是 needs_onboarding",
              file=sys.stderr)
        return 2

    if args.answers:
        return cmd_validate(matrix, args.module, Path(args.answers))
    if args.json:
        print(json.dumps(cell.get("intake"), ensure_ascii=False, indent=1))
        return 0
    return cmd_render(matrix, args.module)


if __name__ == "__main__":
    raise SystemExit(main())
