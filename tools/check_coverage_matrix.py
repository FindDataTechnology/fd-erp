#!/usr/bin/env python3
"""ERP 全覆盖矩阵闸（change establish-erp-event-kernel 6.2 / establish-erp-kernel-toolkit-and-teams 2.2，只读）。

它回答的不是「矩阵格式对不对」，而是「矩阵说的和仓里/对外说的是不是同一件事」：

  1. 格子封闭   —— module_set 与 modules 一一对应，不多不少不重复；四态之外无状态。
  2. 证据可解析 —— delivered/template_configured/needs_onboarding 的证据必须在仓内解析得到，
                   kind=tool 去 tool-surface.json 查、kind=endpoint 去 vertical-api 源码查、
                   kind=file 查文件存在与 contains 子串；**不得用行号锚**（行号会漂）。
  3. 不做需留档 —— not_doing 必须给 reason + decided_by + review_by 三项。
  4. 不做不得被宣称 —— not_doing 模块引用的 claim 不得是 status=delivered。
  5. 待接入说清缺什么 —— needs_onboarding 必须有 blocker。
  6. 连接器事实不漂移 —— 矩阵声明上游 provider 缺口时，连接器仓事实必须仍显缺口；
                        已补齐而矩阵仍记「需接入」即判红（缺口两分类见 erp-connector-onboarding）。
  7. 承担者可指认 —— 每格恰好一个 owner（fleet|template|none）；none 只在 needs_onboarding/
                    not_doing 合法且必须给 reason（delivered/template_configured 写 none 即
                    「纸上能力」，判红）；fleet 的 ref 必须是 kebab-case 团队名（建议 -fleet 结尾，
                    不强制）；template 的 ref 必须是仓内/工作区相对路径且能落到文件。
                    **不查团队是否真实存在**：那是 fleet-packs 侧团队覆盖闸的职责（读本矩阵，
                    见 design D4）。本闸不反查兄弟仓，故 fd-erp 的闸链不受兄弟仓缺席影响；
                    跨仓路径缺失只记 warning 并注明「跨仓不可核」，仓内路径缺失判红。

用法：
  python3 fd-erp/tools/check_coverage_matrix.py
  python3 fd-erp/tools/check_coverage_matrix.py --json
退出码：0 全通过 / 1 有违规 / 2 出处缺失
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
FD_ERP = ROOT / "fd-erp"
MATRIX = ROOT / "fd-erp" / "shared" / "coverage-matrix.json"
TOOL_SURFACE = ROOT / "fd-erp-ledger-mcp" / "tool-surface.json"
VERTICAL_API = ROOT / "fd-erp-vertical-api" / "fd_erp_vertical_api"
CLAIMS = ROOT / "fd-erp-vertical-templates" / "claims" / "claims.json"
CONNECTOR_STATUS = ROOT / "fd-erp-vertical-templates" / "connector-status.json"

VALID_STATES = {"delivered", "template_configured", "needs_onboarding", "not_doing"}
#: 承担者三形态（spec erp-board-coverage「全覆盖指决策空间全覆盖」）。
OWNER_KINDS = {"fleet", "template", "none"}
#: 只有这两态允许「无承担者」：已具备的能力必须有人执行，否则是纸上能力。
OWNER_NONE_STATES = {"needs_onboarding", "not_doing"}
#: 团队名形状：kebab-case。-fleet 结尾是建议不是强制（既有行业舰队不带该后缀）。
KEBAB_CASE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
#: 行号锚：`foo.py:123` 或 `foo.py#L12`。行号会随改动漂移，证据必须锚在符号上。
LINE_ANCHOR = re.compile(r"(:\d+(?::\d+)?$|#L\d+)")
#: 边界句特征：宣称的内容是「我们不做什么」。这类 delivered claim 与 not_doing 不矛盾——
#: 它断言的正是那条红线本身（如「零资金执行面」）。用词与 claim_gate 的否定标记同源。
BOUNDARY_MARKERS = ("不提供", "不自研", "不执行", "禁止", "零", "无资金")


def _is_boundary_claim(entry: dict) -> bool:
    text = entry.get("capability") or ""
    return any(marker in text for marker in BOUNDARY_MARKERS)


def _resolve_template_ref(ref: str) -> tuple[str | None, str | None]:
    """静态资产（template 承担者）的 ref 解析，返回 (error, warning)。

    只判「路径能落到文件」，不读内容、不判资产是否被使用。两种写法都认：
      - 仓内相对路径（如 `shared/tool-surface.json`）：必须存在，缺失判红。
      - finddata 工作区路径（如 `fd-erp-vertical-templates/templates/...`）：存在即过；
        不在场只记 warning 并注明「跨仓不可核」——单仓 CI 里兄弟仓不会被检出。
    不查团队/资产在兄弟仓里是否登记：那是 fleet-packs 侧团队覆盖闸的事（design D4）。
    """
    if not ref:
        return "缺 ref（template 必须指向仓内或工作区里的资产路径）", None
    parts = PurePosixPath(ref).parts
    if Path(ref).is_absolute() or ".." in parts:
        return f"ref={ref!r} 必须用相对路径（不得绝对路径或 ..）", None
    if ref.startswith("fd-erp/"):
        rel = ref[len("fd-erp/"):]
        if (FD_ERP / rel).exists():
            return None, None
        return f"仓内路径不存在 {ref}", None
    if (ROOT / ref).exists():
        return None, None
    head = parts[0] if parts else ""
    if head != "fd-erp" and (ROOT / head).is_dir():
        # 兄弟仓在 workspace 根下出现过，但这一个路径核不到：不能因跨仓缺席判红。
        return None, f"跨仓不可核：{ref} 未落到文件（兄弟仓可能不在场）"
    return f"仓内路径不存在 {ref}", None


def _check_owner(m: dict, state: str, problems: list[str], warnings: list[str]) -> None:
    """7) 承担者可指认：恰好一个 owner，且形态合法。

    分工：本闸只核形状与 none 的合法性；「团队在团队侧声明里存在吗」由 fleet-packs
    的团队覆盖闸读本矩阵后核（design D4），避免 fd-erp 的闸链依赖兄弟仓。
    """
    mid = m.get("id")
    owner = m.get("owner")
    if not isinstance(owner, dict):
        problems.append(
            f"[无承担者] {mid}: 缺 owner（每格必须恰好一个：fleet|template|none）")
        return
    kind = owner.get("kind")
    if kind not in OWNER_KINDS:
        problems.append(
            f"[承担者类型] {mid}: owner.kind={kind!r} 不在 " f"{sorted(OWNER_KINDS)} 内")
        return
    ref = (owner.get("ref") or "").strip()
    if kind == "fleet":
        if not KEBAB_CASE.match(ref):
            problems.append(
                f"[承担者格式] {mid}: fleet ref={ref!r} 应为 kebab-case 团队名")
        elif not ref.endswith("-fleet"):
            warnings.append(
                f"[承担者命名] {mid}: fleet ref={ref!r} 不以 -fleet 结尾（建议，不阻断）")
    elif kind == "template":
        error, warning = _resolve_template_ref(ref)
        if error:
            problems.append(f"[承担者悬空] {mid}: template {error}")
        if warning:
            warnings.append(f"[承担者悬空?] {mid}: {warning}")
    else:  # none
        if state not in OWNER_NONE_STATES:
            problems.append(
                f"[无主能力] {mid}: state={state} 却 owner.kind=none —— "
                "已具备的能力没有人执行＝纸上能力")
        if not (owner.get("reason") or "").strip():
            problems.append(f"[承担者原因] {mid}: kind=none 必须写非空 reason")


def _load(path: Path, label: str) -> dict:
    if not path.is_file():
        raise SystemExit(f"缺少{label}出处：{path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))


def _tool_names() -> set[str]:
    surface = _load(TOOL_SURFACE, "工具面")
    return set(surface["tool_annotations"])


def _api_sources() -> str:
    if not VERTICAL_API.is_dir():
        return ""
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in VERTICAL_API.rglob("*.py"))


def check() -> tuple[list[str], dict]:
    matrix = _load(MATRIX, "覆盖矩阵")
    claims = _load(CLAIMS, "能力宣称")
    tools = _tool_names()
    api_blob = _api_sources()

    problems: list[str] = []
    warnings: list[str] = []
    stats: dict[str, object] = {}

    module_set = matrix.get("module_set") or []
    modules = matrix.get("modules") or []

    # 1) 格子封闭
    ids = [m.get("id") for m in modules]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        problems.append(f"[重复格子] modules 里出现多次：{', '.join(dupes)}")
    missing = sorted(set(module_set) - set(ids))
    extra = sorted(set(ids) - set(module_set))
    if missing:
        problems.append(f"[缺格] module_set 声明但 modules 未登记：{', '.join(missing)}")
    if extra:
        problems.append(f"[越界格子] modules 有而 module_set 未声明（先扩充全集）：{', '.join(extra)}")

    claim_status = {c["id"]: c["status"] for c in claims.get("claims", [])}
    claim_by_id = {c["id"]: c for c in claims.get("claims", [])}

    for m in modules:
        mid = m.get("id")
        state = m.get("state")
        state_ok = state in VALID_STATES
        if not state_ok:
            problems.append(f"[状态越界] {mid}: state={state!r} 不在四态内")
        if not (m.get("boundary") or "").strip():
            problems.append(f"[缺边界说明] {mid}: 每格都必须写边界（能做什么、不做什么）")

        # 7) 承担者可指认（状态越界也照样核 owner：缺字段要一并点名）
        _check_owner(m, state, problems, warnings)
        if not state_ok:
            continue

        # 2) 证据可解析 + 无行号锚
        evidence = m.get("evidence") or []
        if state in {"delivered", "template_configured"} and not evidence:
            problems.append(f"[无证据] {mid}: {state} 必须给至少一条仓内可解析证据")
        for ev in evidence:
            kind, ref = ev.get("kind"), ev.get("ref") or ""
            if LINE_ANCHOR.search(ref):
                problems.append(f"[行号锚] {mid}: 证据 {ref!r} 用行号定位；改用符号/子串")
                continue
            if kind == "tool":
                if ref not in tools:
                    problems.append(f"[工具悬空] {mid}: 工具面里没有 {ref!r}")
            elif kind == "endpoint":
                match = re.match(r"^(GET|POST|PUT|PATCH|DELETE)\s+(\S+)$", ref.strip())
                if not match:
                    problems.append(f"[端点格式] {mid}: {ref!r} 应为 `METHOD /path`")
                elif not api_blob:
                    problems.append(f"[端点不可核] {mid}: 找不到 {VERTICAL_API.relative_to(ROOT)} 源码")
                else:
                    path = match.group(2)
                    # 路由模板用 {x} 占位，源码里也是同样的字面量
                    if path not in api_blob:
                        problems.append(f"[端点悬空] {mid}: 源码里没有路由 {path}")
            elif kind == "file":
                p = ROOT / ref
                if not p.is_file():
                    problems.append(f"[文件悬空] {mid}: 不存在 {ref}")
                elif ev.get("contains") and ev["contains"] not in p.read_text(
                        encoding="utf-8", errors="ignore"):
                    problems.append(
                        f"[内容缺失] {mid}: {ref} 里找不到 {ev['contains']!r}")
            else:
                problems.append(f"[证据类型] {mid}: 未知 kind={kind!r}")

        # 3) not_doing 三项留档
        if state == "not_doing":
            for field in ("reason", "decided_by", "review_by"):
                if not (m.get(field) or "").strip():
                    problems.append(f"[不做未留档] {mid}: not_doing 缺 {field}")

        # 5) needs_onboarding 说清缺什么
        if state == "needs_onboarding" and not (m.get("blocker") or "").strip():
            problems.append(f"[待接入无阻塞项] {mid}: needs_onboarding 必须写 blocker")

        # 4) 不做不得被宣称（引用的 claim 不得是「肯定式已交付」）
        for cid in m.get("claims") or []:
            if cid not in claim_status:
                problems.append(f"[claim 悬空] {mid}: claims.json 里没有 {cid!r}")
                continue
            if state == "not_doing":
                entry = claim_by_id[cid]
                # 两类合法：①本就不可宣称；②宣称内容是「我没做这件事」的边界句
                # （如「零资金执行面」——它断言的正是我们不做资金执行）。
                if entry["status"] == "delivered" and not _is_boundary_claim(entry):
                    problems.append(
                        f"[不做却被宣称] {mid}: not_doing 却引用 delivered 的肯定式 claim {cid!r}")

    # 6) 连接器事实不漂移：矩阵说「等 provider」时，连接器仓必须仍显缺口
    if CONNECTOR_STATUS.is_file():
        status = json.loads(CONNECTOR_STATUS.read_text(encoding="utf-8"))
        roles = (status.get("role_bindings") or {})
        for m in modules:
            blocker = (m.get("blocker") or "")
            match = re.search(r"provider[：:\s]*([a-z0-9_-]+)", blocker)
            if not match:
                continue
            role = match.group(1)
            candidates = (roles.get(role) or {}).get("candidates") or []
            if candidates:
                problems.append(
                    f"[缺口已解除] {m.get('id')}: 矩阵仍记「等 provider {role}」，"
                    f"但连接器仓候选集已非空（{len(candidates)} 个）；应重新定态")

    counts: dict[str, int] = {s: 0 for s in sorted(VALID_STATES)}
    for m in modules:
        if m.get("state") in counts:
            counts[m["state"]] += 1
    stats["cells"] = len(modules)
    stats["states"] = counts
    stats["claims_referenced"] = sum(len(m.get("claims") or []) for m in modules)
    stats["owner_kinds"] = {
        k: sum(1 for m in modules if (m.get("owner") or {}).get("kind") == k)
        for k in sorted(OWNER_KINDS)
    }
    stats["warnings"] = warnings
    return problems, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        problems, stats = check()
    except SystemExit as exc:
        print(f"无法执行：{exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"ok": not problems, "problems": problems,
                          "warnings": stats.get("warnings") or [], "stats": stats},
                         ensure_ascii=False, indent=2))
    else:
        print(f"矩阵 : {MATRIX.relative_to(ROOT)}")
        print(f"格子 : {stats['cells']}（" + " / ".join(
            f"{k}={v}" for k, v in stats["states"].items()) + "）")
        print("承担 : " + " / ".join(
            f"{k}={v}" for k, v in stats["owner_kinds"].items()))
        print(f"claim: 引用 {stats['claims_referenced']} 条")
        print("-" * 60)
        if problems:
            print(f"✗ FAIL — {len(problems)} 项不通过：")
            for p in problems:
                print(f"  - {p}")
        else:
            print("✓ PASS — 格子封闭、证据可解析、不做已留档、每格有承担者、口径无矛盾")
        for w in stats.get("warnings") or []:
            print(f"  ! WARN {w}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
