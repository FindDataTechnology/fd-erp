"""ERP 介绍站的双语文案键（change establish-erp-independent-root 4.2）。

为什么单独一个模块、而不是把英文塞进 `gen_erp_docs.py`：
`render_site()` 是「结构 + 文案」混在一起的一段，把两种语言的文案都内联进去会把它变成
一篇没法评审的散文。这里只放**文案键与术语表**，渲染逻辑留在生成器里；两语言的键
**必须同构**（同一批 key，`--check` 会核），否则「英文版」会悄悄少一节而没人发现。

术语表（`TERMINOLOGY`）是这份文件的第二个职责：直译漂移比不翻译更糟——
`fact ledger kernel` 若一处写 ledger kernel、另一处写 accounting kernel，读者会以为是
两个东西。渲染时把术语表交给**人**看（写进页面页脚），不是自动替换：自动替换会把
`ledger.` 这样的 claim id 也一起换掉。

数据行（能力名、缺口、路由数、矩阵格）一律沿用机器产物原样，不在本文件翻译——
这是任务里那句「数据行沿用机器产物」的执行方式。
"""
from __future__ import annotations

#: 覆盖率四态的英文标签（中文那份在 gen_erp_docs.py，与 claim_gate.py 同源）。
COVERAGE_STATE_LABELS_EN = {
    "delivered": "Delivered",
    "template_configured": "Configurable via template",
    "needs_onboarding": "Needs one-time onboarding",
    "not_doing": "Explicitly out of scope",
}

#: 术语表：**先定**，两语言逐条对应。渲染进页脚，供读者对齐用词。
TERMINOLOGY = (
    ("事实账内核", "fact ledger kernel"),
    ("复式事件账", "double-entry event ledger"),
    ("确认门", "confirmation gate"),
    ("导入车道", "ingestion lane"),
    ("过账规则", "posting rules"),
    ("子模块全覆盖四态", "full-coverage four states"),
    ("明确不做", "explicitly out of scope"),
    ("需一次接入", "needs one-time onboarding"),
    ("模板可配", "configurable via template"),
    ("纵向 REST 服务面", "vertical REST surface"),
    ("行业模板层", "vertical template layer"),
    ("连接器缺口", "connector gap"),
    ("不可宣称", "not claimable"),
)

_Z = {
    # ── 文档头 ──
    "lang": "zh-CN",
    "alt_lang": "en",
    "alt_href": "en/index.html",
    "switch": "English",
    "title": "ERP 板块 — 能力与集成说明 · 寻数 FindData",
    "meta_desc": "{name} 板块的能力面、接口面与边界，数据全部由仓内唯一出处派生。",
    "skip": "跳到正文",
    "doc": "{name} · 能力与集成说明",
    "h1_sub": "能力、接口与边界",
    "mark_a": "数据派生",
    "mark_b": "勿手改",
    "lede": (
        "ERP 是「集群 + 供给包」的组合式交付：一个行业无关的复式事件账内核，"
        "加行业模板资产（连接器 pack、舰队蓝图、科目映射、报表 preset），"
        "经同源入口对外提供 REST 面与 MCP 工具面。它不是单体 ERP 应用，也不提供表单式 UI。"
    ),
    "basis": (
        "本页所有数字均由 claims.json / gaps.json / tool-surface.json / coverage/ / "
        "模板 manifest 在构建时派生，与 claim_gate 同源；不写价格、客户数、用量或上线日期。"
    ),
    # ── 口径表 ──
    "tb_caption": "本页口径",
    "th_item": "项目",
    "th_count": "数量",
    "th_prov": "出处",
    "row_tools": "MCP 工具",
    "row_routes": "业务路由",
    "row_routes_note": "（另有 {health} 条健康探针；其中 {ph} 条未实施）",
    "row_templates": "行业模板",
    "row_claimable": "可宣称能力",
    "row_not_claimable": "明确不宣称",
    # ── 页内导航 ──
    "act_capability": "看能力面",
    "act_routes": "看接口面",
    "act_src": "核验出处",
    "act_home": "寻数官网 ↗",
    "index_title": "科目索引",
    "idx_form": "形态",
    "idx_form_hint": "五层",
    "idx_capability": "能力面",
    "idx_not_claimable": "明确不宣称",
    "idx_tools": "MCP 工具面",
    "idx_routes": "REST 接口面",
    "idx_templates": "行业模板",
    "idx_matrix": "子模块全覆盖",
    "idx_matrix_hint": "{n} 格四态",
    "idx_gaps": "连接器缺口",
    "idx_edges": "边界",
    "idx_edges_hint": "四项",
    "n_items": "{n} 条",
    "n_units": "{n} 个",
    "n_sets": "{n} 套",
    # ── 1 形态 ──
    "form_h2": "形态：五层，各自独立升级",
    "layer1": "客户端",
    "layer1_em": "壹座 miniapp 四端",
    "layer1_what": "UE / SE / SP / CP 四端页面集",
    "layer1_hop": "/erp/supply-chain/v1/*　同源入口，剥掉客户端自带的 X-ERP-*",
    "layer2": "平台网关",
    "layer2_em": "platform gateway",
    "layer2_what": "按会话 + 绑定记录重注入身份；无会话 401，未绑角色不注入",
    "layer3": "纵向 REST 服务面",
    "layer3_em": "vertical api",
    "layer3_what": "{routes} 路由；单副本；闸序 租户 → 页面集 → grant → 身份域",
    "layer3_hop": "全程走内核工具面，不直连库表",
    "layer4": "行业模板层",
    "layer4_em": "vertical templates",
    "layer4_what": "跨境 / 餐饮 / 仓配；四件套 + 定价 + 页面集；边界由 AST 审计",
    "layer4_hop": "仅 proposal，不直写",
    "layer5": "账本内核",
    "layer5_em": "fact ledger kernel",
    "layer5_what": (
        "复式事件账；agent 拟稿经确认门才成为事实；外部系统事实经导入车道按来源权威直接"
        "成为事实；两者都按人工确认的过账规则派生分录，缺规则即挂待补、不猜科目；"
        "借贷必平由 DB 约束强制"
    ),
    "repo_caption": "仓构成",
    "th_role": "角色",
    "th_repo": "仓",
    "th_surface": "面",
    "th_src_loc": "源码行",
    "th_tests_loc": "测试行",
    # ── 2 能力面 ──
    "cap_h2": "能力面（可宣称，逐条带证据）",
    "th_capability": "能力",
    "th_id": "标识",
    "th_evidence": "证据",
    # ── 3 不宣称 ──
    "nc_h2": "明确不宣称（对外如实守界）",
    "nc_note": (
        "以下条目以否定口径出现在本页与官网；任何肯定句式都会被 claim_gate.py 判红。"
    ),
    "th_scope": "口径",
    "nc_prefix": "不宣称：",
    # ── 4 MCP 工具面 ──
    "tools_h2": "MCP 工具面（{n} 个）",
    "th_tool": "工具",
    "th_rw": "读 / 写",
    "th_behavior": "行为",
    "rw_read": "读",
    "rw_write": "写",
    # ── 5 REST 接口面 ──
    "routes_h2": "REST 接口面（{business} 条业务路由，{ph} 条未实施）",
    "th_face": "面",
    "th_route_count": "路由数",
    "th_state": "实施状态",
    "st_ph": "{n} 未实施",
    "st_ok": "已实施",
    "routes_note": (
        "未实施端点按契约返回 501 NOT_IMPLEMENTED 并附计划车道，"
        "承载层不改写、不吞掉、不伪装成占位表单。"
    ),
    # ── 6 行业模板 ──
    "tpl_h2": "行业模板（差异全部上移至此）",
    "th_industry": "行业",
    "th_assets": "模板资产",
    "th_shelf": "上架状态",
    "shelf_ok": "已上架：市场 v{n}",
    "shelf_no": "未上架",
    # ── 7 全覆盖 ──
    "matrix_h2": "子模块全覆盖（{n} 格，四态封闭）",
    "matrix_aria": "{parts}",
    "th_module": "子模块",
    "th_state2": "状态",
    "th_boundary": "边界 / 需客户提供",
    "cell_blk": "需客户提供：{blocker}",
    "cell_reason": "理由：{reason}（复核 {review}）",
    "matrix_note": (
        "「全覆盖」指决策空间全覆盖：每格恰好一态、一据、一理由，"
        "对外不问「做了几个模块」，只答这四种之一。判据 tools/check_coverage_matrix.py；"
        "矩阵漂移、不做格被宣称、宣称无模块背书都判红。"
    ),
    "matrix_note2": (
        "另有一份按客户功能清单导入的行业点矩阵（{vertical}，{n} 点，按实现证据分类），"
        "用于单客户范围的实施盘点，不构成本页的四态口径。"
    ),
    # ── 8 缺口 ──
    "gaps_h2": "连接器缺口（{n} 条，每项带机器判据）",
    "th_gap": "缺口",
    "th_responsible": "责任仓",
    "th_status": "状态",
    # ── 9 边界 ──
    "edges_h2": "边界",
    "edge1_dt": "资金（二清红线）",
    "edge1_dd": (
        "只产出对账结果与核对指令。不提供资金池、代收代付、分账执行；"
        "资金归集与分账走客户自选的持牌通道。"
    ),
    "edge2_dt": "开票 / 税务",
    "edge2_dd": (
        "不自研、当前不提供（挂账）。账内可记录发票类事件并参与对账；"
        "票据本体走客户既有合规渠道，不伪造、不代开。"
    ),
    "edge3_dt": "执行面",
    "edge3_dd": (
        "发货、支付、补货、开票等经营动作仅经采纳的外部 MCP server 完成；"
        "凭证由租户自带（BYOK）、经环境变量注入，零落库零日志。"
    ),
    "edge4_dt": "租户隔离",
    "edge4_dd": (
        "同时服务寻数自用与外部商家/泛企业客户；经营数据按租户隔离，"
        "任一客户租户不能读取其他租户的账、单据或报表。"
    ),
    # ── 页脚 ──
    "src_h2": "出处",
    "glossary_h2": "术语表（两语言逐条对应）",
    "say": (
        "本页由 fd-erp/tools/gen_erp_docs.py 于 {date} 生成。数据出处：claims/claims.json、"
        "gaps.json、publish-record.json、tool-surface.json、coverage/、templates/*/manifest.json。"
        "本页不声称任何未在 publish-record.json 中记为 live 的状态。"
    ),
}

_EN = {
    # ── 文档头 ──
    "lang": "en",
    "alt_lang": "zh-CN",
    "alt_href": "../index.html",
    "switch": "中文",
    "title": "ERP Board — Capabilities and Integration · FindData",
    "meta_desc": (
        "Capability surface, interface surface and boundaries of the {name} board; "
        "every figure is derived from the single source of record in the repository."
    ),
    "skip": "Skip to content",
    "doc": "{name} · Capabilities & Integration",
    "h1_sub": "Capabilities, interfaces and boundaries",
    "mark_a": "Derived data",
    "mark_b": "Do not edit",
    "lede": (
        "ERP is delivered as a cluster plus supply packs: an industry-agnostic "
        "double-entry event-ledger kernel, plus vertical template assets (connector packs, "
        "fleet blueprints, chart-of-accounts mappings, report presets), exposed through a "
        "single same-origin entry as a REST surface and an MCP tool surface. "
        "It is not a monolithic ERP application and it ships no form-based UI."
    ),
    "basis": (
        "Every figure on this page is derived at build time from claims.json, gaps.json, "
        "tool-surface.json, coverage/ and the template manifests — the same sources the "
        "claim_gate reads. No prices, customer counts, usage volumes or go-live dates appear here."
    ),
    # ── 口径表 ──
    "tb_caption": "Figures on this page",
    "th_item": "Item",
    "th_count": "Count",
    "th_prov": "Source",
    "row_tools": "MCP tools",
    "row_routes": "Business routes",
    "row_routes_note": "(plus {health} health probes; {ph} of them not implemented)",
    "row_templates": "Vertical templates",
    "row_claimable": "Claimable capabilities",
    "row_not_claimable": "Explicitly not claimed",
    # ── 页内导航 ──
    "act_capability": "Capabilities",
    "act_routes": "Interfaces",
    "act_src": "Verify sources",
    "act_home": "FindData website ↗",
    "index_title": "Index",
    "idx_form": "Shape",
    "idx_form_hint": "five layers",
    "idx_capability": "Capabilities",
    "idx_not_claimable": "Explicitly not claimed",
    "idx_tools": "MCP tool surface",
    "idx_routes": "REST surface",
    "idx_templates": "Vertical templates",
    "idx_matrix": "Sub-module coverage",
    "idx_matrix_hint": "{n} cells, four states",
    "idx_gaps": "Connector gaps",
    "idx_edges": "Boundaries",
    "idx_edges_hint": "four items",
    "n_items": "{n}",
    "n_units": "{n}",
    "n_sets": "{n}",
    # ── 1 形态 ──
    "form_h2": "Shape: five layers, each upgradable on its own",
    "layer1": "Client",
    "layer1_em": "Yizuo miniapp, four ends",
    "layer1_what": "Four page sets: UE / SE / SP / CP",
    "layer1_hop": "/erp/supply-chain/v1/* — same-origin entry; client-supplied X-ERP-* headers are stripped",
    "layer2": "Platform gateway",
    "layer2_em": "platform gateway",
    "layer2_what": "Re-injects identity from session plus binding record; no session returns 401, unbound roles get no identity",
    "layer3": "Vertical REST surface",
    "layer3_em": "vertical api",
    "layer3_what": "{routes} routes; single replica; gate order: tenant → page set → grant → identity domain",
    "layer3_hop": "Always through the kernel tool surface; never touches database tables directly",
    "layer4": "Vertical template layer",
    "layer4_em": "vertical templates",
    "layer4_what": "Cross-border / restaurant / warehousing; four-piece set + pricing + page set; boundaries checked by AST audit",
    "layer4_hop": "Proposals only; never writes facts",
    "layer5": "Ledger kernel",
    "layer5_em": "fact ledger kernel",
    "layer5_what": (
        "Double-entry event ledger. Agent drafts become facts only through the confirmation gate; "
        "facts from external systems enter directly through the ingestion lane at their source "
        "authority. Both derive postings from human-approved posting rules — a missing rule parks "
        "the item for completion rather than guessing an account. Debits equal credits is enforced "
        "by a database constraint."
    ),
    "repo_caption": "Repository composition",
    "th_role": "Role",
    "th_repo": "Repository",
    "th_surface": "Surface",
    "th_src_loc": "Source lines",
    "th_tests_loc": "Test lines",
    # ── 2 能力面 ──
    "cap_h2": "Capabilities (claimable, each with evidence)",
    "th_capability": "Capability",
    "th_id": "Identifier",
    "th_evidence": "Evidence",
    # ── 3 不宣称 ──
    "nc_h2": "Explicitly not claimed (honest scope boundaries)",
    "nc_note": (
        "The items below appear on this page and on the public website only in a negated form; "
        "any affirmative phrasing is rejected by claim_gate.py."
    ),
    "th_scope": "Wording",
    "nc_prefix": "Not claimed: ",
    # ── 4 MCP 工具面 ──
    "tools_h2": "MCP tool surface ({n})",
    "th_tool": "Tool",
    "th_rw": "Read / write",
    "th_behavior": "Behaviour",
    "rw_read": "read",
    "rw_write": "write",
    # ── 5 REST 接口面 ──
    "routes_h2": "REST surface ({business} business routes, {ph} not implemented)",
    "th_face": "Surface",
    "th_route_count": "Routes",
    "th_state": "State",
    "st_ph": "{n} not implemented",
    "st_ok": "Implemented",
    "routes_note": (
        "Unimplemented endpoints return 501 NOT_IMPLEMENTED with a planned lane, per contract. "
        "The transport layer does not rewrite, swallow or disguise them as placeholder forms."
    ),
    # ── 6 行业模板 ──
    "tpl_h2": "Vertical templates (all variance lives here)",
    "th_industry": "Industry",
    "th_assets": "Template assets",
    "th_shelf": "Marketplace status",
    "shelf_ok": "Published: marketplace v{n}",
    "shelf_no": "Not published",
    # ── 7 全覆盖 ──
    "matrix_h2": "Sub-module coverage ({n} cells, four closed states)",
    "matrix_aria": "{parts}",
    "th_module": "Sub-module",
    "th_state2": "State",
    "th_boundary": "Boundary / what the customer must provide",
    "cell_blk": "Customer must provide: {blocker}",
    "cell_reason": "Reason: {reason} (review by {review})",
    "matrix_note": (
        "Coverage here means the whole decision space is covered: every cell carries exactly one "
        "state, one basis and one reason. We never answer how many modules were built; we answer "
        "with one of these four states. The criterion lives in tools/check_coverage_matrix.py: "
        "matrix drift, a claimed out-of-scope cell, or a claim with no backing module is red."
    ),
    "matrix_note2": (
        "There is a separate industry point matrix imported from a customer feature list "
        "({vertical}, {n} points, classified by implementation evidence). It supports scoping for "
        "a single customer and does not constitute the four-state wording on this page."
    ),
    # ── 8 缺口 ──
    "gaps_h2": "Connector gaps ({n}, each with a machine-checkable criterion)",
    "th_gap": "Gap",
    "th_responsible": "Responsible repo",
    "th_status": "Status",
    # ── 9 边界 ──
    "edges_h2": "Boundaries",
    "edge1_dt": "Funds (the second-clearing red line)",
    "edge1_dd": (
        "We produce reconciliation results and checking instructions only. We do not provide a "
        "fund pool, collection or disbursement on behalf of a merchant, or split-payment execution; "
        "fund pooling and splitting go through the customer's own licensed channel."
    ),
    "edge2_dt": "Invoicing / tax filing",
    "edge2_dd": (
        "Not self-built and not currently provided (parked). Invoices can be recorded as events "
        "in the ledger and take part in reconciliation; the invoice itself goes through the "
        "customer's existing compliant channel — never forged, never issued on their behalf."
    ),
    "edge3_dt": "Execution surface",
    "edge3_dd": (
        "Business actions such as shipping, payment, replenishment and invoicing are performed only "
        "by adopted external MCP servers. Credentials are tenant-supplied (BYOK) and injected as "
        "environment variables: never stored, never logged."
    ),
    "edge4_dt": "Tenant isolation",
    "edge4_dd": (
        "Serves FindData's own use and external merchant or enterprise customers at the same time. "
        "Operational data is isolated per tenant: no customer tenant can read another tenant's "
        "ledger, documents or reports."
    ),
    # ── 页脚 ──
    "src_h2": "Sources",
    "glossary_h2": "Terminology (one-to-one across languages)",
    "say": (
        "Generated by fd-erp/tools/gen_erp_docs.py on {date}. Data sources: claims/claims.json, "
        "gaps.json, publish-record.json, tool-surface.json, coverage/, templates/*/manifest.json. "
        "This page claims no state that publish-record.json does not record as live."
    ),
}

STRINGS = {"zh": _Z, "en": _EN}

#: 两语言必须同构：键集相同即「文案键与中文同构」这条判据的机器可读形式。
LANG_KEYS = {"zh": set(_Z), "en": set(_EN)}


def t(lang: str):
    """返回该语言的取值函数：`t("en")("tools_h2", n=3)`。缺键直接 KeyError，不静默印空。"""
    table = STRINGS[lang]
    return lambda key, **kw: table[key].format(**kw) if kw else table[key]
