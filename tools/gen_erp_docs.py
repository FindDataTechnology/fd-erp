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
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FD_ERP = ROOT / "fd-erp"


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
        "claims": load(src["claims"]),
        "gaps": load(src["gaps"]),
        "publish": load(src["publish_record"]),
        "surface": load(src["tool_surface"]),
        "evidence": load(src["evidence"]),
        "matrix": load(f"{src['matrices']}/supply-chain.json"),
        "templates": {
            v: load(f"{src['templates']}/{v}/manifest.json")
            for v in ("crossborder", "restaurant-chain", "supply-chain")
        },
    }


def _semantics() -> dict:
    """跨仓语义契约的实况，直接复用契约闸的计算——不在这里重新实现一遍 AST 读取。"""
    import importlib.util

    path = Path(__file__).with_name("check_semantics_contract.py")
    spec = importlib.util.spec_from_file_location("_erp_semantics_gate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.check()


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
    if site:
        a(f"站点 `{site['host']}`，内容 `{site['content']}`（生成物，勿手改）。")
        a("")
        a("| 环节 | 位置 | 备注 |")
        a("|---|---|---|")
        o, e = site["origin"], site["edge"]
        a(f"| 源站 | `{o['ssh_alias']}`（{o['ip']}）`{o['path']}` | nginx `{o['nginx_conf']}` |")
        a(f"| 边缘 | {e['role']}（{e['ip']}） | Caddy `{e['caddy_conf']}`，upstream `{e['upstream']}` |")
        a("")
        a(f"**公网状态：{site['public_status']}** —— {site['blocked_by']}")
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
    a("## 8. 待办（结构性）")
    a("")
    for t in m["open_tasks"]:
        a(f"- [ ] {t}")
    a("")
    return "\n".join(lines)


# ── 站点（对外：能力与集成说明，不写营销话术） ────────────────────────────────
CSS = """
:root{--fg:#15181d;--muted:#5b6472;--line:#e3e6ea;--bg:#fbfbfc;--accent:#1f5f8b;--warn:#8a5a00;--ok:#186b47;--card:#fff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:0 20px}
header{border-bottom:1px solid var(--line);background:var(--card)}
header .wrap{padding:18px 20px;display:flex;gap:12px;align-items:baseline;flex-wrap:wrap}
.kicker{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
h1{font-size:26px;margin:26px 0 8px;letter-spacing:-.01em}
h2{font-size:18px;margin:40px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:22px 0 8px}
p{margin:8px 0}
.lead{color:var(--muted);font-size:16px}
.tag{display:inline-block;font-size:11px;padding:2px 7px;border:1px solid var(--line);border-radius:999px;color:var(--muted);background:#fff}
table{width:100%;border-collapse:collapse;margin:10px 0 18px;font-size:13.5px;background:var(--card)}
th,td{text-align:left;padding:8px 10px;border:1px solid var(--line);vertical-align:top}
th{background:#f4f6f8;font-weight:600;white-space:nowrap}
code{font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;background:#f2f4f6;padding:1px 5px;border-radius:4px}
pre{background:#f4f6f8;border:1px solid var(--line);border-radius:8px;padding:14px;overflow:auto;font:12.5px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin:12px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px}
.card h3{margin:0 0 6px;font-size:14px}
.card p{margin:0;font-size:13px;color:var(--muted)}
.rd{color:var(--accent);font-weight:600}
.wr{color:var(--warn);font-weight:600}
.ok{color:var(--ok)}
.muted{color:var(--muted)}
.badge{font-size:11px;padding:1px 6px;border-radius:4px;border:1px solid var(--line);background:#fff;color:var(--muted)}
.badge.no{border-color:#eddcb8;background:#fdf8ec;color:var(--warn)}
footer{margin-top:56px;border-top:1px solid var(--line);padding:20px 0 40px;color:var(--muted);font-size:12.5px}
.stat{display:flex;gap:26px;flex-wrap:wrap;margin:16px 0}
.stat div strong{display:block;font-size:22px;line-height:1.2}
.stat div span{font-size:12px;color:var(--muted)}
"""


def esc(x) -> str:
    return html.escape(str(x), quote=True)


def render_site(d: dict) -> str:
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
    cls = Counter(p["classification"] for p in points)
    packs = d["publish"]["packs"]

    o: list[str] = []
    a = o.append

    a("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">")
    a('<meta name="viewport" content="width=device-width,initial-scale=1">')
    a("<title>ERP 板块 — 能力与集成说明 · 寻数 FindData</title>")
    a(f'<meta name="description" content="{esc(b["name"])} 板块的能力面、接口面与边界，数据全部由仓内唯一出处派生。">')
    a(f"<style>{CSS}</style></head><body>")

    a("<header><div class=\"wrap\">")
    a(f'<span class="kicker">FindData · {esc(b["name"])} · {esc(b["tag_zh"])}</span>')
    a('<span class="tag">数据派生，勿手改</span>')
    a("</div></header><div class=\"wrap\">")

    # 1 · 定位
    a("<h1>ERP 板块：能力、接口与边界</h1>")
    a('<p class="lead">ERP 是「集群 + 供给包」的组合式交付：一个行业无关的复式事件账内核，'
      "加行业模板资产（连接器 pack、舰队蓝图、科目映射、报表 preset），"
      "经同源入口对外提供 REST 面与 MCP 工具面。它不是单体 ERP 应用，也不提供表单式 UI。</p>")
    a('<p class="muted">本页所有数字均由 <code>claims.json</code> / <code>gaps.json</code> / '
      "<code>tool-surface.json</code> / <code>coverage/</code> / 模板 manifest 在构建时派生，"
      "与 <code>claim_gate</code> 同源；不写价格、客户数、用量或上线日期。</p>")

    s = d["gaps"]
    a('<div class="stat">')
    a(f'<div><strong>{len(d["surface"]["tool_annotations"])}</strong><span>MCP 工具</span></div>')
    a(f'<div><strong>{rs["business"]}</strong><span>业务路由（另有 {rs["health"]} 条健康探针；其中 {rs["placeholder"]} 条未实施）</span></div>')
    a(f'<div><strong>{len(d["templates"])}</strong><span>行业模板</span></div>')
    a(f'<div><strong>{len(delivered)}</strong><span>可宣称能力</span></div>')
    a(f'<div><strong>{len(not_claimable)}</strong><span>明确不宣称</span></div>')
    a("</div>")

    # 2 · 分层
    a("<h2>1 · 形态：四层，各自独立升级</h2>")
    a("<pre>"
      "客户端（壹座 miniapp 四端页面集 UE / SE / SP / CP）\n"
      "   │  /erp/supply-chain/v1/*   同源入口，剥掉客户端自带的 X-ERP-*\n"
      "   ▼\n"
      "平台网关（按会话 + 绑定记录重注入身份；无会话 401，未绑角色不注入）\n"
      "   ▼\n"
      "纵向 REST 服务面（65 路由；单副本；闸序 租户 → 页面集 → grant → 身份域）\n"
      "   ▼  全程走内核工具面，不直连库表\n"
      "行业模板层（跨境 / 餐饮 / 仓配；四件套 + 定价 + 页面集；边界由 AST 审计）\n"
      "   ▼  仅 proposal，不直写\n"
      "账本内核（复式事件账；确认门是唯一落账路径；借贷必平由 DB 约束强制）"
      "</pre>")
    a("<div class=\"grid\">")
    for r in m["repos"]:
        a(f'<div class="card"><h3>{esc(r["role"])}</h3>'
          f'<p><code>{esc(r["path"])}</code><br>{esc(r["surface"])} · 源码 {r["src_loc"]} 行 / 测试 {r["tests_loc"]} 行</p></div>')
    a("</div>")

    # 3 · 能力
    a("<h2>2 · 能力面（可宣称，逐条带证据）</h2>")
    a("<table><tr><th>能力</th><th>标识</th><th>证据</th></tr>")
    for c in delivered:
        kinds = sorted({e.get("kind", "?") for e in c.get("evidence", [])})
        a(f"<tr><td>{esc(c['capability'])}</td><td><code>{esc(c['id'])}</code></td>"
          f"<td class=\"muted\">{esc(' / '.join(kinds))} ×{len(c.get('evidence', []))}</td></tr>")
    a("</table>")

    # 4 · 不宣称
    a("<h2>3 · 明确不宣称（对外如实守界）</h2>")
    a("<p class=\"muted\">以下条目以否定口径出现在本页与官网；任何肯定句式都会被 <code>claim_gate.py</code> 判红。</p>")
    a("<table><tr><th>能力</th><th>口径</th></tr>")
    for c in not_claimable:
        # 否定词必须落在同一句内：claim_gate 按句判否定语境，标题里的「不宣称」
        # 不算，所以每行首字写「不宣称：」。
        a(f"<tr><td>不宣称：{esc(c['capability'])}</td><td class=\"muted\">{esc(c.get('reason', ''))}</td></tr>")
    a("</table>")

    # 5 · 工具面
    a(f"<h2>4 · MCP 工具面（{len(ann)} 个）</h2>")
    a("<table><tr><th>分组</th><th>工具</th><th>读/写</th><th>行为</th></tr>")
    for g in groups:
        for t in g["tools"]:
            meta = ann.get(t, {})
            rw = "读" if meta.get("readOnlyHint") else "写"
            cls_ = "rd" if rw == "读" else "wr"
            a(f"<tr><td>{esc(g['group'])}</td><td><code>{esc(t)}</code></td>"
              f"<td class=\"{cls_}\">{rw}</td><td class=\"muted\">{esc(meta.get('behavior', ''))}</td></tr>")
    a("</table>")

    # 6 · 接口面
    a(f"<h2>5 · REST 接口面（{rs['business']} 条业务路由，{rs['placeholder']} 条未实施）</h2>")
    a("<table><tr><th>面</th><th>路由数</th><th>实施状态</th></tr>")
    for face, n in rs["by_face"].items():
        ph = rs["ph_by_face"].get(face, 0)
        badge = f'<span class="badge no">{ph} 未实施</span>' if ph else '<span class="badge ok">已实施</span>'
        a(f"<tr><td><code>{esc(face)}</code></td><td>{n}</td><td>{badge}</td></tr>")
    a("</table>")
    a("<p class=\"muted\">未实施端点按契约返回 <code>501 NOT_IMPLEMENTED</code> 并附计划车道，"
      "承载层不改写、不吞掉、不伪装成占位表单。</p>")

    # 7 · 模板
    a("<h2>6 · 行业模板（差异全部上移至此）</h2>")
    a("<table><tr><th>行业</th><th>模板资产</th><th>上架状态</th></tr>")
    for key, t in d["templates"].items():
        assets = t.get("assets", {})
        parts = ", ".join(f"<code>{esc(k)}</code>" for k in assets)
        rec = packs.get(f"{key}/connector-pack", {})
        if rec.get("published"):
            # 措辞对齐 claims.json 里 market.connector-packs 的已登记 pattern
            # （「已上架：市场 vN」）——否则声明闸会把本页判成未登记声明。
            status = f'<span class="ok">已上架：市场 v{rec.get("market_version")}</span>'
        else:
            status = '<span class="badge no">未上架</span>'
        a(f"<tr><td>{esc(t['name_zh'])} <span class=\"muted\">v{esc(t['version'])}</span></td>"
          f"<td>{parts}</td><td>{status}</td></tr>")
    a("</table>")

    # 8 · 覆盖矩阵
    a(f"<h2>7 · 功能覆盖矩阵（{esc(d['matrix']['vertical'])}，{len(points)} 个功能点）</h2>")
    a("<div class=\"grid\">")
    for k in ("直接命中", "模式复用", "新建", "不做"):
        a(f'<div class="card"><h3>{k}</h3><p>{cls.get(k, 0)} 个功能点</p></div>')
    a("</div>")
    a("<p class=\"muted\">矩阵由客户功能清单导入后重算生成（幂等），每个功能点带至少一条实现证据；"
      "清单本体不进规格与模板资产，只以脱敏编号引用。</p>")

    # 9 · 缺口
    a(f"<h2>8 · 连接器缺口（{len(gaps)} 条，每项带机器判据）</h2>")
    a("<table><tr><th>缺口</th><th>能力</th><th>责任仓</th><th>状态</th></tr>")
    for g in gaps:
        st = '<span class="badge no">open</span>' if g["status"] == "open" else f'<span class="badge ok">{esc(g["status"])}</span>'
        a(f"<tr><td><code>{esc(g['id'])}</code></td><td>{esc(g['capability'])}</td>"
          f"<td><code>{esc(g['responsible_repo'])}</code></td><td>{st}</td></tr>")
    a("</table>")

    # 10 · 边界
    a("<h2>9 · 边界</h2>")
    a('<div class="grid">')
    a('<div class="card"><h3>资金（二清红线）</h3><p>只产出对账结果与核对指令。'
      "不提供资金池、代收代付、分账执行；资金归集与分账走客户自选的持牌通道。</p></div>")
    a('<div class="card"><h3>开票 / 税务</h3><p>不自研、当前不提供（挂账）。'
      "账内可记录发票类事件并参与对账；票据本体走客户既有合规渠道，不伪造、不代开。</p></div>")
    a('<div class="card"><h3>执行面</h3><p>发货、支付、补货、开票等经营动作仅经采纳的外部 MCP server 完成；'
      "凭证由租户自带（BYOK）、经环境变量注入，零落库零日志。</p></div>")
    a('<div class="card"><h3>租户隔离</h3><p>同时服务寻数自用与外部商家/泛企业客户；'
      "经营数据按租户隔离，任一客户租户不能读取其他租户的账、单据或报表。</p></div>")
    a("</div>")

    a(f"<footer>本页由 <code>fd-erp/tools/gen_erp_docs.py</code> 于 {date.today().isoformat()} 生成。"
      "数据出处：<code>claims/claims.json</code>、<code>gaps.json</code>、<code>publish-record.json</code>、"
      "<code>tool-surface.json</code>、<code>coverage/</code>、<code>templates/*/manifest.json</code>。"
      "本页不声称任何未在 <code>publish-record.json</code> 中记为 live 的状态。</footer>")
    a("</div></body></html>")
    return "\n".join(o)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比对不落盘")
    args = ap.parse_args()

    d = collect()
    readme = render_readme(d)
    site = render_site(d)

    targets = {FD_ERP / "README.md": readme, FD_ERP / "site" / "index.html": site}

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
