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
    # REST 实现面 ↔ 四份 api-contract.md 双向对拍（change:
    # gate-rest-surface-against-contract）。守的是「契约写着『全部端点同源』却没人核对」
    # 那类事故：2026-11-12 实测 6 条端点实现完了、契约表里没有。
    ("REST 面与契约一致", "check_rest_surface.py"),
    # 如实 501 的阻塞归属（change: track-blocked-endpoints-by-dependency）。此前 11 条 501
    # 只有散文理由，没人能回答「哪个依赖解除会点亮哪几条」，也没人会发现「依赖早到位、
    # 端点还挂 501」。本闸把判据做成机器可读的外部事实（连接器 provider 状态 / 内核工具名）。
    ("501 阻塞归属", "check_blocked_endpoints.py"),
    # 全覆盖矩阵要跨仓核证据（工具面/端点/连接器事实），兄弟仓不在场时它只做仓内部分
    ("全覆盖矩阵", "check_coverage_matrix.py"),
]

#: 工作区里才有意义的外仓闸（不在 fd-erp 内）
EXTERNAL_GATES = [
    ("对外声明（claim_gate）", ROOT / "fd-erp-vertical-templates" / "scripts" / "claim_gate.py"),
    # 团队覆盖闸住在 fleet-packs（它读本仓矩阵）。兄弟仓不在位时 SKIP 并写明「未执行」
    # ——跳过与通过是两件事，前者可审计。
    ("ERP 团队覆盖", ROOT / "fleet-packs" / "scripts" / "check_erp_team_coverage.py"),
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

    # 派生文档漂移：**两种模式都跑**（2026-11-16）。
    # 先前它整段在 `if not args.ci` 里，而 CI 跑的正是 `--ci` ⇒ 这条闸在 CI 里一次都
    # 没跑过（判据齐全、调用方缺失）。现在生成器对「出处文件不全」退 **2**，这里据此记
    # SKIP 并点名缺什么——与跨仓闸同一口径：判不出就不许装成通过。
    # 两句分工要说清：CI 由「生成物指纹」（artifact-lock，见下）抓「有人手改了生成物」；
    # 「上游数字变了没重生成」只有看得到兄弟仓时判得出，归工作区那次全跑。
    code, out = _run([sys.executable, "-I", str(TOOLS / "gen_erp_docs.py"), "--check"])
    drift_tail = (out.splitlines() or ["（无输出）"])[0]
    drift_state = "PASS" if code == 0 else ("SKIP" if code == 2 else "FAIL")
    rows.append(("派生文档漂移", drift_state, drift_tail))
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

    # 子代理补丁：`impeccable install` 会整体覆盖 .claude/agents/，补丁随之丢失。
    # 退出 2 = 没装过 impeccable：记 SKIP，不当作通过。
    code, out = _run([sys.executable, "-I", str(TOOLS / "patch_impeccable_agents.py"), "--check"])
    tail = (out.splitlines() or ["（无输出）"])[-1]
    agent_state = "PASS" if code == 0 else ("SKIP" if code == 2 else "FAIL")
    rows.append(("子代理补丁（impeccable）", agent_state, tail))
    failed = failed or code not in (0, 2)

    schema_problems = check_contract_schema()
    rows.append(("契约 schema 自洽", "FAIL" if schema_problems else "PASS",
                 f"{len(schema_problems)} 处问题" if schema_problems else "全部契约结构合法"))

    # 规格归属：可复算枚举（不写死条数——写死要么常年红、要么被随手改数改绿）。
    # 只读工作区的 openspec 根，单仓也能跑；CI 看不到根时退 2 ⇒ SKIP。
    code, out = _run([sys.executable, "-I", str(TOOLS / "check_spec_ownership.py")])
    own_tail = (out.splitlines() or ["（无输出）"])[-1]
    own_state = "PASS" if code == 0 else ("SKIP" if code == 2 else "FAIL")
    rows.append(("规格归属枚举", own_state, own_tail))
    failed = failed or code not in (0, 2)

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
