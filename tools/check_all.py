#!/usr/bin/env python3
"""ERP 全部闸的一次跑完入口。

两种模式，区别是**能不能看见兄弟仓**——这不是风格差异，决定哪些闸在 CI 里算数：

  （默认）workspace 模式：在 finddata 工作区里跑。跨仓闸（工具面/语义/配置/日志向量）
      读兄弟目录的源码，能验真东西。
  --ci 模式：只在 fd-erp 单仓里跑。兄弟仓不在场，跨仓闸**不假装通过**——它们被显式列为
      SKIP 并说明原因；此时真正算数的只有：
        · 契约文件本身的 schema 自洽（能拦住拼错的声明）
        · 生成物指纹（artifact-lock.json）——手改 README/站点会露馅

CI 里跑的是 --ci 子集，这是**刻意的**：一个在没有输入时"全绿"的闸，比没有闸更糟。

退出码：0 全通过（允许有已说明的 SKIP）/ 1 有失败 / 2 无法执行
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FD_ERP = ROOT / "fd-erp"
TOOLS = FD_ERP / "tools"
LOCK = FD_ERP / "shared" / "artifact-lock.json"

#: 跨仓闸：需要兄弟仓源码在场
CROSS_REPO_GATES = [
    ("工具面覆盖面", "check_kernel_client_contract.py"),
    ("跨仓语义（错误码/指标）", "check_semantics_contract.py"),
    ("环境变量契约", "check_config_contract.py"),
    ("日志打码向量", "check_log_redaction.py"),
]

#: 工作区里才有意义的外仓闸（不在 fd-erp 内）
EXTERNAL_GATES = [
    ("对外声明（claim_gate）", ROOT / "fd-erp-vertical-templates" / "scripts" / "claim_gate.py"),
]


def _run(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(args, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin:/usr/local/bin", "NO_PROXY": "127.0.0.1"})
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    return proc.returncode, (out + ("\n" + err if err else ""))


def _siblings_present() -> tuple[bool, list[str]]:
    missing = [p for p in ("fd-erp-ledger-mcp", "fd-erp-vertical-api", "fd-erp-vertical-templates")
               if not (ROOT / p).is_dir()]
    return not missing, missing


def check_contract_schema() -> list[dict]:
    """契约文件自洽：CI 里唯一能算数的结构检查。"""
    problems: list[dict] = []
    contracts = sorted((FD_ERP / "shared").glob("*.json"))
    if not contracts:
        problems.append({"code": "NO_CONTRACTS", "message": "shared/ 下没有任何契约文件"})
    for path in contracts:
        rel = path.relative_to(ROOT)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append({"code": "CONTRACT_UNPARSABLE", "message": f"{rel}: {exc}"})
            continue
        if not isinstance(data, dict) or "schema" not in data:
            problems.append({"code": "CONTRACT_NO_SCHEMA", "message": f"{rel}: 缺 schema 字段"})
            continue
        name = path.name
        if name == "config-contract.json":
            for var, spec in (data.get("shared") or {}).items():
                if not isinstance(spec, dict) or "consumers" not in spec:
                    problems.append({"code": "CONTRACT_SHAPE",
                                     "message": f"{rel}: shared.{var} 缺 consumers"})
        if name == "semantics-contract.json":
            for svc, codes in (data.get("error_codes", {}).get("service_specific_codes") or {}).items():
                for code, reason in codes.items():
                    if not str(reason or "").strip():
                        problems.append({"code": "CONTRACT_EMPTY_REASON",
                                         "message": f"{rel}: {svc}.{code} 没有理由"})
        if name == "log-contract.json":
            vectors = (data.get("redaction") or {}).get("vectors") or []
            if not vectors:
                problems.append({"code": "CONTRACT_NO_VECTORS", "message": f"{rel}: 没有打码向量"})
            for v in vectors:
                for key in ("id", "input"):
                    if key not in v:
                        problems.append({"code": "CONTRACT_VECTOR_SHAPE",
                                         "message": f"{rel}: 向量缺 {key} → {v}"})
        if name == "kernel-client-contract.json":
            for c in data.get("consumers") or []:
                for key in ("repo", "client", "classes", "must_cover", "intentionally_absent"):
                    if key not in c:
                        problems.append({"code": "CONTRACT_SHAPE",
                                         "message": f"{rel}: consumer 缺 {key}"})
    return problems


def check_artifact_lock() -> list[dict]:
    """生成物指纹：谁手改了 README / 站点，这里就红。"""
    if not LOCK.is_file():
        return [{"code": "LOCK_MISSING", "message": "shared/artifact-lock.json 不存在（跑一次 gen_erp_docs.py）"}]
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    problems: list[dict] = []
    for rel, want in (lock.get("artifacts") or {}).items():
        path = FD_ERP / rel
        if not path.is_file():
            problems.append({"code": "ARTIFACT_MISSING", "message": f"生成物不在：fd-erp/{rel}"})
            continue
        got = hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        if got != want:
            problems.append({"code": "ARTIFACT_TAMPERED",
                             "message": f"fd-erp/{rel} 与指纹不符（手改生成物？重跑 gen_erp_docs.py）"})
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ci", action="store_true", help="只跑单仓能自证的部分")
    args = ap.parse_args()

    rows: list[tuple[str, str, str]] = []   # (名称, 状态, 备注)
    failed = False

    # 边缘宿主机配置：纯本地文件检查，CI 与 workspace 都跑。
    # 它守的是 2026-11-11 两次全站白屏的根因（单站点 bind 抢走共享监听地址）。
    # 退出 2 = 线上连不上：记 SKIP（不伪装通过），与跨仓闸同一口径。
    host_args = [sys.executable, "-I", str(TOOLS / "check_host_configs.py")]
    code, out = _run(host_args + ([] if args.ci else ["--live"]))
    tail = (out.splitlines() or ["（无输出）"])[-1]
    host_state = "PASS" if code == 0 else ("SKIP" if code == 2 else "FAIL")
    rows.append(("边缘配置（bind 不抢地址）", host_state, tail))
    failed = failed or code not in (0, 2)

    if not args.ci:
        ok, missing = _siblings_present()
        for label, script in CROSS_REPO_GATES:
            if not ok:
                rows.append((label, "SKIP", f"兄弟仓缺失：{','.join(missing)}"))
                continue
            code, out = _run([sys.executable, "-I", str(TOOLS / script)])
            tail = (out.splitlines() or ["（无输出）"])[-1]
            rows.append((label, "PASS" if code == 0 else "FAIL", tail))
            failed = failed or code != 0

        code, out = _run([sys.executable, "-I", str(TOOLS / "gen_erp_docs.py"), "--check"])
        rows.append(("派生文档漂移", "PASS" if code == 0 else "FAIL", (out.splitlines() or ["（无输出）"])[-1]))
        failed = failed or code != 0

        for label, gate in EXTERNAL_GATES:
            if not gate.is_file():
                rows.append((label, "SKIP", f"脚本不在：{gate.relative_to(ROOT)}"))
                continue
            code, out = _run([sys.executable, "-I", str(gate), "check"], cwd=gate.parents[1])
            tail = (out.splitlines() or ["（无输出）"])[0]
            rows.append((label, "PASS" if code == 0 else "FAIL", tail))
            failed = failed or code != 0
    else:
        for label, _ in CROSS_REPO_GATES:
            rows.append((label, "SKIP", "CI 单仓模式：兄弟仓不在场，不假装通过"))

    schema_problems = check_contract_schema()
    rows.append(("契约 schema 自洽", "FAIL" if schema_problems else "PASS",
                 f"{len(schema_problems)} 处问题" if schema_problems else "全部契约结构合法"))

    lock_problems = check_artifact_lock()
    rows.append(("生成物指纹", "FAIL" if lock_problems else "PASS",
                 "指纹一致" if not lock_problems else f"{len(lock_problems)} 处不符"))

    width = max(len(r[0]) for r in rows)
    for label, state, note in rows:
        print(f"  {state:<4} {label:<{width}}  {note}")
    for p in schema_problems + lock_problems:
        print(f"  x [{p['code']}] {p['message']}")

    if failed or schema_problems or lock_problems:
        print("\nERP 闸：阻断")
        return 1
    skipped = sum(1 for r in rows if r[1] == "SKIP")
    print(f"\nERP 闸：通过" + (f"（{skipped} 项因场景缺输入而 SKIP，非通过）" if skipped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
