#!/usr/bin/env python3
"""内核工具面 × 客户端覆盖面 的契约闸（跨仓，只读）。

背景：`tool-surface.json` 是内核工具面的单一出处，但没有人回答"每条消费仓盖了多少、
漏掉的是故意不盖还是忘了盖"。结果是签名靠人肉对齐、缺口靠 grep 猜。

本闸把"故意不盖"变成声明：
  1. 每个消费仓声明的必须覆盖集合，必须与客户端实际方法集合逐名相等；
  2. 未覆盖的工具必须逐条在 `intentionally_absent` 里给出理由 —— 说不出理由就是缺口；
  3. 客户端里不得出现工具面之外的发明方法；
  4. 声明了 `transport` 块的消费仓，其**传输适配器**（如 `McpKernelClient`）必须与
     工具面**逐名全等** —— 缺一个转发就是那一档能力在生产断链（2026-11-15
     `decide_event` 生产 500 的订正：api 的 MCP 内层复用的就是模板仓传输类，
     而原先把传输类混进编排面比对，两个方向都会错）。
  5. **参数名**（2026-11-15 补）：只判方法名会漏掉今天大半事故。三个方向各一档：
     - `TRANSPORT_PARAM_MISSING`：内核工具收、传输类不收 ⇒ 该能力经 MCP 不可达；
     - `TRANSPORT_PARAM_SWALLOWED`：传输类收了但不装进 payload ⇒ 静默不生效；
     - `TRANSPORT_PARAM_EXTRA`：传输类收/发内核没有的参数 ⇒ MCP 形态 TypeError；
     - `CALLSITE_UNKNOWN_KWARG`：消费仓在**内核客户端接收者**上调用工具时传了内核
       没有的关键字 ⇒ 同样是 TypeError，但代码不在客户端类里，前面三档都看不见。

     三档的例外全部声明在 `transport.param_policy`（`tenant_id` 构造时绑定、
     `*_by` 由内核默认值填）。**没有声明就是缺陷**——这条纪律与 `intentionally_absent`
     一致：说不出理由的缺口一律红。

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


def kernel_tool_params() -> dict[str, dict]:
    """内核工具面的**参数表**（真源仍是 tools.py 的 `@mcp.tool` 定义）。

    返回 {工具名: {"params": [...], "payload": {...} or None}}，另外把
    「必填参数」也带出来（无默认值的），因为缺必填参数与缺可选参数不是一回事。
    """
    p = ROOT / "fd-erp-ledger-mcp" / "fd_erp_ledger_mcp" / "tools.py"
    if not p.is_file():
        raise SystemExit(f"缺少内核工具面实现：{p.relative_to(ROOT)}")
    src = p.read_text(encoding="utf-8")
    tree = ast.parse(src)
    out: dict[str, dict] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(ast.unparse(d).startswith("mcp.tool") for d in node.decorator_list):
            continue
        args = node.args
        positional = list(args.args)
        n_default = len(args.defaults)
        required = {a.arg for a in positional[:len(positional) - n_default]}
        names = [a.arg for a in positional] + [a.arg for a in args.kwonlyargs]
        out[node.name] = {"params": names, "required": required}
    return out


def transport_method_params(rel_path: str, classes: list[str]) -> dict[str, dict]:
    """传输类每个方法的**接受参数**与**实际装进 payload 的键**。

    `_call("tool", {...})` 的第二个实参是 payload 字典 —— 只认字面量键，
    这样「接受但不转发」与「接受且转发」能分开（前者是静默不生效）。
    """
    p = ROOT / rel_path
    if not p.is_file():
        raise SystemExit(f"缺少客户端文件：{rel_path}")
    tree = ast.parse(p.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in classes:
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name.startswith("_") or item.name == "__init__":
                continue
            params = ([a.arg for a in item.args.args][1:]
                      + [a.arg for a in item.args.kwonlyargs])
            payload: set[str] = set()
            for sub in ast.walk(item):
                if not isinstance(sub, ast.Call):
                    continue
                fn = sub.func
                if getattr(fn, "attr", None) != "_call" and getattr(fn, "id", None) != "_call":
                    continue
                for arg in sub.args[1:2]:
                    if isinstance(arg, ast.Dict):
                        payload |= {k.value for k in arg.keys
                                    if isinstance(k, ast.Constant)}
                for kw in sub.keywords:
                    if isinstance(kw.value, ast.Dict):
                        payload |= {k.value for k in kw.value.keys
                                    if isinstance(k, ast.Constant)}
            out[item.name] = {"params": params, "payload": payload}
    return out


def _policy_key(policy: dict, tool: str, param: str) -> str | None:
    """取声明：先查 `工具.参数`，再查 `*:参数`，最后查裸参数名（全局）。"""
    for key in (f"{tool}.{param}", f"*.{param}", param):
        if key in policy:
            return key
    return None


def callsite_unknown_kwargs(scan: dict, kernel: dict[str, dict]) -> list[dict]:
    """扫消费仓调用点：在内核客户端接收者上调用工具时传了内核没有的关键字。

    只认**接收者白名单**（`_kernel`/`kernel`/`_client`…）。不按方法名全仓扫是必要的：
    `proposals.submit_proposal(conn, settings=…)` 这种模块级同名函数会把
    `settings=` 报成越界关键字，一条假红就够让闸被无视。
    """
    receivers = set(scan.get("receivers") or [])
    allow = scan.get("allow") or {}
    hits: list[dict] = []
    for root in scan.get("roots") or []:
        base = ROOT / root
        if not base.exists():
            hits.append({"code": "CALLSITE_ROOT_MISSING", "repo": root,
                         "message": f"调用点扫描根不存在：{root}"})
            continue
        for py in sorted(base.rglob("*.py")):
            rel = str(py.relative_to(ROOT))
            if "/tests/" in rel or py.name.startswith("test_") or "/build/" in rel:
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                hits.append({"code": "CALLSITE_PARSE_ERROR", "repo": rel,
                             "message": f"解析失败：{exc}"})
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                if not isinstance(fn, ast.Attribute) or fn.attr not in kernel:
                    continue
                recv = fn.value
                name = (recv.attr if isinstance(recv, ast.Attribute)
                        else getattr(recv, "id", None))
                if name not in receivers:
                    continue
                passed = {k.arg for k in node.keywords if k.arg}
                unknown = passed - set(kernel[fn.attr]["params"])
                for param in sorted(unknown):
                    # 调用点只认 `工具.参数` 精确声明：接收者不是传输类本身，
                    # 全局豁免（裸参数名 / `*.参数`）会把真断链一起放走。
                    if f"{fn.attr}.{param}" in allow:
                        continue
                    hits.append({
                        "code": "CALLSITE_UNKNOWN_KWARG", "repo": rel,
                        "message": (f"{rel}:{node.lineno} {name}.{fn.attr}() "
                                    f"传了内核工具面没有的关键字 {param!r}"
                                    f" ⇒ MCP 形态 TypeError（同进程形态看不出来）"),
                    })
    return hits


def check() -> dict:
    tools = surface_tools()
    tool_set = set(tools)
    kernel = kernel_tool_params()
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

        # ④ 传输面：1:1 覆盖工具面（声明了 transport 块才判）
        transport_spec = consumer.get("transport") or {}
        transport_actual: set[str] = set()
        transport_classes = transport_spec.get("classes") or []
        if transport_classes:
            for cls, names in client_methods(consumer["client"],
                                             transport_classes).items():
                if not names:
                    violations.append({
                        "code": "CLIENT_CLASS_EMPTY", "repo": repo,
                        "message": (f"传输类 {cls} 未找到任何公开方法"
                                    f"（类名改了？路径：{consumer['client']}）"),
                    })
                transport_actual |= names
            if transport_actual != tool_set:
                violations.append({
                    "code": "TRANSPORT_COVERAGE", "repo": repo,
                    "message": (f"传输面与工具面不一致："
                                f"缺少 {sorted(tool_set - transport_actual)} "
                                f"多出 {sorted(transport_actual - tool_set)}"
                                f"（传输类 {transport_classes}；缺一个转发 = "
                                f"复用它作 MCP 内层的消费仓那一端点在生产断链）"),
                })

        # ⑤ 故意不覆盖的每一条必须有理由
        for name in sorted(declared_absent):
            reason = (consumer["intentionally_absent"][name] or "").strip()
            if len(reason) < 6:
                violations.append({
                    "code": "ABSENT_WITHOUT_REASON", "repo": repo,
                    "message": f"{name} 标为故意不覆盖但没给出可读理由",
                })

        # ⑥ 参数名：传输类的接受参数 ↔ 内核工具签名（只判传输面，声明例外）
        param_policy = transport_spec.get("param_policy") or {}
        not_accepted = param_policy.get("not_accepted") or {}
        if transport_classes:
            tparams = transport_method_params(consumer["client"], transport_classes)
            for tool in sorted(transport_actual & tool_set):
                spec = tparams.get(tool)
                if spec is None:
                    continue  # 缺方法已由 TRANSPORT_COVERAGE 报过
                accepted = set(spec["params"])
                payload = spec["payload"]
                kparams = kernel[tool]
                for param in kparams["params"]:
                    if param in accepted:
                        # 收了必须真发：接受但不装进 payload = 静默不生效
                        if param not in payload:
                            if _policy_key(not_accepted, tool, param):
                                continue
                            violations.append({
                                "code": "TRANSPORT_PARAM_SWALLOWED", "repo": repo,
                                "message": (f"{tool}.{param}：传输类接受但没装进 payload"
                                            f" ⇒ 调用方传了也不生效（静默）"),
                            })
                        continue
                    if _policy_key(not_accepted, tool, param):
                        continue
                    if param in kparams["required"]:
                        violations.append({
                            "code": "TRANSPORT_PARAM_MISSING", "repo": repo,
                            "message": (f"{tool}.{param}：内核**必填**而传输类不收"
                                        f" ⇒ 该能力经 MCP 不可达"),
                        })
                    else:
                        violations.append({
                            "code": "TRANSPORT_PARAM_MISSING", "repo": repo,
                            "message": (f"{tool}.{param}：内核可选而传输类不收"
                                        f" ⇒ 调用方传它必 TypeError（2026-11-15 "
                                        f"booked_on/provenance 同族）"),
                        })
                for param in spec["params"]:
                    if param in kparams["params"]:
                        continue
                    if _policy_key(not_accepted, tool, param):
                        continue
                    violations.append({
                        "code": "TRANSPORT_PARAM_EXTRA", "repo": repo,
                        "message": (f"{tool}.{param}：传输类收/发内核工具面没有的参数"
                                    f" ⇒ MCP 形态 pydantic 判非法（unexpected_keyword）"),
                    })
            for key, reason in not_accepted.items():
                if len((reason or "").strip()) < 6:
                    violations.append({
                        "code": "PARAM_POLICY_NO_REASON", "repo": repo,
                        "message": f"参数例外 {key} 没给出可读理由",
                    })
                bare = key.split(".", 1)[-1] if "." in key else key
                if bare not in {p for t in transport_actual & tool_set
                                for p in kernel[t]["params"]}:
                    violations.append({
                        "code": "PARAM_POLICY_STALE", "repo": repo,
                        "message": (f"参数例外 {key} 指向内核工具面里不存在的参数"
                                    f" —— 声明过期，删掉它（别留着给下一次漂移当"
                                    f"豁免）"),
                    })

        rows.append({
            "repo": repo,
            "covered": len(actual & tool_set),
            "absent": len(declared_absent),
            "surface": len(tool_set),
            "transport": len(transport_actual & tool_set) if transport_classes else None,
        })

    # ⑦ 调用点：内核客户端接收者上传了内核没有的关键字（跨仓，只扫一次）
    scan = ((contract.get("transport_param_scan")) or {})
    if scan:
        violations.extend(callsite_unknown_kwargs(scan, kernel))

    return {"ok": not violations, "violations": violations, "rows": rows,
            "surface": len(tool_set), "kernel_params": len(kernel)}


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
        extra = (f"  传输面 {r['transport']}/{r['surface']}"
                 if r.get("transport") is not None else "")
        print(f"  {r['repo']:<32} 覆盖 {r['covered']:>2}/{r['surface']}  "
              f"声明不覆盖 {r['absent']:>2}{extra}")
    if result["ok"]:
        print("契约闸：通过（声明 = 实际，未覆盖项均有理由）")
        return 0
    print(f"契约闸：阻断（{len(result['violations'])} 处）")
    for v in result["violations"]:
        print(f"  x [{v['code']}] {v.get('repo','')} {v['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
