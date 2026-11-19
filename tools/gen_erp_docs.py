#!/usr/bin/env python3
"""从仓内唯一出处派生 ERP 归属总图（README.md）与独立介绍站（site/index.html）。

产权纪律：
  - 本脚本不写任何事实，只读 manifest.json + 各仓的机器可读产物（claims / gaps /
    publish-record / tool-surface / coverage evidence / matrices / 模板 manifest），
    再渲染成文档。新增能力先进那些出处，不要往模板里手写。
  - 因此站点上的每个数字都能被 claim_gate 与 release_gate 复核。

用法：
  python3 fd-erp/tools/gen_erp_docs.py            # 写入 README.md 与 site/index.html
  python3 fd-erp/tools/gen_erp_docs.py --check    # 只比对，不落盘（CI 用；不一致退出 1）
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FD_ERP = ROOT / "fd-erp"

#: 文案键必须**显式**把本文件所在目录放进 `sys.path`。`check_all.py` 用
#: `[sys.executable, "-I", <script>]` 调本脚本，而 `-I` 隐含 `-P`（不预置脚本目录）
#: ⇒ 只靠默认行为会 `ModuleNotFoundError: site_i18n`，症状是「派生文档漂移」那条闸
#: 突然报判不出/红，而代码本身没错。这一行是那次教训的落地。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from site_i18n import (COVERAGE_STATE_LABELS_EN, LANG_KEYS,  # noqa: E402
                       STRINGS, TERMINOLOGY)
from site_i18n import t as _t  # noqa: E402


def _has_key(lang: str):
    """该语言是否有这个键（层 1/3/4 有 `_hop`、2/5 没有，用键存在性而不是写死分支）。"""
    return lambda key: key in STRINGS[lang]


#: 全覆盖四态：标签与顺序与 fd-erp-vertical-templates/scripts/claim_gate.py 同源。
#: 第五态不存在——矩阵里出现别的值由 check_coverage_matrix.py 判红，本脚本若读到
#: 未知态会直接 MissingKeyError，不会把它印成空白。
COVERAGE_STATE_LABELS = {
    "delivered": "已实现",
    "template_configured": "模板可配",
    "needs_onboarding": "需一次接入",
    "not_doing": "明确不做",
}
COVERAGE_STATE_ORDER = ("delivered", "template_configured",
                        "needs_onboarding", "not_doing")


# ── 读数据 ────────────────────────────────────────────────────────────────────
def load(rel: str):
    p = ROOT / rel
    if not p.is_file():
        raise SystemExit(f"缺少出处文件：{rel}")
    return json.loads(p.read_text(encoding="utf-8"))


def collect() -> dict:
    m = load("fd-erp/manifest.json")
    src = m["sources"]
    return {
        "manifest": m,
        "contract": load("fd-erp/shared/kernel-client-contract.json"),
        "semantics": _semantics(),
        "config": _gate("check_config_contract.py"),
        "logs": _gate("check_log_redaction.py"),
        "log_contract": load("fd-erp/shared/log-contract.json"),
        "claims": load(src["claims"]),
        "gaps": load(src["gaps"]),
        "publish": load(src["publish_record"]),
        "surface": load(src["tool_surface"]),
        "evidence": load(src["evidence"]),
        "matrix": load(f"{src['matrices']}/supply-chain.json"),
        #: 板块级全覆盖矩阵（21 格四态，唯一出处；站点覆盖栏由它派生）
        "coverage": load("fd-erp/shared/coverage-matrix.json"),
        #: 营销（第二个生产者）已登记的事实类型——从种子 SQL 解析，不另存清单
        "marketing_types": marketing_event_types(),
        "templates": {
            v: load(f"{src['templates']}/{v}/manifest.json")
            for v in ("crossborder", "restaurant-chain", "supply-chain")
        },
    }


def _gate(script: str) -> dict:
    """复用契约闸的计算跑一遍 check()——不在这里重新实现一遍 AST 读取。"""
    import importlib.util

    path = Path(__file__).with_name(script)
    spec = importlib.util.spec_from_file_location(f"_erp_gate_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.check()


def _semantics() -> dict:
    return _gate("check_semantics_contract.py")


#: 营销事件类型登记在迁移里（注册表是封闭集，种子 SQL 就是唯一出处）。
#: 这里直接解析那段 VALUES，而不是再维护一份 JSON 清单——两份清单必然漂移，
#: 而漂移时没人知道该信哪份。
_MARKETING_SEED = (
    Path(__file__).resolve().parents[2]
    / "fd-erp-ledger-mcp/fd_erp_ledger_mcp/migrations/0011_marketing_producers.sql"
)


def marketing_event_types(path: Path = _MARKETING_SEED) -> list[dict]:
    """从种子 SQL 里抠出 `producer='marketing'` 的类型行（名字/说明/载体/是否过账）。"""
    if not path.is_file():
        raise SystemExit(f"缺少营销类型种子：{path}")
    sql = path.read_text(encoding="utf-8")
    head = sql.find("INSERT INTO event_types")
    if head < 0:
        raise SystemExit(f"{path} 里找不到 event_types 的 INSERT")
    body = sql[head:]
    out: list[dict] = []
    # 每个元组：('marketing.x.y', '说明', '{...}'::jsonb, 'day', INTERVAL '0',
    #            false, 'UTC', 'marketing', 'marketing', '载体出处'),
    # 只认整段元组：截到 `)` 后面紧跟 `,` 或 `ON CONFLICT` 为止。
    spans = re.finditer(r"\(\s*'(marketing\.[a-z0-9_.]+)'(.*?)\)(?=,|\s*ON\s+CONFLICT)",
                        body, re.DOTALL)
    for m in spans:
        name, rest = m.group(1), m.group(2)
        quoted = [q.replace("''", "'") for q in re.findall(r"'((?:[^']|'')*)'", rest)]
        posting = re.search(r"INTERVAL\s+'[^']*',\s*(true|false)", rest)
        out.append({
            "event_type": name,
            "description": quoted[0] if quoted else "",
            # 载体出处是元组的最后一个字符串字面量
            "evidence_ref": quoted[-1] if quoted else "",
            "requires_posting": (posting.group(1) == "true") if posting else None,
        })
    if not out:
        raise SystemExit(f"{path} 里没解析出任何 marketing 类型——种子格式变了，先修本解析")
    return out


def route_stats(evidence: dict) -> dict:
    routes = evidence["routes"]
    by_face: Counter[str] = Counter()
    ph_by_face: Counter[str] = Counter()
    health = 0
    prefix = "/erp/supply-chain/v1"
    for r in routes:
        path = r["path"]
        if not path.startswith(prefix):
            health += 1  # /health、/healthz —— 探针不是业务面
            continue
        parts = path.split("/")
        face = parts[4] if len(parts) > 4 else "(根)"
        by_face[face] += 1
        if r.get("placeholder"):
            ph_by_face[face] += 1
    return {
        "total": len(routes),
        "health": health,
        "business": len(routes) - health,
        "placeholder": sum(ph_by_face.values()),
        "by_face": dict(sorted(by_face.items())),
        "ph_by_face": dict(sorted(ph_by_face.items())),
    }


# ── README（对内：归属与债） ───────────────────────────────────────────────────
def render_readme(d: dict) -> str:
    m = d["manifest"]
    b = m["board"]
    lines: list[str] = []
    a = lines.append

    a("# fd-erp — ERP 板块独立维护根")
    a("")
    a("> 本文件由 `fd-erp/tools/gen_erp_docs.py` 从 `fd-erp/manifest.json` 与各仓机器可读产物派生，**不要手改**。")
    a(f"> 生成日期：{date.today().isoformat()}。改归属/改资产位置请先改 `manifest.json` 再重跑生成器。")
    a("")
    a(f"{b['name']} 是**{b['tag_zh']}**，{b['position']}。章程 `{b['spec']}`；对外口径唯一出处 `{b['charter_doc']}`。")
    a("")
    a("## 1. 代码仓")
    a("")
    a("| 角色 | 目录 | 远端 | 形态 | 源码 / 测试 | 边界 |")
    a("|---|---|---|---|---|---|")
    for r in m["repos"]:
        a(
            f"| {r['role']} | `{r['path']}` | `{r['remote']}` | {r['surface']} "
            f"| {r['src_loc']} / {r['tests_loc']} 行 | {r['boundary']} |"
        )
    a("")
    a("## 2. 资产与规格")
    a("")
    a("| 资产 | 位置 | 有版本控制 | 归属 | 注意 |")
    a("|---|---|---|---|---|")
    for x in m["assets"]:
        ver = "是" if x["versioned"] else "**否**"
        owner = f"`{x['owner_repo']}`" if x["owner_repo"] else "—"
        a(f"| {x['what']} | `{x['path']}` | {ver} | {owner} | {x['note']} |")
    a("")
    a("## 3. 跨仓耦合点（ERP 代码活在别人仓里）")
    a("")
    a("| 内容 | 位置 | 所属仓 | 为什么必须在那 |")
    a("|---|---|---|---|")
    for c in m["couplings"]:
        a(f"| {c['what']} | `{c['path']}` | `{c['owner_repo']}` | {c['why']} |")
    a("")
    a("## 4. 共享组件债（同一契约的 N 份实现）")
    a("")
    a("| 组件 | 实现数 | 位置 | 问题 |")
    a("|---|---|---|---|")
    for s in m["shared_component_debt"]:
        locs = "<br>".join(f"`{p}`" for p in s["implementations"])
        a(f"| `{s['component']}` | {len(s['implementations'])} | {locs} | {s['problem']} |")
    a("")
    a("### 4.1 内核工具面 × 客户端覆盖面（声明式契约）")
    a("")
    a("工具面真源 `fd-erp-ledger-mcp/tool-surface.json`；谁必须盖哪些、哪些故意不盖及理由，"
      "写在 `fd-erp/shared/kernel-client-contract.json`。两侧漂移由 "
      "`fd-erp/tools/check_kernel_client_contract.py` 判红（声明 ≠ 实际、发明工具面之外的方法、"
      "不覆盖却没给理由，三种都拦）。")
    a("")
    a("| 消费仓 | 覆盖 | 声明不覆盖 |")
    a("|---|---|---|")
    for c in d["contract"]["consumers"]:
        n_absent = len(c["intentionally_absent"])
        a(f"| `{c['repo']}` | {len(c['must_cover'])} | {n_absent} |")
    a("")
    a("> 注：tenant 由客户端绑定、不逐方法透传（一进程一租户）；"
      "`approved_by` / `submitted_by` / `reversed_by` 不透传，由内核按默认值填 "
      "（`human` / `ops` / `human`）—— 这是审计口径的已知取舍，不是漏参。")
    a("")
    a("### 4.2 跨仓语义契约（错误码 / 指标名）")
    a("")
    sem = d["semantics"]
    s = sem["summary"]
    a("码表与指标名一律从源码 AST 现读，契约文件只写「必须逐字一致的部分」与"
      "「允许不同但必须声明的部分」。闸：`fd-erp/tools/check_semantics_contract.py`。")
    a("")
    a(f"- 错误码：内核封闭集 **{s['kernel_codes']}** 个，与 `tool-surface.json` 镜像逐一对照；"
      f"跨仓共享 **{s['shared_codes']}** 个（语义类别 / 可重试 / 默认提示必须逐字一致）；"
      f"api 自有 {s['api_codes'] - s['shared_codes']} 个、模板层自有 9 个，均须在契约里声明并给理由")
    a(f"- 指标：内核 {s['metrics']['fd-erp-ledger-mcp']} 个 / api {s['metrics']['fd-erp-vertical-api']} 个，"
      f"同一 Prometheus 下不得跨服务重名")
    gate_state = "通过" if sem["ok"] else f"阻断（{len(sem['violations'])} 处）"
    a(f"- 闸门状态：{gate_state}")
    for dev in sem["declared_deviations"]:
        a(f"- 已声明偏差（{dev['kind']}，{dev['service']}）：{dev['detail']}；待办 `{dev.get('task','-')}`")
    a("")
    a("### 4.3 环境变量契约")
    a("")
    cfg = d["config"]
    a("变量清单与默认值从源码 AST 现读；契约只声明「哪些是跨仓共享的」与约定本身。"
      "闸：`fd-erp/tools/check_config_contract.py`。")
    a("")
    a("| 仓 | 读取的 `ERP_` 变量数 |")
    a("|---|---|")
    for repo, names in cfg["per_repo"].items():
        a(f"| `{repo}` | {len(names)} |")
    a("")
    a(f"- 跨仓共享且已登记：**{len(cfg['shared'])}** 个 —— "
      + "、".join(f"`{n}`" for n in cfg["shared"]))
    a("- 共享变量默认值必须逐字一致（同名不同默认值 = 同一份部署清单在两个进程里两种行为）")
    a("- 含凭据的 Settings 字段必须 `field(repr=False)`：日志层打码不覆盖异常栈 / pprint / REPL")
    cfg_state = "通过" if cfg["ok"] else f"阻断（{len(cfg['violations'])} 处）"
    a(f"- 闸门状态：{cfg_state}")
    a("")
    a("### 4.4 结构化日志与打码向量")
    a("")
    logs = d["logs"]
    a("只看源码里有没有 `password` 关键字不算验证 —— 本闸把向量喂给内核**真的** `redact()`，"
      "断言凭据值不出现在输出里、非敏感值不被过度打码、任何形态都不许抛异常。"
      "闸：`fd-erp/tools/check_log_redaction.py`。")
    a("")
    a("| 服务 | 结构化日志 | 说明 |")
    a("|---|---|---|")
    for name, spec in d["log_contract"]["services"].items():
        mark = "有" if spec.get("structured_logs") else "**无**"
        note = spec.get("gap") or f"{len(spec.get('events', []))} 个事件"
        a(f"| `{name}` | {mark} | {note} |")
    a("")
    log_state = "通过" if logs["ok"] else f"阻断（{len(logs['violations'])} 处）"
    a(f"- 打码向量：**{logs.get('vector_count', 0)}** 条；闸门状态：{log_state}")
    a("")
    a("## 5. 部署实况")
    a("")
    a(f"集群 `{m['deploy']['cluster_context']}` / 命名空间 `{m['deploy']['namespace']}`。")
    a("")
    a("| 工作负载 | 类型 | 镜像 | Ready | 暴露面 |")
    a("|---|---|---|---|---|")
    for w in m["deploy"]["workloads"]:
        a(f"| `{w['name']}` | {w['kind']} | `{w['image']}` | {w['ready']} | {w['exposure']} |")
    a("")
    a("| CronJob | 计划 | 时区 | 挂起 | 上次触发 | 说明 |")
    a("|---|---|---|---|---|---|")
    for cj in m["deploy"]["cronjobs"]:
        a(
            f"| `{cj['name']}` | `{cj['schedule']}` | {cj['timezone'] or '未声明'} "
            f"| {'**是**' if cj['suspend'] else '否'} | {cj['last_schedule'] or '从未'} | {cj['note']} |"
        )
    a("")
    a("## 6. 独立站发布")
    a("")
    site = m["deploy"].get("site")
    if site and site.get("redact"):
        # 部署细节（host 路径、证书指纹、SSH 目标）不进公开面：README 是对外文档，
        # 这些是运维手册内容。详尽版留在 manifest.deploy.json（不入库）。
        a(f"站点 `{site['host']}`，内容 `{site['content']}`（生成物，勿手改）。")
        a("")
        a("部署拓扑与验收记录内网留存，不随仓公开。")
        a("")
        a(f"**公网状态：{site['public_status']}**")
        a("")
        a("| 公开地址 | 状态 |")
        a("|---|---|")
        for u in site.get("public_urls", []):
            a(f"| {u['url']} | **{u['status']}** |")
        a("")
    elif site:
        a(f"站点 `{site['host']}`，内容 `{site['content']}`（生成物，勿手改）。")
        a("")
        a("| 环节 | 位置 | 备注 |")
        a("|---|---|---|")
        o, e = site["origin"], site["edge"]
        a(f"| 源站 | `{o['ssh_alias']}`（{o['ip']}）`{o['path']}` | nginx `{o['nginx_conf']}` |")
        a(f"| 边缘 | {e['role']}（{e['ip']}） | Caddy `{e['caddy_conf']}`，upstream `{e['upstream']}` |")
        a("")
        a(f"**公网状态：{site['public_status']}**")
        a("")
        a("| 公开地址 | 状态 | 形态 | 验收 |")
        a("|---|---|---|---|")
        for u in site.get("public_urls", []):
            a(f"| {u['url']} | **{u['status']}** | {u['how']} | {u.get('verified', '—')} |")
        a("")
        if site.get("blocked_by"):
            a(f"未打通的地址：{site['blocked_by']}")
            a("")
        a("已验证：")
        for v in site["verified"]:
            a(f"- {v}")
    else:
        a("（未登记站点）")
    a("")
    a("## 7. 能力与缺口（派生，勿手写）")
    a("")
    claims = d["claims"]["claims"]
    delivered = [c for c in claims if c["status"] == "delivered"]
    not_claimable = [c for c in claims if c["status"] == "not_claimable"]
    a(f"- 可宣称能力：**{len(delivered)}** 条（每条带仓内可解析证据）")
    a(f"- 不可宣称：**{len(not_claimable)}** 条（对外材料出现肯定句式即被 `claim_gate.py` 判红）")
    a(f"- 连接器缺口：**{len(d['gaps']['gaps'])}** 条（每项带机器判据）")
    a("")
    # 覆盖怎么落到人：这是「全覆盖」从口径变成执行的那一步，放在能力段后面。
    cells = d["coverage"]["modules"]
    by_kind: Counter[str] = Counter((c.get("owner") or {}).get("kind") for c in cells)
    fleet_cells = [(c["name_zh"], (c.get("owner") or {}).get("ref"))
                   for c in cells if (c.get("owner") or {}).get("kind") == "fleet"]
    a("### 7.1 每格谁在做")
    a("")
    a(f"- 承揽：**{by_kind.get('fleet', 0)}** 格由智能体团队承担、"
      f"**{by_kind.get('template', 0)}** 格由模板资产承担、"
      f"**{by_kind.get('none', 0)}** 格无承担者（需一次接入或明确不做，各带原因）")
    a("- agent 侧工具书：`fd-erp-ledger-mcp/toolkit/`（8 组卡 + `catalog.json`），"
      "判据 `scripts/check_toolkit.py`；团队编制见 `fleet-packs/erp/`，"
      "判据 `scripts/check_erp_team_coverage.py`")
    if fleet_cells:
        a("- 承担者：")
        for name, ref in fleet_cells:
            a(f"  - {name} → `{ref}`")
    a("")
    a("团队按平台既有形状落地（fleet 模板 + 逐岗 preset），装包后在管理面板"
      "「智能体团队」的看板/驾驶舱/决策队列/运行台账里直接可见——"
      "**不为 ERP 另建专用面板**：并行呈现面会成为第二份团队数据。")
    a("")
    # 第二个生产者：事件层不只为 ERP 一家开，但「融合」的边界是载体，不是叙事。
    #
    # 整节包在 claim-gate 生成块里：这张表逐行抄的是类型注册表的 description，
    # 而注册表的措辞里带「已发布」这类宣称词——不标成生成块，claim_gate 会把它当成
    # 人写的能力宣称（CLAIM_UNDECLARED），而它其实是 seed SQL 的派生。标成生成块
    # 不是绕过检查：本节的内容由 `gen_erp_docs.py --check` 与注册表种子对拍。
    mkt = d["marketing_types"]
    a("<!-- claim-gate:begin:marketing-producers -->")
    a("### 7.2 事实层的第二个生产者")
    a("")
    a("事件层是**多生产者**的：同一张只追加流水上，每条事实带 `producer` 标记"
      "（`erp` / `marketing`），纪律一套（幂等键、定型粒度、只追加、状态只许"
      "`pending→accepted|rejected→reversed`）。营销板块当前可生产 "
      f"**{len(mkt)}** 类事实，每类都能指到仓内真实载体：")
    a("")
    a("| 事件类型 | 事实 | 载体出处 | 过账 |")
    a("| --- | --- | --- | --- |")
    for t in mkt:
        posting = "是" if t["requires_posting"] else "否（只记事实，不入账）"
        a(f"| `{t['event_type']}` | {t['description']} | `{t['evidence_ref']}` | {posting} |")
    a("")
    a("- **只有这三类**：投放花费、线索、活动、转化四类在仓内没有任何载体，"
      "登记即被黑名单拒绝（`ERP_EVENT_FABRICATED_FACT`）——"
      "「先补载体再登记类型」，不许先登记再找人填数。")
    a("- **营销账不并入 ERP 账本**：两侧共用的是事件流水与纪律，不是账。"
      "营销事件全部 `requires_posting=false`，ERP 的账本仍只由 ERP 的过账规则产生；"
      "跨板块看数是同租户内的**只读聚合**（按 `producer` 过滤），不是并账。"
      "（`line-integration-charter`：六本账不并成一本。）")
    a("- 闸：类型注册表的前缀自洽、载体出处必填、黑名单三条判据在 "
      "`fd-erp-ledger-mcp/tests/test_marketing_producers.py`；"
      "接线脚本 `fd-wire/scripts/publish_facts_to_kernel.py`（可手动跑、可重放，不进常驻调度）。")
    a("<!-- claim-gate:end:marketing-producers -->")
    a("")
    a("## 8. 待办（结构性）")
    a("")
    for t in m["open_tasks"]:
        a(f"- [ ] {t}")
    a("")
    return "\n".join(lines)


# ── 站点（对外：能力与集成说明，不写营销话术） ────────────────────────────────
CSS = """
:root{
--paper:#eaece5;--paper-2:#e3e7df;--paper-3:#dbe0d7;
--ink:#16211d;--ink-2:#46564e;--ink-3:#525f58;
--rule:#cbd6cc;--rule-2:#a7b6ab;--rule-3:#7f9187;
--red:#8e2b24;--green:#1f5c42;
--serif:"Source Han Serif SC","Noto Serif SC","Songti SC","STSong","SimSun",Georgia,serif;
--sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
--rail:88px
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:400 16.5px/1.85 var(--serif)}
::selection{background:#cadfd0;color:var(--ink)}
:focus-visible{outline:2px solid var(--red);outline-offset:3px}
a{color:var(--ink);text-decoration:none;border-bottom:1px solid var(--rule-2);text-underline-offset:3px}
a:hover{border-bottom-color:var(--red);color:var(--red)}
.skip{position:absolute;left:-9999px}
.skip:focus{left:16px;top:12px;z-index:9;background:var(--paper);padding:8px 12px;border:1px solid var(--ink)}

.masthead{border-bottom:1px solid var(--rule-2);background:var(--paper)}
.masthead .sheet{display:flex;align-items:baseline;gap:16px;padding:14px 0 13px calc(var(--rail) + 24px);font:500 12px/1 var(--sans);letter-spacing:.16em;text-transform:uppercase}
.masthead .brand{letter-spacing:.24em;color:var(--ink)}
.masthead .doc{color:var(--ink-2);letter-spacing:.1em}
.masthead .stamp{margin-left:auto;color:var(--ink-3);font-variant-numeric:tabular-nums lining-nums}

.sheet{max-width:1060px;margin:0 auto;padding:0 24px 0 calc(var(--rail) + 24px);position:relative}
.sheet::before{content:"";position:absolute;left:var(--rail);top:0;bottom:0;width:1px;background:var(--rule)}
.masthead .sheet::before{display:none}

.hero{padding:46px 0 8px;position:relative}
.mark{position:absolute;right:2px;top:40px;transform:rotate(-4deg);border:2px solid var(--red);border-radius:2px;
color:var(--red);font:600 12.5px/1.55 var(--sans);letter-spacing:.14em;text-align:center;padding:7px 11px;opacity:.88}
.mark::after{content:"";position:absolute;inset:3px;border:1px solid var(--red);border-radius:1px;opacity:.7}
.mark span{display:block}
h1{margin:0;font-weight:600;font-size:clamp(2.35rem,5.4vw,3.55rem);line-height:1.12;letter-spacing:-.02em}
h1 .sub{display:block;font-size:.58em;font-weight:500;color:var(--ink-2);margin-top:.22em;letter-spacing:-.01em}
.rule-double{border-top:1px solid var(--ink);position:relative;margin:26px 0 22px}
.rule-double::after{content:"";position:absolute;left:0;right:0;top:3px;height:1px;background:var(--rule-2)}
.lede{max-width:62ch;font-size:1.06rem;margin:0 0 14px}
.basis{max-width:66ch;color:var(--ink-3);font-size:.86rem;line-height:1.7;margin:0 0 30px}

table{width:100%;border-collapse:collapse;font:400 14px/1.6 var(--sans)}
caption{caption-side:top;text-align:left;font:500 12px/1 var(--sans);letter-spacing:.16em;text-transform:uppercase;color:var(--ink-3);padding-bottom:10px}
th,td{text-align:left;padding:9px 12px 9px 0;border-bottom:1px solid var(--rule);vertical-align:top}
th{font-weight:600;font-size:.82rem;color:var(--ink-2);border-bottom:1px solid var(--rule-3);white-space:nowrap}
tbody tr:hover td{background:#e6ece4}
td.num,th.num{white-space:nowrap;text-align:right;font-family:var(--serif);font-variant-numeric:tabular-nums lining-nums;font-size:1rem;padding-right:18px}
.num.big{font-size:1.35rem;line-height:1.3}
.prov{color:var(--ink-2);font-size:.82rem;font-family:var(--mono);letter-spacing:0}
.prov .dim{color:var(--ink-3);font-family:var(--sans);letter-spacing:0}

.fn{font:600 .68rem/1 var(--sans);position:relative;color:var(--ink-3);border:0;padding-left:3px;vertical-align:super}
.fn::after{content:attr(data-src);position:absolute;right:-6px;bottom:1.9em;transform:translateY(4px);text-align:left;white-space:normal;max-width:min(240px,54vw);
background:#1d2a24;color:#eef1ec;font:400 11px/1 var(--mono);padding:5px 8px;border-radius:3px;opacity:0;pointer-events:none;transition:opacity .18s ease-out,transform .18s ease-out}
.fn:hover::after,.fn:focus-visible::after{opacity:1;transform:translateY(0)}
.fn:hover{color:var(--red)}

.acts{display:flex;gap:26px;flex-wrap:wrap;margin:30px 0 0;font:500 13px/1 var(--sans);letter-spacing:.04em}
.acts a{border-bottom:1px solid var(--ink);padding-bottom:4px}
.acts a.ghost{border-bottom-color:var(--rule-2);color:var(--ink-2)}
.acts a:hover{border-bottom-color:var(--red)}

.index{margin:52px 0 0;padding:22px 0 26px;border-top:1px solid var(--ink);border-bottom:1px solid var(--rule-2)}
.index h2{margin:0 0 14px;font:500 12px/1 var(--sans);letter-spacing:.18em;text-transform:uppercase;color:var(--ink-3);border:0;padding:0}
.index ol{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(228px,1fr));gap:0 32px;
font:400 14px/2.1 var(--sans)}
.index a{display:flex;gap:12px;border-bottom:1px dotted var(--rule-2);padding:0}
.index .k{flex:1;min-width:0}
.index .v{margin-left:auto;color:var(--ink-3);font-family:var(--mono);font-size:12.5px;white-space:nowrap}

section{padding:56px 0 8px;position:relative}
section::before{content:"";position:absolute;left:calc(-1 * var(--rail) - 3px);top:63px;width:7px;height:7px;border-radius:50%;background:var(--paper);border:1px solid var(--rule-3)}
h2{margin:0 0 18px;font-weight:600;font-size:1.32rem;letter-spacing:-.01em;padding-bottom:10px;border-bottom:1px solid var(--ink);position:relative}
h2::after{content:"";position:absolute;left:0;right:0;bottom:-4px;height:1px;background:var(--rule-2)}
h3{font:600 .95rem/1.5 var(--sans);margin:26px 0 8px;letter-spacing:.02em}
p{margin:10px 0;max-width:68ch}
.muted{color:var(--ink-3)}
code{font:12.5px/1.5 var(--mono);background:var(--paper-2);padding:1px 5px;border-radius:3px;border:1px solid var(--rule)}

.stack{list-style:none;margin:18px 0 24px;padding:0;border-top:1px solid var(--rule-3)}
.stack li{display:grid;grid-template-columns:210px 1fr;gap:4px 22px;padding:14px 0;border-bottom:1px solid var(--rule)}
.stack .layer{font:600 1rem/1.4 var(--serif)}
.stack .layer em{display:block;font:400 11px/1.6 var(--mono);color:var(--ink-3);font-style:normal;letter-spacing:0;margin-top:4px}
.stack .what{color:var(--ink-2);font:400 13.5px/1.7 var(--sans)}
.stack .hop{grid-column:1/-1;font:400 12.5px/1 var(--mono);color:var(--ink-3);letter-spacing:.02em}
.stack .hop::before{content:"↓ "}

.tb td:first-child{font-family:var(--sans);font-size:.86rem;color:var(--ink-2)}
.tag{display:inline-block;white-space:nowrap;font:400 12.5px/1.65 var(--mono);color:var(--ink-2);border:1px solid var(--rule-2);border-radius:2px;padding:0 5px;margin:1px 5px 1px 0;background:var(--paper)}
.cnt{color:var(--ink-3);font:400 12.5px/1.6 var(--mono);margin-left:4px;white-space:nowrap}
.rw{font:600 11px/1 var(--sans);letter-spacing:.08em}
.rw.w{color:var(--red)}
.rw.r{color:var(--green)}
.st{font:600 12.5px/1 var(--sans);letter-spacing:.04em;white-space:nowrap}
.st.ok{color:var(--green)}
.st.no{color:var(--red)}

.matrix{margin:18px 0 8px}
.bar{display:flex;height:26px;border:1px solid var(--ink);background:var(--paper)}
.bar span{display:block;height:100%;border-right:1px solid var(--paper)}
.bar span:last-child{border-right:0}
.s1{background:var(--ink)}
.s2{background:var(--ink-3)}
.s3{background:var(--rule-3)}
.s4{background:#d9c0bc}
.legend{list-style:none;display:flex;flex-wrap:wrap;gap:8px 26px;margin:12px 0 0;padding:0;font:400 12.5px/1.6 var(--sans);color:var(--ink-2)}
.legend i{display:inline-block;width:11px;height:11px;margin-right:7px;vertical-align:-1px;border:1px solid var(--ink)}
.legend b{font-weight:600;color:var(--ink);font-variant-numeric:tabular-nums lining-nums}

dl.edges{margin:16px 0 8px;border-top:1px solid var(--rule-3)}
dl.edges div{padding:15px 0;border-bottom:1px solid var(--rule)}
dl.edges dt{font:600 .93rem/1.5 var(--sans);letter-spacing:.02em}
dl.edges dd{margin:4px 0 0;color:var(--ink-2);font:400 13.5px/1.7 var(--sans);max-width:70ch}

footer{margin-top:64px;border-top:1px solid var(--ink);padding:22px 0 56px;color:var(--ink-2);font:400 13px/1.9 var(--sans)}
footer h2{font:500 12px/1 var(--sans);letter-spacing:.18em;text-transform:uppercase;color:var(--ink-3);border:0;padding:0 0 12px;margin:0}
footer h2::after{display:none}
footer ul{list-style:none;margin:0 0 18px;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:0 28px}
footer li{font-family:var(--mono);font-size:12.5px}
footer .say{max-width:78ch;margin:0}

@media (max-width:900px){
:root{--rail:0px}
.sheet{padding:0 20px}
.masthead .sheet{padding:12px 0;flex-wrap:wrap;gap:10px 14px}
.masthead .stamp{margin-left:auto}
table:not(.tb){display:block;overflow-x:auto;-webkit-overflow-scrolling:touch}
.tb thead{position:absolute;left:-9999px}
.tb tr{display:grid;grid-template-columns:1fr auto;align-items:baseline;padding:11px 0;border-bottom:1px solid var(--rule)}
.tb td{border:0;padding:0}
.tb td:first-child{grid-column:1;grid-row:1}
.tb td.num{grid-column:2;grid-row:1;text-align:right;padding:0 0 0 12px;font-size:1.15rem}
.tb td.prov{grid-column:1/-1;grid-row:2;padding-top:3px;font-size:12.5px;line-height:1.55}
.prov,.tb .dim{word-break:break-word}
.sheet::before{display:none}
section::before{display:none}
h1{font-size:2.1rem}
.stack li{grid-template-columns:1fr}
.index ol{gap:0;grid-template-columns:1fr}
.mark{position:relative;display:inline-block;top:auto;right:auto;transform:none;margin:16px 0 4px}
}
@media (prefers-reduced-motion:reduce){
*{transition:none!important;animation:none!important}
.fn::after{transition:none}
}
@media print{
body{background:#fff}
.masthead,.acts,.index{display:none}
.sheet{padding:0}
.sheet::before,section::before{display:none}
a{border:0}
}
"""



def esc(x) -> str:
    return html.escape(str(x), quote=True)


def render_site(d: dict, lang: str = "zh") -> str:
    """渲染介绍站。`lang` 只换文案，**数据行一律沿用机器产物原样**（任务 4.2）。

    文案键在 `fd-erp/tools/site_i18n.py`；两语言键集必须同构（`--check` 会核）。
    """
    T = _t(lang)
    has = _has_key(lang)
    state_labels = COVERAGE_STATE_LABELS if lang == "zh" else COVERAGE_STATE_LABELS_EN
    alt_lang = T("alt_lang")
    alt_href = T("alt_href")

    m = d["manifest"]
    b = m["board"]
    claims = d["claims"]["claims"]
    delivered = [c for c in claims if c["status"] == "delivered"]
    not_claimable = [c for c in claims if c["status"] == "not_claimable"]
    gaps = d["gaps"]["gaps"]
    rs = route_stats(d["evidence"])
    groups = d["surface"]["tool_groups"]
    ann = d["surface"]["tool_annotations"]
    points = d["matrix"]["points"]
    packs = d["publish"]["packs"]
    # 板块级全覆盖（21 格四态）：覆写页面上「覆盖」这一栏的口径——客户问「某子模块
    # 有没有」，答案必须落在这四种之一，不是「客户功能清单命中了几点」。
    cells = d["coverage"]["modules"]
    by_state = Counter(c["state"] for c in cells)

    o: list[str] = []
    a = o.append

    a(f'<!doctype html><html lang="{T("lang")}"><head><meta charset="utf-8">')
    a('<meta name="viewport" content="width=device-width,initial-scale=1">')
    a(f"<title>{esc(T('title'))}</title>")
    a(f'<meta name="description" content="{esc(T("meta_desc", name=b["name"]))}">')
    # 两语言互指：搜索引擎按 hreflang 区分两份，别当成重复内容。
    a(f'<link rel="alternate" hreflang="{T("lang")}" href="./">')
    a(f'<link rel="alternate" hreflang="{alt_lang}" href="{alt_href}">')
    a(f"<style>{CSS}</style></head><body>")
    a(f'<a class="skip" href="#main">{T("skip")}</a>')

    # 报头：账簿的页眉，不是标题上方的眉标
    a('<header class="masthead"><div class="sheet">')
    a('<span class="brand">FindData</span>')
    a(f'<span class="doc">{esc(T("doc", name=b["name"]))}</span>')
    a(f'<span class="stamp">{date.today().isoformat()}</span>')
    a(f'<a class="lang" href="{alt_href}" hreflang="{alt_lang}" rel="alternate">{T("switch")}</a>')
    a("</div></header>")

    a('<main id="main" class="sheet">')

    # ── 首屏：定位 + 试算表 + 入口 ───────────────────────────────────────
    a('<div class="hero">')
    a(f'<h1>{esc(b["name"])} {esc(b["tag_zh"])}'
      f'<span class="sub">{esc(T("h1_sub"))}</span></h1>')
    a('<div class="rule-double"></div>')
    a(f'<span class="mark" aria-hidden="true"><span>{T("mark_a")}</span>'
      f'<span>{T("mark_b")}</span></span>')
    a(f'<p class="lede">{T("lede")}</p>')
    a(f'<p class="basis">{T("basis")}</p>')

    a(f'<table class="tb"><caption>{T("tb_caption")}</caption>')
    a(f'<thead><tr><th scope="col">{T("th_item")}</th>'
      f'<th scope="col" class="num">{T("th_count")}</th>'
      f'<th scope="col">{T("th_prov")}</th></tr></thead><tbody>')
    a(f'<tr><td>{T("row_tools")}</td>'
      f'<td class="num big">{len(ann)}<sup><a class="fn" href="#src" data-src="tool-surface.json">1</a></sup></td>'
      '<td class="prov">tool-surface.json</td></tr>')
    a(f'<tr><td>{T("row_routes")}</td>'
      f'<td class="num big">{rs["business"]}<sup><a class="fn" href="#src" data-src="coverage/">2</a></sup></td>'
      f'<td class="prov">coverage/ <span class="dim">'
      f'{esc(T("row_routes_note", health=rs["health"], ph=rs["placeholder"]))}</span></td></tr>')
    a(f'<tr><td>{T("row_templates")}</td>'
      f'<td class="num big">{len(d["templates"])}<sup><a class="fn" href="#src" '
      'data-src="templates/*/manifest.json">3</a></sup></td>'
      '<td class="prov">templates/*/manifest.json</td></tr>')
    a(f'<tr><td>{T("row_claimable")}</td>'
      f'<td class="num big">{len(delivered)}<sup><a class="fn" href="#src" data-src="claims.json">4</a></sup></td>'
      '<td class="prov">claims.json</td></tr>')
    a(f'<tr><td>{T("row_not_claimable")}</td>'
      f'<td class="num big">{len(not_claimable)}<sup><a class="fn" href="#src" data-src="claims.json">5</a></sup></td>'
      '<td class="prov">claims.json</td></tr>')
    a("</tbody></table>")

    a('<nav class="acts">')
    a(f'<a href="#capability">{T("act_capability")}</a>')
    a(f'<a href="#routes">{T("act_routes")}</a>')
    a(f'<a class="ghost" href="#src">{T("act_src")}</a>')
    a(f'<a class="ghost" href="https://www.finddatatech.cloud/" rel="noopener">{T("act_home")}</a>')
    a("</nav>")
    a("</div>")

    # ── 科目索引 ────────────────────────────────────────────────────────
    a(f'<nav class="index"><h2>{T("index_title")}</h2><ol>')
    for anchor, label, hint in (
        ("form", T("idx_form"), T("idx_form_hint")),
        ("capability", T("idx_capability"), T("n_items", n=len(delivered))),
        ("not-claimable", T("idx_not_claimable"), T("n_items", n=len(not_claimable))),
        ("tools", T("idx_tools"), T("n_units", n=len(ann))),
        ("routes", T("idx_routes"), T("n_items", n=rs["business"])),
        ("templates", T("idx_templates"), T("n_sets", n=len(d["templates"]))),
        ("matrix", T("idx_matrix"), T("idx_matrix_hint", n=len(cells))),
        ("gaps", T("idx_gaps"), T("n_items", n=len(gaps))),
        ("edges", T("idx_edges"), T("idx_edges_hint")),
    ):
        a(f'<li><a href="#{anchor}"><span class="k">{label}</span>'
          f'<span class="v">{esc(hint)}</span></a></li>')
    a("</ol></nav>")

    # ── 1 形态 ──────────────────────────────────────────────────────────
    a(f'<section id="form"><h2>{T("form_h2")}</h2>')
    a('<ul class="stack">')
    for n in (1, 2, 3, 4, 5):
        em = f'<em>{esc(T(f"layer{n}_em"))}</em>' if has(f"layer{n}_em") else ""
        what = (esc(T(f"layer{n}_what", routes=rs["business"])) if n == 3
                else esc(T(f"layer{n}_what")))
        hop = (f'<span class="hop">{esc(T(f"layer{n}_hop"))}</span>'
               if has(f"layer{n}_hop") else "")
        a(f'<li><span class="layer">{esc(T(f"layer{n}"))}{em}</span>'
          f'<span class="what">{what}</span>{hop}</li>')
    a("</ul>")
    a(f'<table><caption>{T("repo_caption")}</caption><thead><tr>'
      f'<th scope="col">{T("th_role")}</th><th scope="col">{T("th_repo")}</th>'
      f'<th scope="col">{T("th_surface")}</th>'
      f'<th scope="col" class="num">{T("th_src_loc")}</th>'
      f'<th scope="col" class="num">{T("th_tests_loc")}</th></tr></thead><tbody>')
    for r in m["repos"]:
        a(f'<tr><td>{esc(r["role"])}</td><td><code>{esc(r["path"])}</code></td>'
          f'<td class="muted">{esc(r["surface"])}</td>'
          f'<td class="num">{r["src_loc"]}</td><td class="num">{r["tests_loc"]}</td></tr>')
    a("</tbody></table></section>")

    # ── 2 能力面 ────────────────────────────────────────────────────────
    a(f'<section id="capability"><h2>{T("cap_h2")}</h2>')
    a(f'<table><thead><tr><th scope="col">{T("th_capability")}</th>'
      f'<th scope="col">{T("th_id")}</th>'
      f'<th scope="col">{T("th_evidence")}</th></tr></thead><tbody>')
    for c in delivered:
        kinds = sorted({e.get("kind", "?") for e in c.get("evidence", [])})
        a(f'<tr><td>{esc(c["capability"])}</td><td><code>{esc(c["id"])}</code></td>'
          f'<td>{"".join(f"<span class=tag>{esc(k)}</span>" for k in kinds)}'
          f'<span class="cnt">×{len(c.get("evidence", []))}</span></td></tr>')
    a("</tbody></table></section>")

    # ── 3 不宣称（红字，账面上的冲销） ──────────────────────────────────
    a(f'<section id="not-claimable"><h2>{T("nc_h2")}</h2>')
    a(f'<p class="muted">{T("nc_note")}</p>')
    a(f'<table><thead><tr><th scope="col">{T("th_capability")}</th>'
      f'<th scope="col">{T("th_scope")}</th></tr></thead><tbody>')
    for c in not_claimable:
        # 否定词必须落在同一句内：claim_gate 按句判否定语境，标题里的「不宣称」
        # 不算，所以每行首写前缀（中文「不宣称：」/ 英文 "Not claimed: "）。
        a(f'<tr><td><span class="st no">{T("nc_prefix")}</span>{esc(c["capability"])}</td>'
          f'<td class="muted">{esc(c.get("reason", ""))}</td></tr>')
    a("</tbody></table></section>")

    # ── 4 MCP 工具面 ────────────────────────────────────────────────────
    a(f'<section id="tools"><h2>{T("tools_h2", n=len(ann))}</h2>')
    for g in groups:
        a(f'<h3>{esc(g["group"])}</h3>')
        a(f'<table><thead><tr><th scope="col">{T("th_tool")}</th>'
          f'<th scope="col">{T("th_rw")}</th>'
          f'<th scope="col">{T("th_behavior")}</th></tr></thead><tbody>')
        for tool in g["tools"]:
            meta = ann.get(tool, {})
            rw = T("rw_read") if meta.get("readOnlyHint") else T("rw_write")
            cls_ = "r" if meta.get("readOnlyHint") else "w"
            a(f'<tr><td><code>{esc(tool)}</code></td>'
              f'<td class="rw {cls_}">{rw}</td>'
              f'<td class="muted">{esc(meta.get("behavior", ""))}</td></tr>')
        a("</tbody></table>")
    a("</section>")

    # ── 5 REST 接口面 ───────────────────────────────────────────────────
    a(f'<section id="routes"><h2>'
      f'{T("routes_h2", business=rs["business"], ph=rs["placeholder"])}</h2>')
    a(f'<table><thead><tr><th scope="col">{T("th_face")}</th>'
      f'<th scope="col" class="num">{T("th_route_count")}</th>'
      f'<th scope="col">{T("th_state")}</th></tr></thead><tbody>')
    for face, n in rs["by_face"].items():
        ph = rs["ph_by_face"].get(face, 0)
        st = (f'<span class="st no">{T("st_ph", n=ph)}</span>' if ph
              else f'<span class="st ok">{T("st_ok")}</span>')
        a(f'<tr><td><code>{esc(face)}</code></td><td class="num">{n}</td><td>{st}</td></tr>')
    a("</tbody></table>")
    a(f'<p class="muted">{T("routes_note")}</p></section>')

    # ── 6 行业模板 ──────────────────────────────────────────────────────
    a(f'<section id="templates"><h2>{T("tpl_h2")}</h2>')
    a(f'<table><thead><tr><th scope="col">{T("th_industry")}</th>'
      f'<th scope="col">{T("th_assets")}</th>'
      f'<th scope="col">{T("th_shelf")}</th></tr></thead><tbody>')
    for key, tp in d["templates"].items():
        assets = tp.get("assets", {})
        parts = "".join(f"<span class=tag>{esc(k)}</span>" for k in assets)
        rec = packs.get(f"{key}/connector-pack", {})
        if rec.get("published"):
            # 措辞对齐 claims.json 里 market.connector-packs 的已登记 pattern
            # （「已上架：市场 vN」/ "Published: marketplace vN"）——否则声明闸会把
            # 本页判成未登记声明。
            status = f'<span class="st ok">{T("shelf_ok", n=rec.get("market_version"))}</span>'
        else:
            status = f'<span class="st no">{T("shelf_no")}</span>'
        a(f'<tr><td>{esc(tp["name_zh"])} <span class="muted">v{esc(tp["version"])}</span></td>'
          f"<td>{parts}</td><td>{status}</td></tr>")
    a("</tbody></table></section>")

    # ── 7 全覆盖（21 格四态）──────────────────────────────────────────────
    total = max(len(cells), 1)
    a(f'<section id="matrix"><h2>{T("matrix_h2", n=len(cells))}</h2>')
    a('<div class="matrix">')
    a('<div class="bar" role="img" aria-label="'
      + esc(T("matrix_aria", parts=", ".join(
          f"{state_labels[k]} {by_state.get(k, 0)}" for k in COVERAGE_STATE_ORDER))) + '">')
    for i, k in enumerate(COVERAGE_STATE_ORDER, start=1):
        pct = 100.0 * by_state.get(k, 0) / total
        if pct > 0:
            a(f'<span class="s{i}" style="width:{pct:.3f}%"></span>')
    a("</div>")
    a('<ul class="legend">')
    for i, k in enumerate(COVERAGE_STATE_ORDER, start=1):
        a(f'<li><i class="s{i}"></i>{state_labels[k]} <b>{by_state.get(k, 0)}</b></li>')
    a("</ul></div>")
    a(f'<table><thead><tr><th scope="col">{T("th_module")}</th>'
      f'<th scope="col">{T("th_state2")}</th>'
      f'<th scope="col">{T("th_boundary")}</th></tr></thead><tbody>')
    for cell in cells:
        note = esc(cell["boundary"])
        if cell["state"] == "needs_onboarding":
            note += ('<br><span class="muted">'
                     + esc(T("cell_blk", blocker=cell.get("blocker", ""))) + "</span>")
        elif cell["state"] == "not_doing":
            note += ('<br><span class="muted">'
                     + esc(T("cell_reason", reason=cell.get("reason", ""),
                             review=cell.get("review_by", ""))) + "</span>")
        a(f'<tr><td>{esc(cell["name_zh"])}</td>'
          f'<td><code>{esc(cell["state"])}</code><br>'
          f'<span class="muted">{state_labels[cell["state"]]}</span></td>'
          f'<td class="muted">{note}</td></tr>')
    a("</tbody></table>")
    a(f'<p class="muted">{T("matrix_note")}</p>')
    a(f'<p class="muted">'
      f'{esc(T("matrix_note2", vertical=d["matrix"]["vertical"], n=len(points)))}</p></section>')

    # ── 8 缺口 ──────────────────────────────────────────────────────────
    a(f'<section id="gaps"><h2>{T("gaps_h2", n=len(gaps))}</h2>')
    a(f'<table><thead><tr><th scope="col">{T("th_gap")}</th>'
      f'<th scope="col">{T("th_capability")}</th>'
      f'<th scope="col">{T("th_responsible")}</th>'
      f'<th scope="col">{T("th_status")}</th></tr></thead><tbody>')
    for g in gaps:
        st = (f'<span class="st no">{esc(g["status"])}</span>' if g["status"] == "open"
              else f'<span class="st ok">{esc(g["status"])}</span>')
        a(f'<tr><td><code>{esc(g["id"])}</code></td><td>{esc(g["capability"])}</td>'
          f'<td><code>{esc(g["responsible_repo"])}</code></td><td>{st}</td></tr>')
    a("</tbody></table></section>")

    # ── 9 边界 ──────────────────────────────────────────────────────────
    a(f'<section id="edges"><h2>{T("edges_h2")}</h2><dl class="edges">')
    for n in (1, 2, 3, 4):
        a(f'<div><dt>{T(f"edge{n}_dt")}</dt><dd>{T(f"edge{n}_dd")}</dd></div>')
    a("</dl></section>")

    # ── 页脚：出处清单（脚注落点）+ 术语表 ──────────────────────────────
    a(f'<footer id="src"><h2>{T("src_h2")}</h2><ul>')
    for rel in ("claims/claims.json", "gaps.json", "publish-record.json",
                "tool-surface.json", "coverage/", "templates/*/manifest.json"):
        a(f"<li>{esc(rel)}</li>")
    a("</ul>")
    a(f'<h2>{T("glossary_h2")}</h2><dl class="glossary">')
    for zh, en in TERMINOLOGY:
        a(f"<div><dt>{esc(zh)}</dt><dd>{esc(en)}</dd></div>")
    a("</dl>")
    a(f'<p class="say">{esc(T("say", date=date.today().isoformat()))}</p>')
    a("</footer>")
    a("</main></body></html>")
    return "\n".join(o)


LOCK = FD_ERP / "shared" / "artifact-lock.json"


def _lock_payload(targets: dict) -> dict:
    """生成物指纹：CI 里看不到兄弟仓，仍能识别「有人手改了生成物」。"""
    import hashlib

    return {
        "schema": "erp-artifact-lock/v1",
        "note": "生成物指纹。gen_erp_docs.py 写入，check_all.py 校验；手改生成物会在这里露馅。",
        "artifacts": {
            str(p.relative_to(FD_ERP)): hashlib.sha256(text.encode("utf-8")).hexdigest()
            for p, text in sorted(targets.items())
        },
    }


#: 出处文件 11 个路径里有 7 个在**兄弟仓**（`fd-erp-vertical-templates` /
#: `fd-erp-ledger-mcp`）。CI 只 checkout 本仓 ⇒ 那 7 个必然不在，`load()` 会
#: `SystemExit("缺少出处文件")`，`check_all.py` 把它记 FAIL —— 于是这段只能被放进
#: `if not args.ci`，而它在 CI 里就**一次都没跑过**（判据齐全、调用方缺失）。
#: 退出码按 `check_all.py` 对跨仓闸的既有约定分三档：0 一致 / 1 漂移 / **2 判不出**。
def _missing_sources() -> list[str]:
    m = load("fd-erp/manifest.json")
    src = m["sources"]
    want = [src["claims"], src["gaps"], src["publish_record"], src["tool_surface"],
            src["evidence"], f"{src['matrices']}/supply-chain.json",
            src["kernel_client_contract"]]
    want += [f"{src['templates']}/{v}/manifest.json" for v in (m.get("templates") or {})]
    return [rel for rel in want if not (ROOT / rel).is_file()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比对不落盘")
    args = ap.parse_args()

    missing = _missing_sources()
    if missing:
        print("判不出：出处文件不全（本仓看不到兄弟仓，CI 单仓形态如此）——")
        for rel in missing:
            print("  -", rel)
        print("这不是「一致」；完整判定要在工作区里跑：python3 fd-erp/tools/check_all.py")
        return 2

    d = collect()

    # 两语言**键集必须同构**（任务 4.2「文案键与中文同构」的机器可读形式）。
    # 为什么这条要单独判：少一个键不会报错——`render_site` 只会在跑到那一节时
    # KeyError，而英文页少一整节（比如少「明确不宣称」）是**对外材料缺一节**，
    # 肉眼扫一遍页面看不出来。这里在渲染之前先把它判掉。
    zh_keys, en_keys = LANG_KEYS["zh"], LANG_KEYS["en"]
    if zh_keys != en_keys:
        print("文案键不同构（英文版会缺节或印错，先修 fd-erp/tools/site_i18n.py）：")
        for k in sorted(zh_keys - en_keys):
            print(f"  - 只有中文：{k}")
        for k in sorted(en_keys - zh_keys):
            print(f"  - 只有英文：{k}")
        return 1

    readme = render_readme(d)
    targets = {
        FD_ERP / "README.md": readme,
        FD_ERP / "site" / "index.html": render_site(d, "zh"),
        FD_ERP / "site" / "en" / "index.html": render_site(d, "en"),
    }

    if args.check:
        drift = [
            str(p.relative_to(ROOT))
            for p, want in targets.items()
            if (not p.is_file()) or p.read_text(encoding="utf-8") != want
        ]
        if drift:
            print("派生文档已漂移，请重跑 gen_erp_docs.py：")
            for x in drift:
                print("  -", x)
            return 1
        print("派生文档与出处一致。")
        return 0

    for p, text in targets.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        print(f"写入 {p.relative_to(ROOT)}")
    LOCK.write_text(json.dumps(_lock_payload(targets), ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    print(f"写入 {LOCK.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
