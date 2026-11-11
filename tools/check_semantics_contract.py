#!/usr/bin/env python3
"""ERP 跨仓语义契约闸：错误码 + 指标名（只读，AST 现读，不 import 任何仓）。

为什么不 import：三仓 CI 互相看不见，但本闸跑在 ERP 维护根上，AST 读取既无依赖也
不触发 fastmcp / psycopg 的安装需求。

检查项（对应 shared/semantics-contract.json）：
  1. 内核 CATALOG 的码名 == tool-surface.json 的 error_codes.codes（双向）；
  2. 跨仓共享码在内核与 api 两侧 semantic_class / retryable / default_hint 逐字一致；
  3. 模板层码集 ⊆ 内核码 ∪ api 自有码 ∪ 模板自有码（不得凭空造码，也不得声明不存在的）；
  4. 指标名符合命名式，且不跨服务重名；
  5. histogram 桶集不一致必须已声明（未声明的差异判红）。

用法：
  python3 fd-erp/tools/check_semantics_contract.py [--json]
退出码：0 一致 / 1 有违规 / 2 出处缺失
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "fd-erp" / "shared" / "semantics-contract.json"


# ── AST 读取 ──────────────────────────────────────────────────────────────────
def _read(rel: str) -> ast.Module:
    p = ROOT / rel
    if not p.is_file():
        raise SystemExit(f"缺少出处文件：{rel}")
    return ast.parse(p.read_text(encoding="utf-8"))


def _dict_of_calls(tree: ast.Module, var: str) -> dict[str, list]:
    """取 `VAR: dict[str, X] = {"CODE": X(...), ...}` 的码名 → 位置参数列表。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            if not (isinstance(node.target, ast.Name) and node.target.id == var):
                continue
            value = node.value
        elif isinstance(node, ast.Assign):
            if not any(isinstance(t, ast.Name) and t.id == var for t in node.targets):
                continue
            value = node.value
        else:
            continue
        if not isinstance(value, ast.Dict):
            continue
        out: dict[str, list] = {}
        for k, v in zip(value.keys, value.values):
            if not isinstance(k, ast.Constant):
                continue
            args = [a.value for a in getattr(v, "args", []) if isinstance(a, ast.Constant)]
            out[k.value] = args
        return out
    raise SystemExit(f"未在源码中找到 {var}")


def _tuple_class_attr(rel: str, cls: str, attr: str) -> list[str]:
    tree = _read(rel)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for item in node.body:
                if isinstance(item, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == attr for t in item.targets):
                    if isinstance(item.value, (ast.Tuple, ast.List)):
                        return [e.value for e in item.value.elts if isinstance(e, ast.Constant)]
    raise SystemExit(f"未在 {rel} 的 {cls}.{attr} 找到码元组")


def _metrics(rel: str) -> list[dict]:
    tree = _read(rel)
    out = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            target = node.targets[0]
            call = node.value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            call = node.value
        else:
            continue
        if not (isinstance(target, ast.Name) and isinstance(call, ast.Call)):
            continue
        kind = getattr(call.func, "id", None)
        if kind not in ("Counter", "Histogram", "Gauge", "Summary"):
            continue
        name = call.args[0].value if call.args and isinstance(call.args[0], ast.Constant) else None
        buckets = None
        for kw in call.keywords:
            if kw.arg == "buckets" and isinstance(kw.value, (ast.List, ast.Tuple)):
                buckets = [e.value for e in kw.value.elts if isinstance(e, ast.Constant)]
        out.append({"var": target.id, "kind": kind, "name": name, "buckets": buckets})
    return out


# ── 检查 ──────────────────────────────────────────────────────────────────────
def check() -> dict:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    violations: list[dict] = []
    summary: dict = {}

    # ① 错误码：内核 CATALOG × tool-surface 镜像
    ec = contract["error_codes"]["sources"]
    kernel = _dict_of_calls(_read(ec["kernel_catalog"]), "CATALOG")
    mirror_tree = _read(ec["kernel_mirror"])
    mirror = _read_surface_codes(ec["kernel_mirror"])

    only_kernel = sorted(set(kernel) - set(mirror))
    only_mirror = sorted(set(mirror) - set(kernel))
    if only_kernel or only_mirror:
        violations.append({
            "code": "MIRROR_DRIFT",
            "message": (f"内核 CATALOG 与 tool-surface 镜像不一致："
                        f"仅内核 {only_kernel} / 仅镜像 {only_mirror}"),
        })
    summary["kernel_codes"] = len(kernel)
    summary["mirror_codes"] = len(mirror)

    # ② 共享码语义一致（内核 vs api）
    api = _dict_of_calls(_read(ec["api_catalog"]), "ERROR_CATALOG")
    shared = sorted(set(kernel) & set(api))
    for name in shared:
        k, a = kernel[name], api[name]
        # ErrorCode(code, semantic_class, retryable, hint)
        # ErrorCodeMeta(code, semantic_class, retryable, hint, http_status)
        fields = ("semantic_class", "retryable", "default_hint")
        for idx, field in ((1, fields[0]), (2, fields[1]), (3, fields[2])):
            kv = k[idx] if len(k) > idx else None
            av = a[idx] if len(a) > idx else None
            if kv != av:
                violations.append({
                    "code": "SHARED_SEMANTIC_DRIFT",
                    "message": (f"共享码 {name} 的 {field} 两侧不一致："
                                f"内核 {kv!r} vs api {av!r}"),
                })
    summary["shared_codes"] = len(shared)
    summary["api_codes"] = len(api)

    # ③ 仓自有码必须声明：新增一个码而不登记 → 判红（防止封闭集被静默扩张）
    declared_specific: dict[str, dict[str, str]] = (
        contract["error_codes"].get("service_specific_codes") or {}
    )
    tpl = _tuple_class_attr(ec["templates_codes"], "TemplateError", "CODES")
    owners = {
        "fd-erp-vertical-templates": set(tpl) - set(kernel) - set(api),
        "fd-erp-vertical-api": set(api) - set(kernel),
    }
    for svc, own in owners.items():
        declared = set(declared_specific.get(svc) or {})
        undeclared = sorted(own - declared)
        stale = sorted(declared - own)
        if undeclared:
            violations.append({
                "code": "SERVICE_CODE_UNDECLARED",
                "message": (f"{svc} 出现未声明的自有错误码：{undeclared}"
                            f"——要么登记进 semantics-contract.json 并给理由，要么复用语内核码"),
            })
        if stale:
            violations.append({
                "code": "SERVICE_CODE_STALE_DECLARATION",
                "message": f"{svc} 声明的自有码已不在源码中：{stale}",
            })
        for name in sorted(declared & own):
            reason = (declared_specific[svc][name] or "").strip()
            if len(reason) < 6:
                violations.append({
                    "code": "SERVICE_CODE_WITHOUT_REASON",
                    "message": f"{svc} 的自有码 {name} 没有可读理由",
                })
    # 模板层复用的内核码，必须能与内核语义对上（不能借用同名但含义不同）
    for name in sorted(set(tpl) & set(kernel)):
        if len(kernel[name]) < 3:
            violations.append({
                "code": "TEMPLATE_SHARED_SEMANTICS_MISSING",
                "message": f"模板层复用了内核码 {name}，但内核侧语义字段不全",
            })
    summary["templates_codes"] = len(tpl)

    # ④ 指标：命名式 + 跨服务不重名
    mc = contract["metrics"]
    pattern = re.compile(mc["rules"]["name_pattern"])
    per_service = {
        "fd-erp-ledger-mcp": _metrics(mc["sources"]["kernel"]),
        "fd-erp-vertical-api": _metrics(mc["sources"]["api"]),
    }
    seen: dict[str, str] = {}
    for svc, items in per_service.items():
        for m in items:
            name = m["name"] or ""
            if not pattern.match(name):
                violations.append({
                    "code": "METRIC_NAME_INVALID",
                    "message": f"{svc} 的指标名 {name!r} 不符合命名式 {pattern.pattern}",
                })
            if name in seen:
                violations.append({
                    "code": "METRIC_DUPLICATE",
                    "message": f"指标名 {name} 同时出现在 {seen[name]} 与 {svc}（同一 Prometheus 会冲突）",
                })
            seen[name] = svc
    summary["metrics"] = {svc: len(v) for svc, v in per_service.items()}

    # ⑤ histogram 桶集：以内核为基准，偏离基准的服务必须已在 declared_deviations 里声明
    declared = {d["service"] for d in mc.get("declared_deviations", [])
                if d.get("kind") == "histogram_buckets"}
    reference_service = "fd-erp-ledger-mcp"
    ref_sets = {tuple(m["buckets"]) for m in per_service[reference_service]
                if m["kind"] == "Histogram" and m["buckets"]}
    if len(ref_sets) > 1:
        violations.append({
            "code": "HISTOGRAM_BUCKETS_INCONSISTENT_WITHIN_SERVICE",
            "message": f"{reference_service} 内部多个 histogram 桶集不一致，无法作为基准",
        })
    elif ref_sets:
        ref = next(iter(ref_sets))
        for svc, items in per_service.items():
            if svc == reference_service:
                continue
            sets = {tuple(m["buckets"]) for m in items
                    if m["kind"] == "Histogram" and m["buckets"]}
            if sets and sets != {ref} and svc not in declared:
                violations.append({
                    "code": "HISTOGRAM_BUCKETS_UNDECLARED",
                    "message": (f"{svc} 的 histogram 桶集与基准 {reference_service} 不一致，"
                                f"且未在 declared_deviations 里声明"),
                })

    return {
        "ok": not violations,
        "violations": violations,
        "summary": summary,
        "declared_deviations": mc.get("declared_deviations", []),
    }


def _read_surface_codes(rel: str) -> list[str]:
    p = ROOT / rel
    data = json.loads(p.read_text(encoding="utf-8"))
    codes = (data.get("error_codes") or {}).get("codes")
    if not isinstance(codes, list):
        raise SystemExit(f"{rel} 里没有 error_codes.codes")
    return sorted(codes)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = check()

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r["ok"] else 1

    s = r["summary"]
    print(f"错误码：内核 {s['kernel_codes']} / 镜像 {s['mirror_codes']} / 共享 {s['shared_codes']} "
          f"/ api {s['api_codes']} / 模板 {s['templates_codes']}")
    print(f"指标：内核 {s['metrics']['fd-erp-ledger-mcp']} 个 / "
          f"api {s['metrics']['fd-erp-vertical-api']} 个")
    for d in r["declared_deviations"]:
        print(f"  已声明偏差 [{d['kind']}] {d['service']}：{d['detail']}（待办 {d.get('task','-')}）")
    if r["ok"]:
        print("语义契约闸：通过")
        return 0
    print(f"语义契约闸：阻断（{len(r['violations'])} 处）")
    for v in r["violations"]:
        print(f"  x [{v['code']}] {v['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
