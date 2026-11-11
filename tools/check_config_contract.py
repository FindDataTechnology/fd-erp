#!/usr/bin/env python3
"""ERP 跨仓环境变量契约闸（只读，AST 现读）。

检查项（对应 shared/config-contract.json）：
  1. 变量名符合 ERP_ 命名式；
  2. 出现在两个以上仓的同名变量必须已在 shared 登记（偶然撞名不算契约）；
  3. 共享变量的默认值必须逐字一致（同名不同默认值 = 同一份清单两种行为）；
  4. 含凭据的 Settings 字段必须 field(repr=False)（日志层打码不覆盖异常栈/pprint/REPL）。

用法：python3 fd-erp/tools/check_config_contract.py [--json]
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
CONTRACT = ROOT / "fd-erp" / "shared" / "config-contract.json"

CONFIGS = {
    "fd-erp-ledger-mcp": "fd-erp-ledger-mcp/fd_erp_ledger_mcp/config.py",
    "fd-erp-vertical-api": "fd-erp-vertical-api/fd_erp_vertical_api/config.py",
    "fd-erp-vertical-templates": "fd-erp-vertical-templates/fd_erp_vertical_templates",
}


def _parse(rel: str) -> ast.Module:
    """单文件，或目录（模板层没有独立 config.py：环境变量散布在多个模块）。

    目录形态把每个 .py 的顶层调用都并进同一棵"合成"树：只需 env_defaults 看到的
    调用节点，不需要忠实还原模块边界。
    """
    p = ROOT / rel
    if not p.exists():
        raise SystemExit(f"缺少出处：{rel}")
    if p.is_dir():
        merged = ast.Module(body=[], type_ignores=[])
        for f in sorted(p.rglob("*.py")):
            if "__pycache__" in f.parts or f.name.startswith("test_"):
                continue
            merged.body.extend(ast.parse(f.read_text(encoding="utf-8")).body)
        return merged
    return ast.parse(p.read_text(encoding="utf-8"))


def env_defaults(tree: ast.Module) -> dict[str, str | None]:
    """取 变量→默认值，覆盖两种读取形态：

      _env("VAR", default) / _int_env("VAR", 90)      —— 本仓 config.py 的封装
      os.environ.get("VAR", "7")                      —— 模板层直接读

    只认 ERP_ / FD_ 前缀，避免把 PATH 之类的通用变量算进来。
    """
    out: dict[str, str | None] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if fn not in ("_env", "_int_env", "getenv", "get"):
            continue
        # os.environ.get(...) 的 attr 也是 "get"，靠 func.value 是否 environ 区分
        if fn == "get":
            base = node.func.value
            if not (isinstance(base, ast.Attribute) and base.attr == "environ"):
                continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        name = node.args[0].value
        if not isinstance(name, str) or not name.startswith(("ERP_", "FD_")):
            continue
        default = None
        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
            default = str(node.args[1].value)
        else:
            for kw in node.keywords:
                if kw.arg == "default" and isinstance(kw.value, ast.Constant):
                    default = str(kw.value.value)
        if name not in out or (out[name] is None and default is not None):
            out[name] = default
    return out


def settings_fields(tree: ast.Module) -> dict[str, bool]:
    """取 Settings 类的字段 → 是否 field(repr=False)。"""
    out: dict[str, bool] = {}
    for node in tree.body:
        if not (isinstance(node, ast.ClassDef) and node.name.endswith("Settings")):
            continue
        for item in node.body:
            name = None
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                name = item.target.id
                value = item.value
            elif isinstance(item, ast.Assign) and isinstance(item.targets[0], ast.Name):
                name = item.targets[0].id
                value = item.value
            if not name or name.startswith("_") or name == "extra":
                continue
            protected = False
            if isinstance(value, ast.Call) and getattr(value.func, "id", None) == "field":
                for kw in value.keywords:
                    if kw.arg == "repr" and isinstance(kw.value, ast.Constant):
                        protected = value
                        protected = kw.value.value is False
            out[name] = protected
    return out


def check() -> dict:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    pattern = re.compile(contract["naming"]["pattern"])
    violations: list[dict] = []
    per_repo: dict[str, dict[str, str | None]] = {}
    fields: dict[str, dict[str, bool]] = {}

    for repo, rel in CONFIGS.items():
        tree = _parse(rel)
        per_repo[repo] = env_defaults(tree)
        fields[repo] = settings_fields(tree)

    # ① 命名式
    for repo, vars_ in per_repo.items():
        for name in vars_:
            if not pattern.match(name):
                violations.append({
                    "code": "ENV_NAME_INVALID", "repo": repo,
                    "message": f"{name} 不符合命名式 {pattern.pattern}",
                })

    # ② 跨仓同名必须登记
    all_names = {n for vars_ in per_repo.values() for n in vars_}
    shared_declared = set(contract["shared"])
    for name in sorted(all_names):
        repos = [r for r, v in per_repo.items() if name in v]
        if len(repos) > 1 and name not in shared_declared:
            violations.append({
                "code": "SHARED_ENV_UNDECLARED",
                "message": f"{name} 出现在 {sorted(repos)}，但未在 shared 里登记",
            })

    # ③ 共享变量默认值一致
    for name, spec in contract["shared"].items():
        present = {r: v[name] for r, v in per_repo.items() if name in v}
        for repo in spec.get("consumers") or []:
            if repo not in present:
                violations.append({
                    "code": "SHARED_ENV_MISSING", "repo": repo,
                    "message": f"契约声明 {name} 由 {repo} 读取，但源码里没有",
                })
        if len(present) > 1:
            distinct = {v for v in present.values()}
            if len(distinct) > 1:
                detail = " / ".join(f"{r}={v!r}" for r, v in sorted(present.items()))
                violations.append({
                    "code": "SHARED_ENV_DEFAULT_DRIFT",
                    "message": f"{name} 默认值跨仓不一致：{detail}",
                })
            expected = spec.get("default")
            if expected is not None and str(expected) not in {str(v) for v in present.values()}:
                violations.append({
                    "code": "SHARED_ENV_DEFAULT_CONTRACT_MISMATCH",
                    "message": f"{name} 契约默认值 {expected!r} 与源码 {present} 不一致",
                })

    # ④ 凭据字段必须 repr=False
    cred_names = set(contract["credential_field_names"])
    for repo, flds in fields.items():
        for name, protected in flds.items():
            if name in cred_names and not protected:
                violations.append({
                    "code": "CREDENTIAL_FIELD_REPR_LEAK", "repo": repo,
                    "message": (f"{repo} 的 Settings.{name} 未加 field(repr=False)："
                                f"日志层有打码，但异常栈 / pprint / REPL 不走日志层"),
                })

    return {
        "ok": not violations,
        "violations": violations,
        "per_repo": {r: sorted(v) for r, v in per_repo.items()},
        "shared": sorted(shared_declared & all_names),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = check()
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r["ok"] else 1

    for repo, names in r["per_repo"].items():
        print(f"  {repo:<28} {len(names):>2} 个变量")
    print(f"  跨仓共享且已登记：{r['shared']}")
    if r["ok"]:
        print("配置契约闸：通过")
        return 0
    print(f"配置契约闸：阻断（{len(r['violations'])} 处）")
    for v in r["violations"]:
        print(f"  x [{v['code']}] {v.get('repo','')} {v['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
