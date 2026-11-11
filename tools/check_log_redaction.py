#!/usr/bin/env python3
"""ERP 日志打码向量闸：拿真函数跑真向量，不靠读源码判断「有没有保护」。

为什么不用静态检查：`_SENSITIVE_KEY_HINTS` 里有 "password" 不证明 `apiKey` 会被拦住
（实测确实没拦住）。所以这里的判据是**跑一遍**：把契约里的向量喂给各服务的 redact()，
断言凭据值不出现在输出里、非敏感值不被过度打码、以及任何形态都不许抛异常。

覆盖**所有**声明有结构化日志的服务（`services.*.redaction_vectors = true`）：
打码逻辑在两个仓各有一份（内核 observability、API logs），同一组向量必须两个都过——
否则「修好一边」会被当成「全局修好」。

执行环境：内核的 observability 依赖 prometheus_client，用内核 venv；API 的 logs.py
刻意只依赖标准库，所以用系统解释器即可（这也让「纯 stdlib」这条纪律可被验证）。

用法：python3 fd-erp/tools/check_log_redaction.py [--json]
退出码：0 全部通过 / 1 有向量失败 / 2 无法执行
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "fd-erp" / "shared" / "log-contract.json"

#: 每个服务的探针坐标：仓根 / 打码函数所在模块 / 是否需要该仓 venv。
#: venv=False 的服务必须只用标准库——这条本身就是纪律的一部分。
PROBES = {
    "fd-erp-ledger-mcp": {
        "root": "fd-erp-ledger-mcp",
        "module": "fd_erp_ledger_mcp.observability",
        "venv": True,
    },
    "fd-erp-vertical-api": {
        "root": "fd-erp-vertical-api",
        "module": "fd_erp_vertical_api.logs",
        "venv": False,
    },
}

_PROBE = r"""
import importlib, json, sys
sys.path.insert(0, ".")
redact = importlib.import_module(MODULE).redact

vectors = json.load(sys.stdin)
out = {}
for v in vectors:
    try:
        redacted = redact(v["input"])
        out[v["id"]] = {"ok": True, "text": json.dumps(redacted, ensure_ascii=False, sort_keys=True)}
    except Exception as exc:  # 打码失败也算失败：记日志不得因打码而崩
        out[v["id"]] = {"ok": False, "text": f"CRASH {type(exc).__name__}: {exc}"}
print(json.dumps(out, ensure_ascii=False))
"""


def _python(probe: dict) -> str:
    if not probe["venv"]:
        return sys.executable
    candidate = ROOT / probe["root"] / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def _run_probe(name: str, probe: dict, vectors: list[dict]) -> dict:
    root = ROOT / probe["root"]
    proc = subprocess.run(
        [_python(probe), "-c", f"MODULE={probe['module']!r}\n" + _PROBE],
        cwd=str(root), input=json.dumps(vectors), capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "NO_PROXY": "127.0.0.1",
             "PYTHONPATH": "."},
    )
    if proc.returncode != 0:
        return {"runnable": False,
                "message": (f"{name}: 无法执行打码探针（{probe['module']}）："
                            f"{proc.stderr.strip()[:400]}")}
    try:
        return {"runnable": True, "results": json.loads(proc.stdout)}
    except json.JSONDecodeError:
        return {"runnable": False,
                "message": f"{name}: 探针输出不是 JSON：{proc.stdout[:200]}"}


def _judge(vectors: list[dict], results: dict, service: str,
           rows: list[dict], violations: list[dict]) -> None:
    for v in vectors:
        r = results.get(v["id"]) or {}
        text = r.get("text", "")
        problems = []
        if not r.get("ok"):
            problems.append(text or "未返回结果")
        else:
            for needle in v.get("must_not_contain", []):
                if needle in text:
                    problems.append(f"明文外泄：{needle!r}")
            for needle in v.get("must_contain", []):
                if needle not in text:
                    problems.append(f"缺少必需内容：{needle!r}（过度打码或逻辑错）")
        rows.append({"service": service, "id": v["id"], "ok": not problems,
                     "output": text})
        for p in problems:
            violations.append({"code": "REDACTION_VECTOR_FAILED",
                               "message": f"[{service}][{v['id']}] {p} → {text[:160]}"})


def check() -> dict:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    vectors = contract["redaction"]["vectors"]
    declared = contract["services"]

    violations: list[dict] = []
    rows: list[dict] = []
    ran: list[str] = []

    for name, spec in declared.items():
        # 服务覆盖声明与实况一致性：声明「有结构化日志」的必须有 emitter 文件
        if spec.get("structured_logs"):
            emitter = ROOT / spec["emitter"]
            if not emitter.is_file():
                violations.append({"code": "LOGGER_DECLARED_MISSING",
                                   "message": f"{name} 声明有结构化日志，但 {spec['emitter']} 不存在"})
        if not spec.get("redaction_vectors"):
            continue
        probe = PROBES.get(name)
        if probe is None:
            violations.append({"code": "PROBE_NOT_CONFIGURED",
                               "message": f"{name} 声明要跑打码向量，但闸里没有它的探针坐标"})
            continue

        probe_out = _run_probe(name, probe, vectors)
        if not probe_out["runnable"]:
            violations.append({"code": "PROBE_FAILED",
                               "message": probe_out["message"]})
            continue
        ran.append(name)
        _judge(vectors, probe_out["results"], name, rows, violations)

    if not ran:
        violations.append({"code": "NO_PROBE_RAN",
                           "message": "没有任何服务跑过打码向量——「没跑」不等于「通过」"})

    return {"ok": not violations, "runnable": bool(ran), "violations": violations,
            "results": rows, "vector_count": len(vectors), "services": ran}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = check()
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r["ok"] else 1

    if not r["runnable"]:
        print("日志向量闸：无法执行（venv / 依赖 / 探针坐标缺失）")
        for v in r["violations"]:
            print(f"  ! {v['message']}")
        return 2
    for row in r["results"]:
        print(f"  {'ok  ' if row['ok'] else 'FAIL'}  {row['service']:<22} {row['id']:<22} "
              f"{row['output'][:72]}")
    if r["ok"]:
        print(f"日志向量闸：通过（{r['vector_count']} 条向量 × {len(r['services'])} 个服务："
              f"{'、'.join(r['services'])}）")
        return 0
    print(f"日志向量闸：阻断（{len(r['violations'])} 处）")
    for v in r["violations"]:
        print(f"  x [{v['code']}] {v['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
