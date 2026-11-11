#!/usr/bin/env python3
"""ERP 日志打码向量闸：拿真函数跑真向量，不靠读源码判断「有没有保护」。

为什么不用静态检查：`_SENSITIVE_KEY_HINTS` 里有 "password" 不证明 `apiKey` 会被拦住
（实测确实没拦住）。所以这里的判据是**跑一遍**：把契约里的向量喂给内核的 redact()，
断言凭据值不出现在输出里、非敏感值不被过度打码、以及任何形态都不许抛异常。

执行环境：内核的 venv（observability 依赖 prometheus_client）。脚本自己找：
  fd-erp-ledger-mcp/.venv/bin/python
找不到就用当前解释器并如实报「无法执行」（缺失 != 通过）。

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
KERNEL = ROOT / "fd-erp-ledger-mcp"

_PROBE = r"""
import json, sys
sys.path.insert(0, ".")
from fd_erp_ledger_mcp.observability import redact

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


def _python() -> str:
    candidate = KERNEL / ".venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


def check() -> dict:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    vectors = contract["redaction"]["vectors"]

    proc = subprocess.run(
        [_python(), "-c", _PROBE],
        cwd=str(KERNEL), input=json.dumps(vectors), capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "NO_PROXY": "127.0.0.1", "PYTHONPATH": "."},
    )
    if proc.returncode != 0:
        return {"ok": False, "runnable": False,
                "violations": [{"code": "PROBE_FAILED",
                                "message": f"无法在内核 venv 里执行打码探针：{proc.stderr.strip()[:400]}"}],
                "results": []}

    results = json.loads(proc.stdout)
    violations: list[dict] = []
    rows: list[dict] = []

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
        rows.append({"id": v["id"], "ok": not problems, "output": text})
        for p in problems:
            violations.append({"code": "REDACTION_VECTOR_FAILED",
                               "message": f"[{v['id']}] {p} → {text[:160]}"})

    # 服务覆盖声明与实况一致性：声明「有结构化日志」的必须有 emitter 文件
    declared = contract["services"]
    for name, spec in declared.items():
        if spec.get("structured_logs"):
            emitter = ROOT / spec["emitter"]
            if not emitter.is_file():
                violations.append({"code": "LOGGER_DECLARED_MISSING",
                                   "message": f"{name} 声明有结构化日志，但 {spec['emitter']} 不存在"})

    return {"ok": not violations, "runnable": True, "violations": violations,
            "results": rows, "vector_count": len(vectors)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = check()
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r["ok"] else 1

    if not r["runnable"]:
        print("日志向量闸：无法执行（venv 或依赖缺失）")
        for v in r["violations"]:
            print(f"  ! {v['message']}")
        return 2
    for row in r["results"]:
        print(f"  {'ok  ' if row['ok'] else 'FAIL'}  {row['id']:<22} {row['output'][:88]}")
    if r["ok"]:
        print(f"日志向量闸：通过（{r['vector_count']} 条向量）")
        return 0
    print(f"日志向量闸：阻断（{len(r['violations'])} 处）")
    for v in r["violations"]:
        print(f"  x [{v['code']}] {v['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
