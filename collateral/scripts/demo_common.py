"""ERP 演示公共层：MCP 结果解包 + 输出排版 + 演示环境装载。

演示纪律（与 collateral-solution 同规）：
- 数字白名单：脚本打印的每个数字都来自当下真实调用返回，不硬编预期值冒充实测。
- 凭证零泄漏：DSN/口令只从 secrets/erp-demo.env 读取，绝不打印。
- 数据合成标注：所有业务数据为演示合成（demo_adapters.py 内注明），非真实客户数据。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

def _workspace_root() -> Path:
    """工作区根：**向上找锚点**，不数 `..`。

    2026-11-16 这套脚本从 `finddata/collateral-erp/scripts/` 搬进
    `finddata/fd-erp/collateral/scripts/`，三个脚本里各自写死的层级（`.parent.parent`
    / `.parents[2]` / `.parents[3]`）**同时**指错了地方，而症状是「模板目录不存在」
    这类看不出与搬迁有关的报错。把深度改成「找到含 fd-erp-vertical-templates 的那一级」
    之后，再搬一次也不会静默走错；找不到就显式报错，不猜。
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "fd-erp-vertical-templates").is_dir():
            return parent
    raise RuntimeError(
        "找不到工作区根（向上没有任何一级含 fd-erp-vertical-templates）——"
        f"本文件在 {Path(__file__).resolve()}；演示脚本要求工作区里有兄弟仓")


FINDATA = _workspace_root()
SECRETS = FINDATA / "secrets" / "erp-demo.env"

# 模板包 + 其 venv 依赖提前入 path（本脚本用内核 venv 的 python 跑，fastmcp 在内核侧）
import sys as _sys  # noqa: E402
for _p in (str(FINDATA / "fd-erp-vertical-templates"),
           str(FINDATA / "fd-erp-vertical-templates" / ".venv" / "lib" / "python3.14"
               / "site-packages")):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

CB_URL = "http://127.0.0.1:8301/mcp/"
REST_URL = "http://127.0.0.1:8302/mcp/"
TENANT_CB = "demo-crossborder"
TENANT_REST = "demo-restaurant"


def load_env() -> None:
    """把 secrets/erp-demo.env 装进进程环境（只装不显）。"""
    for line in SECRETS.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            os.environ.setdefault(k, v)


def unwrap(result: Any) -> Any:
    """fastmcp CallToolResult → 业务 dict（.data 优先，空则退 structured_content）。

    空 {} 可能掩盖真实错误（如 ERP_FX_UNSOURCED），必须回退取完整负载。
    """
    data = getattr(result, "data", None)
    if data:
        return data
    sc = getattr(result, "structured_content", None)
    if sc:
        return sc
    content = getattr(result, "content", None)
    if content:
        try:
            return json.loads(content[0].text)
        except Exception:  # noqa: BLE001
            return content[0].text
    return result


def make_kernel(url: str, tenant_id: str):
    """生产形态客户端：模板包 McpKernelClient（MCP over HTTP，8 工具同形）。"""
    from fd_erp_vertical_templates.kernel_client import McpKernelClient
    return McpKernelClient(url, tenant_id)


def rule(title: str) -> None:
    print(f"\n{'=' * 64}\n■ {title}\n{'=' * 64}")


def step(name: str) -> None:
    print(f"\n--- {name}")


def show(obj: Any, *, keys: list[str] | None = None, note: str = "") -> None:
    """打印关键返回（可只挑字段）；note 为一句业务解读。"""
    if keys and isinstance(obj, dict):
        obj = {k: obj.get(k) for k in keys if k in obj}
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    if note:
        print(f"  ↳ {note}")


def balance_by_code(kernel, code: str) -> dict[str, Any]:
    res = unwrap(kernel.query_balance(account_code=code))
    data = res.get("data", res) if isinstance(res, dict) else res
    rows = data if isinstance(data, list) else [data]
    return rows[0] if rows else {}


def reset_demo_tenant(tenant_id: str) -> None:
    """演示库清场（ERP_DEMO_RESET=1 时由演示脚本开头调用）。

    ⚠️ 仅限一次性演示库：走 DBA SQL 清 proposals/entries/recon/audit，
    内核工具面的删除路径依然不存在（append-only 约束只在运行时车道上）。
    生产租户严禁调用。
    """
    if os.environ.get("ERP_DEMO_RESET", "1") != "1":
        return
    import psycopg
    dsn = os.environ["ERP_LEDGER_DATABASE_URL"]
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        # append-only 触发器会拦 TRUNCATE——演示库清场先临时摘触发器再复原
        cur.execute("ALTER TABLE journal_entries DISABLE TRIGGER all")
        cur.execute(
            "TRUNCATE proposals, journal_entries, recon_reports, "
            "recon_task_items, audit")
        cur.execute("ALTER TABLE journal_entries ENABLE TRIGGER all")
        # fx_facts 是内核级参考数据（租户无关），清场不动——保持出处登记持续有效
    print(f"[reset] 演示租户 {tenant_id} 账面已清场（DBA SQL，非工具面）")
