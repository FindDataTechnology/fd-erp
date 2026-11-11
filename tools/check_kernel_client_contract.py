#!/usr/bin/env python3
"""内核工具面 × 客户端覆盖面 的契约闸（跨仓，只读）。

背景：`tool-surface.json` 是内核工具面的单一出处，但没有人回答"每条消费仓盖了多少、
漏掉的是故意不盖还是忘了盖"。结果是签名靠人肉对齐、缺口靠 grep 猜。

本闸把"故意不盖"变成声明：
  1. 每个消费仓声明的必须覆盖集合，必须与客户端实际方法集合逐名相等；
  2. 未覆盖的工具必须逐条在 `intentionally_absent` 里给出理由 —— 说不出理由就是缺口；
  3. 客户端里不得出现工具面之外的发明方法。

用法：
  python3 fd-erp/tools/check_kernel_client_contract.py
  python3 fd-erp/tools/check_kernel_client_contract.py --json
退出码：0 一致 / 1 有违规 / 2 出处缺失
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "fd-erp" / "shared" / "kernel-client-contract.json"


def surface_tools() -> list[str]:
    p = ROOT / "fd-erp-ledger-mcp" / "tool-surface.json"
    if not p.is_file():
        raise SystemExit(f"缺少工具面出处：{p.relative_to(ROOT)}")
    return sorted(json.loads(p.read_text(encoding="utf-8"))["tool_annotations"])


def client_methods(rel_path: str, classes: list[str]) -> dict[str, set[str]]:
    """按类收集公开方法名（不含下划线开头、不含构造）。"""
    p = ROOT / rel_path
    if not p.is_file():
        raise SystemExit(f"缺少客户端文件：{rel_path}")
    tree = ast.parse(p.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {c: set() for c in classes}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in classes:
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not item.name.startswith("_") and item.name != "__init__":
                    out[node.name].add(item.name)
    return out


def check() -> dict:
    tools = surface_tools()
    tool_set = set(tools)
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    violations: list[dict] = []
    rows: list[dict] = []

    for consumer in contract["consumers"]:
        repo = consumer["repo"]
        methods = client_methods(consumer["client"], consumer["classes"])
        actual: set[str] = set()
        for cls, names in methods.items():
            if not names:
                violations.append({
                    "code": "CLIENT_CLASS_EMPTY",
                    "message": f"{repo} 的 {cls} 未找到任何公开方法（类名改了？路径：{consumer['client']}）",
                })
            actual |= names

        declared_cover = set(consumer["must_cover"])
        declared_absent = set(consumer["intentionally_absent"])

        # ① 声明必须自洽：覆盖 + 故意不覆盖 = 工具面，且不重叠
        if declared_cover & declared_absent:
            violations.append({
                "code": "DECLARATION_OVERLAP", "repo": repo,
                "message": f"同时声明为覆盖与不覆盖：{sorted(declared_cover & declared_absent)}",
            })
        if declared_cover | declared_absent != tool_set:
            missing = tool_set - (declared_cover | declared_absent)
            extra = (declared_cover | declared_absent) - tool_set
            violations.append({
                "code": "DECLARATION_INCOMPLETE", "repo": repo,
                "message": f"声明未覆盖工具面全集：漏 {sorted(missing)} 多 {sorted(extra)}",
            })

        # ② 实际必须等于声明
        if actual != declared_cover:
            violations.append({
                "code": "CLIENT_DRIFT", "repo": repo,
                "message": (f"客户端实际方法与声明不一致："
                            f"多出 {sorted(actual - declared_cover)} "
                            f"缺少 {sorted(declared_cover - actual)}"),
            })

        # ③ 不得发明工具面之外的方法
        invented = actual - tool_set
        if invented:
            violations.append({
                "code": "INVENTED_METHOD", "repo": repo,
                "message": f"客户端出现工具面之外的方法：{sorted(invented)}",
            })

        # ④ 故意不覆盖的每一条必须有理由
        for name in sorted(declared_absent):
            reason = (consumer["intentionally_absent"][name] or "").strip()
            if len(reason) < 6:
                violations.append({
                    "code": "ABSENT_WITHOUT_REASON", "repo": repo,
                    "message": f"{name} 标为故意不覆盖但没给出可读理由",
                })

        rows.append({
            "repo": repo,
            "covered": len(actual & tool_set),
            "absent": len(declared_absent),
            "surface": len(tool_set),
        })

    return {"ok": not violations, "violations": violations, "rows": rows,
            "surface": len(tool_set)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result = check()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0 if result["ok"] else 1

    print(f"内核工具面：{result['surface']} 个工具")
    for r in result["rows"]:
        print(f"  {r['repo']:<32} 覆盖 {r['covered']:>2}/{r['surface']}  声明不覆盖 {r['absent']:>2}")
    if result["ok"]:
        print("契约闸：通过（声明 = 实际，未覆盖项均有理由）")
        return 0
    print(f"契约闸：阻断（{len(result['violations'])} 处）")
    for v in result["violations"]:
        print(f"  x [{v['code']}] {v.get('repo','')} {v['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
