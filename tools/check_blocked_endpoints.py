#!/usr/bin/env python3
"""如实 501 端点的**阻塞归属**对拍闸（change: track-blocked-endpoints-by-dependency）。

为什么要有这道闸：11 条 501 此前只有散文理由（`planned_lane`），没人能回答「哪个外部依赖解除
了会点亮哪几条端点」，也没人会发现「依赖早就到位、端点还挂在 501」。散文没人核对，等于没有。

三条判据，任一不满足即判红：

  1. 覆盖     —— 代码里每个 501 端点恰好属于一个接入包（新增 501 必须报出它卡在什么上）；
  2. 不陈旧   —— 包里的端点必须仍是 501（已实现的端点留在包里＝映射骗人）；
  3. 依赖一致 —— 包的判据（连接器 provider 状态 / 内核工具名）**已解除**而端点仍是 501 → 红。
                 这是把 erp-board-coverage 那条「跨仓事实已解除而本仓仍记缺口必须判红」落到端点粒度。

判据必须是机器可读的外部事实，不接受散文：
  · connector-provider → 读 `fd-erp-vertical-templates/connector-status.json` 的 state
  · tool-in-surface    → 读 `fd-erp-ledger-mcp/tool-surface.json` 的工具名清单

兄弟仓不在场时 SKIP（退出 2），不假绿。

用法：
    python3 tools/check_blocked_endpoints.py
    python3 tools/check_blocked_endpoints.py --connector-status /tmp/fake.json   # 造红用
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MAP_PATH = ROOT / "fd-erp" / "shared" / "blocked-endpoints.json"
API_DIR = ROOT / "fd-erp-vertical-api"
API_PKG_DIR = API_DIR / "fd_erp_vertical_api"
PLANNED_SURFACES = API_DIR / "scripts" / "planned_surfaces.py"
CONNECTOR_STATUS = ROOT / "fd-erp-vertical-templates" / "connector-status.json"
TOOL_SURFACE = ROOT / "fd-erp-ledger-mcp" / "tool-surface.json"

PLACEHOLDER_RE = re.compile(r"\{[^}]+\}")


def norm(path: str) -> str:
    """占位符规范化：代码用 `{statement_id}`、映射用 `{statementId}`，同一条路由。"""
    return PLACEHOLDER_RE.sub("{}", str(path).strip())


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def live_501(api_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """从 API 仓源码派生当前 501 端点集合（复用 planned_surfaces 的 AST 派生，不写第二套）。"""
    script = api_dir / "scripts" / "planned_surfaces.py"
    if not script.is_file():
        raise SystemExit(f"SKIP: 找不到 {script}（无法派生 501 集合）")
    spec = importlib.util.spec_from_file_location("_planned_surfaces", script)
    if spec is None or spec.loader is None:
        raise SystemExit(f"SKIP: 无法加载 {script}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    derived = mod.derive(api_dir.resolve())
    return {(e["method"].upper(), norm(e["path"])): e for e in derived.get("endpoints") or []}


def implemented(api_dir: Path) -> set[tuple[str, str]]:
    """全部实现端点（含 501）——用来判「包里的端点是不是早已不再 501」。"""
    return set(live_501(api_dir))


def connector_states(path: Path) -> dict[str, str]:
    """provider → state。同一 provider 多条时取最「打通」的一条（connected 优先）。"""
    data = load_json(path)
    out: dict[str, str] = {}
    for item in data.get("integrations") or []:
        provider = str(item.get("provider") or "").strip()
        if not provider:
            continue
        state = str(item.get("state") or "").strip()
        if out.get(provider) != "connected":
            out[provider] = state
    return out


def tool_names(path: Path) -> set[str]:
    """内核工具面里的工具名。tool-surface.json 的形状是 {tool_annotations: {name: {...}}}。"""
    data = load_json(path)
    names: set[str] = set()
    if isinstance(data.get("tool_annotations"), dict):
        names |= set(data["tool_annotations"].keys())
    for key in ("tools", "surface", "tools_surface"):
        val = data.get(key)
        if isinstance(val, list):
            for t in val:
                if isinstance(t, str):
                    names.add(t)
                elif isinstance(t, dict) and t.get("name"):
                    names.add(str(t["name"]))
    return names


def check(mapping: dict[str, Any], live: dict[tuple[str, str], dict[str, Any]],
          connectors: dict[str, str], tools: set[str]) -> tuple[list[str], list[str]]:
    """返回 (问题, 包状态摘要)。"""
    problems: list[str] = []
    summary: list[str] = []
    claimed: dict[tuple[str, str], str] = {}

    packages = mapping.get("packages") or []
    if not packages:
        problems.append("[映射为空] blocked-endpoints.json 里没有任何接入包——"
                        "11 条 501 会因此无人归属")

    for pkg in packages:
        pid = str(pkg.get("id") or "").strip()
        crit = pkg.get("criterion") or {}
        kind = str(crit.get("kind") or "").strip()
        subject = str(crit.get("subject") or "").strip()
        if not pid:
            problems.append("[包无 id] 每个接入包都必须有稳定 id（判据与端点靠它关联）")
            continue
        if not str(crit.get("note") or "").strip():
            problems.append(f"[{pid}] criterion.note 为空——解除后点亮什么必须写清，"
                            f"否则下一个人不知道这个包值不值得推")
        if kind == "connector-provider":
            state = connectors.get(subject)
            if state is None:
                # provider 都不存在：这就是缺口本身，不算漂移（收银台例子：file-service）
                summary.append(f"{pid}: 阻塞（连接器无 {subject} provider）")
                cleared = False
            else:
                cleared = state == "connected"
                # 「provider 未落地」（上面那支）= 真阻塞；「落地但 live 未验收」= 可实施
                # （catalog+执行器测试已到位，剩余是 live 验收车道，不是没人开工）。
                if cleared:
                    summary.append(f"{pid}: 依赖已解除（{subject}={state}）")
                else:
                    summary.append(f"{pid}: 可实施（{subject} 已落地，live 待验收；"
                                   f"state={state}）")
        elif kind == "tool-in-surface":
            cleared = subject in tools
            summary.append(f"{pid}: {'依赖已解除' if cleared else '阻塞'}"
                           f"（工具 {subject} {'在' if cleared else '不在'}工具面）")
        else:
            problems.append(f"[{pid}] criterion.kind 非法：{kind!r}"
                            f"（只接受 connector-provider / tool-in-surface）")
            cleared = False

        eps = pkg.get("endpoints") or []
        if not eps:
            problems.append(f"[{pid}] 包内没有端点——空包要么删掉，要么补上它卡住的那几条")
        for ep in eps:
            key = (str(ep.get("method") or "").upper(), norm(ep.get("path") or ""))
            if key in claimed:
                problems.append(f"[重复归属] {key[0]} {key[1]} 同时属于 {claimed[key]} 与 {pid}"
                                f"——每条 501 只能卡在一个依赖上")
                continue
            claimed[key] = pid
            if key not in live:
                problems.append(f"[包陈旧] {pid} 的 {key[0]} {key[1]} 已不是 501"
                                f"（或路由已不存在）——把它从包里移出，或说明为何它仍不可用")
                continue
            if cleared:
                lane = (live[key].get("planned_lane") or "")[:60]
                problems.append(
                    f"[依赖已解除仍 501] {pid}：{subject} 已到位，但 {key[0]} {key[1]} 还是 501"
                    f"（planned_lane={lane}…）——去实现它；若判断仍不可行，把判据改成真实阻塞"
                    f"（不能靠留着旧判据继续挂 501）")

    # 覆盖：每个 501 都必须有归属
    for key in sorted(live):
        if key not in claimed:
            ep = live[key]
            problems.append(
                f"[未归属] {key[0]} {key[1]}（{ep.get('capability')}，"
                f"{ep.get('source')}）是 501 但不在任何接入包里——"
                f"把它归到对应依赖包（或新建一个包并写清判据）")

    return problems, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="501 端点的阻塞归属对拍")
    ap.add_argument("--map", default=str(MAP_PATH), help="接入包映射（默认 fd-erp/shared/blocked-endpoints.json）")
    ap.add_argument("--api-dir", default=str(API_DIR), help="fd-erp-vertical-api 仓目录")
    ap.add_argument("--connector-status", default=str(CONNECTOR_STATUS),
                    help="connector-status.json（造红时指向替身）")
    ap.add_argument("--tool-surface", default=str(TOOL_SURFACE), help="内核 tool-surface.json")
    args = ap.parse_args(argv)

    need = [Path(args.map), Path(args.api_dir), Path(args.connector_status),
            Path(args.tool_surface)]
    missing = [str(p) for p in need if not p.exists()]
    if missing:
        print(f"SKIP: 输入不在场，无法对拍（缺 {', '.join(missing)}）")
        return 2

    live = live_501(Path(args.api_dir))
    mapping = load_json(Path(args.map))
    connectors = connector_states(Path(args.connector_status))
    tools = tool_names(Path(args.tool_surface))

    problems, summary = check(mapping, live, connectors, tools)
    for line in summary:
        print(f"  · {line}")
    if problems:
        print(f"FAIL: 501 阻塞归属不一致（{len(problems)} 处）：")
        for p in problems:
            print("  " + p)
        return 1
    print(f"OK: {len(live)} 条 501 端点全部有归属，{len(mapping.get('packages') or [])} 个接入包的"
          f"判据均未解除（无一「依赖已解除仍 501」）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
