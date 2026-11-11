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
        "config": _gate("check_config_contract.py"),
        "logs": _gate("check_log_redaction.py"),
        "log_contract": load("fd-erp/shared/log-contract.json"),
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
    if site:
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
th{font-weight:600;font-size:.82rem;color:var(--ink-2);border-bottom:1px solid var(--rule-3)}
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
.st{font:600 11.5px/1 var(--sans);letter-spacing:.04em}
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
    a('<a class="skip" href="#main">跳到正文</a>')

    # 报头：账簿的页眉，不是标题上方的眉标
    a('<header class="masthead"><div class="sheet">')
    a('<span class="brand">FindData</span>')
    a(f'<span class="doc">{esc(b["name"])} · 能力与集成说明</span>')
    a(f'<span class="stamp">{date.today().isoformat()}</span>')
    a("</div></header>")

    a('<main id="main" class="sheet">')

    # ── 首屏：定位 + 试算表 + 入口 ───────────────────────────────────────
    a('<div class="hero">')
    a(f'<h1>{esc(b["name"])} {esc(b["tag_zh"])}<span class="sub">能力、接口与边界</span></h1>')
    a('<div class="rule-double"></div>')
    a('<span class="mark" aria-hidden="true"><span>数据派生</span><span>勿手改</span></span>')
    a('<p class="lede">ERP 是「集群 + 供给包」的组合式交付：一个行业无关的复式事件账内核，'
      "加行业模板资产（连接器 pack、舰队蓝图、科目映射、报表 preset），"
      "经同源入口对外提供 REST 面与 MCP 工具面。它不是单体 ERP 应用，也不提供表单式 UI。</p>")
    a('<p class="basis">本页所有数字均由 <code>claims.json</code> / <code>gaps.json</code> / '
      "<code>tool-surface.json</code> / <code>coverage/</code> / 模板 manifest 在构建时派生，"
      "与 <code>claim_gate</code> 同源；不写价格、客户数、用量或上线日期。</p>")

    a('<table class="tb"><caption>本页口径</caption>')
    a('<thead><tr><th scope="col">项目</th><th scope="col" class="num">数量</th>'
      '<th scope="col">出处</th></tr></thead><tbody>')
    a('<tr><td>MCP 工具</td>'
      f'<td class="num big">{len(ann)}<sup><a class="fn" href="#src" data-src="tool-surface.json">1</a></sup></td>'
      '<td class="prov">tool-surface.json</td></tr>')
    a('<tr><td>业务路由</td>'
      f'<td class="num big">{rs["business"]}<sup><a class="fn" href="#src" data-src="coverage/">2</a></sup></td>'
      f'<td class="prov">coverage/ <span class="dim">（另有 {rs["health"]} 条健康探针；'
      f'其中 {rs["placeholder"]} 条未实施）</span></td></tr>')
    a('<tr><td>行业模板</td>'
      f'<td class="num big">{len(d["templates"])}<sup><a class="fn" href="#src" '
      'data-src="templates/*/manifest.json">3</a></sup></td>'
      '<td class="prov">templates/*/manifest.json</td></tr>')
    a('<tr><td>可宣称能力</td>'
      f'<td class="num big">{len(delivered)}<sup><a class="fn" href="#src" data-src="claims.json">4</a></sup></td>'
      '<td class="prov">claims.json</td></tr>')
    a('<tr><td>明确不宣称</td>'
      f'<td class="num big">{len(not_claimable)}<sup><a class="fn" href="#src" data-src="claims.json">5</a></sup></td>'
      '<td class="prov">claims.json</td></tr>')
    a("</tbody></table>")

    a('<nav class="acts" aria-label="页内入口">')
    a('<a href="#capability">看能力面</a>')
    a('<a href="#routes">看接口面</a>')
    a('<a class="ghost" href="#src">核验出处</a>')
    a('<a class="ghost" href="https://www.finddatatech.cloud/" rel="noopener">寻数官网 ↗</a>')
    a("</nav>")
    a("</div>")

    # ── 科目索引 ────────────────────────────────────────────────────────
    a('<nav class="index" aria-label="科目索引"><h2>科目索引</h2><ol>')
    for anchor, label, hint in (
        ("form", "形态", "四层"),
        ("capability", "能力面", f"{len(delivered)} 条"),
        ("not-claimable", "明确不宣称", f"{len(not_claimable)} 条"),
        ("tools", "MCP 工具面", f"{len(ann)} 个"),
        ("routes", "REST 接口面", f"{rs['business']} 条"),
        ("templates", "行业模板", f"{len(d['templates'])} 套"),
        ("matrix", "功能覆盖矩阵", f"{len(points)} 点"),
        ("gaps", "连接器缺口", f"{len(gaps)} 条"),
        ("edges", "边界", "四项"),
    ):
        a(f'<li><a href="#{anchor}"><span class="k">{label}</span>'
          f'<span class="v">{esc(hint)}</span></a></li>')
    a("</ol></nav>")

    # ── 1 形态 ──────────────────────────────────────────────────────────
    a('<section id="form"><h2>形态：四层，各自独立升级</h2>')
    a('<ul class="stack">'
      '<li><span class="layer">客户端<em>壹座 miniapp 四端</em></span>'
      '<span class="what">UE / SE / SP / CP 四端页面集</span>'
      '<span class="hop">/erp/supply-chain/v1/*　同源入口，剥掉客户端自带的 X-ERP-*</span></li>'
      '<li><span class="layer">平台网关<em>platform gateway</em></span>'
      '<span class="what">按会话 + 绑定记录重注入身份；无会话 401，未绑角色不注入</span></li>'
      '<li><span class="layer">纵向 REST 服务面<em>vertical api</em></span>'
      f'<span class="what">{rs["business"]} 路由；单副本；闸序 租户 → 页面集 → grant → 身份域</span>'
      '<span class="hop">全程走内核工具面，不直连库表</span></li>'
      '<li><span class="layer">行业模板层<em>vertical templates</em></span>'
      '<span class="what">跨境 / 餐饮 / 仓配；四件套 + 定价 + 页面集；边界由 AST 审计</span>'
      '<span class="hop">仅 proposal，不直写</span></li>'
      '<li><span class="layer">账本内核<em>fact ledger kernel</em></span>'
      '<span class="what">复式事件账；确认门是唯一落账路径；借贷必平由 DB 约束强制</span></li>'
      "</ul>")
    a('<table><caption>仓构成</caption><thead><tr><th scope="col">角色</th><th scope="col">仓</th>'
      '<th scope="col">面</th><th scope="col" class="num">源码行</th>'
      '<th scope="col" class="num">测试行</th></tr></thead><tbody>')
    for r in m["repos"]:
        a(f'<tr><td>{esc(r["role"])}</td><td><code>{esc(r["path"])}</code></td>'
          f'<td class="muted">{esc(r["surface"])}</td>'
          f'<td class="num">{r["src_loc"]}</td><td class="num">{r["tests_loc"]}</td></tr>')
    a("</tbody></table></section>")

    # ── 2 能力面 ────────────────────────────────────────────────────────
    a('<section id="capability"><h2>能力面（可宣称，逐条带证据）</h2>')
    a('<table><thead><tr><th scope="col">能力</th><th scope="col">标识</th>'
      '<th scope="col">证据</th></tr></thead><tbody>')
    for c in delivered:
        kinds = sorted({e.get("kind", "?") for e in c.get("evidence", [])})
        a(f'<tr><td>{esc(c["capability"])}</td><td><code>{esc(c["id"])}</code></td>'
          f'<td>{"".join(f"<span class=tag>{esc(k)}</span>" for k in kinds)}'
          f'<span class="cnt">×{len(c.get("evidence", []))}</span></td></tr>')
    a("</tbody></table></section>")

    # ── 3 不宣称（红字，账面上的冲销） ──────────────────────────────────
    a('<section id="not-claimable"><h2>明确不宣称（对外如实守界）</h2>')
    a('<p class="muted">以下条目以否定口径出现在本页与官网；任何肯定句式都会被 '
      "<code>claim_gate.py</code> 判红。</p>")
    a('<table><thead><tr><th scope="col">能力</th><th scope="col">口径</th></tr></thead><tbody>')
    for c in not_claimable:
        # 否定词必须落在同一句内：claim_gate 按句判否定语境，标题里的「不宣称」
        # 不算，所以每行首字写「不宣称：」。
        a(f'<tr><td><span class="st no">不宣称：</span>{esc(c["capability"])}</td>'
          f'<td class="muted">{esc(c.get("reason", ""))}</td></tr>')
    a("</tbody></table></section>")

    # ── 4 MCP 工具面 ────────────────────────────────────────────────────
    a(f'<section id="tools"><h2>MCP 工具面（{len(ann)} 个）</h2>')
    for g in groups:
        a(f'<h3>{esc(g["group"])}</h3>')
        a('<table><thead><tr><th scope="col">工具</th><th scope="col">读 / 写</th>'
          '<th scope="col">行为</th></tr></thead><tbody>')
        for t in g["tools"]:
            meta = ann.get(t, {})
            rw = "读" if meta.get("readOnlyHint") else "写"
            cls_ = "r" if rw == "读" else "w"
            a(f'<tr><td><code>{esc(t)}</code></td>'
              f'<td class="rw {cls_}">{rw}</td>'
              f'<td class="muted">{esc(meta.get("behavior", ""))}</td></tr>')
        a("</tbody></table>")
    a("</section>")

    # ── 5 REST 接口面 ───────────────────────────────────────────────────
    a(f'<section id="routes"><h2>REST 接口面（{rs["business"]} 条业务路由，'
      f'{rs["placeholder"]} 条未实施）</h2>')
    a('<table><thead><tr><th scope="col">面</th><th scope="col" class="num">路由数</th>'
      '<th scope="col">实施状态</th></tr></thead><tbody>')
    for face, n in rs["by_face"].items():
        ph = rs["ph_by_face"].get(face, 0)
        st = (f'<span class="st no">{ph} 未实施</span>' if ph
              else '<span class="st ok">已实施</span>')
        a(f'<tr><td><code>{esc(face)}</code></td><td class="num">{n}</td><td>{st}</td></tr>')
    a("</tbody></table>")
    a('<p class="muted">未实施端点按契约返回 <code>501 NOT_IMPLEMENTED</code> 并附计划车道，'
      "承载层不改写、不吞掉、不伪装成占位表单。</p></section>")

    # ── 6 行业模板 ──────────────────────────────────────────────────────
    a('<section id="templates"><h2>行业模板（差异全部上移至此）</h2>')
    a('<table><thead><tr><th scope="col">行业</th><th scope="col">模板资产</th>'
      '<th scope="col">上架状态</th></tr></thead><tbody>')
    for key, t in d["templates"].items():
        assets = t.get("assets", {})
        parts = "".join(f"<span class=tag>{esc(k)}</span>" for k in assets)
        rec = packs.get(f"{key}/connector-pack", {})
        if rec.get("published"):
            # 措辞对齐 claims.json 里 market.connector-packs 的已登记 pattern
            # （「已上架：市场 vN」）——否则声明闸会把本页判成未登记声明。
            status = f'<span class="st ok">已上架：市场 v{rec.get("market_version")}</span>'
        else:
            status = '<span class="st no">未上架</span>'
        a(f'<tr><td>{esc(t["name_zh"])} <span class="muted">v{esc(t["version"])}</span></td>'
          f"<td>{parts}</td><td>{status}</td></tr>")
    a("</tbody></table></section>")

    # ── 7 覆盖矩阵 ──────────────────────────────────────────────────────
    total = max(len(points), 1)
    order = ("直接命中", "模式复用", "新建", "不做")
    a(f'<section id="matrix"><h2>功能覆盖矩阵（{esc(d["matrix"]["vertical"])}，'
      f'{len(points)} 个功能点）</h2>')
    a('<div class="matrix">')
    a('<div class="bar" role="img" aria-label="' +
      "、".join(f"{k} {cls.get(k, 0)} 个" for k in order) + '">')
    for i, k in enumerate(order, start=1):
        pct = 100.0 * cls.get(k, 0) / total
        if pct > 0:
            a(f'<span class="s{i}" style="width:{pct:.3f}%"></span>')
    a("</div>")
    a('<ul class="legend">')
    for i, k in enumerate(order, start=1):
        a(f'<li><i class="s{i}"></i>{k} <b>{cls.get(k, 0)}</b></li>')
    a("</ul></div>")
    a('<p class="muted">矩阵由客户功能清单导入后重算生成（幂等），每个功能点带至少一条实现证据；'
      "清单本体不进规格与模板资产，只以脱敏编号引用。</p></section>")

    # ── 8 缺口 ──────────────────────────────────────────────────────────
    a(f'<section id="gaps"><h2>连接器缺口（{len(gaps)} 条，每项带机器判据）</h2>')
    a('<table><thead><tr><th scope="col">缺口</th><th scope="col">能力</th>'
      '<th scope="col">责任仓</th><th scope="col">状态</th></tr></thead><tbody>')
    for g in gaps:
        st = ('<span class="st no">open</span>' if g["status"] == "open"
              else f'<span class="st ok">{esc(g["status"])}</span>')
        a(f'<tr><td><code>{esc(g["id"])}</code></td><td>{esc(g["capability"])}</td>'
          f'<td><code>{esc(g["responsible_repo"])}</code></td><td>{st}</td></tr>')
    a("</tbody></table></section>")

    # ── 9 边界 ──────────────────────────────────────────────────────────
    a('<section id="edges"><h2>边界</h2><dl class="edges">')
    a("<div><dt>资金（二清红线）</dt><dd>只产出对账结果与核对指令。"
      "不提供资金池、代收代付、分账执行；资金归集与分账走客户自选的持牌通道。</dd></div>")
    a("<div><dt>开票 / 税务</dt><dd>不自研、当前不提供（挂账）。"
      "账内可记录发票类事件并参与对账；票据本体走客户既有合规渠道，不伪造、不代开。</dd></div>")
    a("<div><dt>执行面</dt><dd>发货、支付、补货、开票等经营动作仅经采纳的外部 MCP server 完成；"
      "凭证由租户自带（BYOK）、经环境变量注入，零落库零日志。</dd></div>")
    a("<div><dt>租户隔离</dt><dd>同时服务寻数自用与外部商家/泛企业客户；"
      "经营数据按租户隔离，任一客户租户不能读取其他租户的账、单据或报表。</dd></div>")
    a("</dl></section>")

    # ── 页脚：出处清单（脚注落点） ──────────────────────────────────────
    a('<footer id="src"><h2>出处</h2><ul>')
    for rel in ("claims/claims.json", "gaps.json", "publish-record.json",
                "tool-surface.json", "coverage/", "templates/*/manifest.json"):
        a(f"<li>{esc(rel)}</li>")
    a("</ul>")
    a(f'<p class="say">本页由 <code>fd-erp/tools/gen_erp_docs.py</code> 于 '
      f"{date.today().isoformat()} 生成。数据出处：<code>claims/claims.json</code>、"
      "<code>gaps.json</code>、<code>publish-record.json</code>、"
      "<code>tool-surface.json</code>、<code>coverage/</code>、<code>templates/*/manifest.json</code>。"
      "本页不声称任何未在 <code>publish-record.json</code> 中记为 live 的状态。</p>")
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
    LOCK.write_text(json.dumps(_lock_payload(targets), ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    print(f"写入 {LOCK.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
