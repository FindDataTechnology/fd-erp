# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

两类读者，同一页：

1. **外部商家 / 泛企业客户的决策与集成负责人** —— 判断「这套东西能不能接进我现有的账与单据流程」，需要先看懂它不是单体 ERP、边界在哪、接进来要面对什么。
2. **内部与伙伴的工程/集成人员** —— 要按接口面与工具面施工，需要可逐条核对的清单：有哪些路由、哪些未实施、哪些能力可宣称、哪些明确不宣称。

## Product Purpose

ERP 板块是「集群 + 供给包」的组合式交付：一个行业无关的复式事件账内核，加行业模板资产（连接器 pack、舰队蓝图、科目映射、报表 preset），经同源入口对外提供 REST 面与 MCP 工具面。它不是单体 ERP 应用，也不提供表单式 UI。

成功的标志：读者能自己判断「这个能力有没有、边界在哪、我的场景落在哪个模板上」，并且不需要问人就能核到依据。

## Positioning

一切对外表述都由仓内唯一出处派生，并在构建时与声明闸同源校验；页面上的每个数字都带指回源文件的标记。同行可以复制功能列表，但复制不了「每一句都能被机器核验」这条生产线。

## Operating Context

- 页面是生成物：`fd-erp/tools/gen_erp_docs.py` 从 `claims/claims.json`、`gaps.json`、`publish-record.json`、`tool-surface.json`、`coverage/`、`templates/*/manifest.json` 派生 HTML，手改会被 `shared/artifact-lock.json` 指纹拦下。
- 对外文案受 `claim_gate` 逐句扫描：「不宣称」必须落在否定语境里，市场状态必须写成「已上架：市场 vN」，价格 / 客户数 / 用量 / 上线日期一律不写。
- 站点有两处入口：`https://erp.finddatatech.cloud/`（独立域名）与 `https://www.finddatatech.cloud/erp-docs/`（挂在官网路径下），同一份 HTML。

## Capabilities and Constraints

- 现有板块：形态四层、能力面（可宣称）、明确不宣称、MCP 工具面、REST 接口面、行业模板、功能覆盖矩阵、连接器缺口、边界。
- 所有数字必须由 `collect()` 现算，不允许硬编码（见「已知缺陷」）。
- 已知缺陷：形态图里「65 路由」是写死的字符串，实际路由数已变为 63。
- 无后端、无表单、无追踪；单文件静态页，内联 CSS，不引外部字体与脚本。

## Brand Commitments

- 名称：寻数 FindData / ERP 板块。
- 语气：克制、可核验、不做营销夸张；不写价格、客户数、用量、上线日期。
- 对外介绍用「量级话术」，不用精确数字堆砌。

## Evidence on Hand

- `fd-erp/tools/gen_erp_docs.py`（生成器，唯一真源入口）
- `fd-erp-vertical-templates/claims/claims.json`（12 条可宣称 / 7 条不宣称 + 扫描规则）
- `fd-erp-vertical-templates/gaps.json`（4 条缺口，3 条 open）
- `fd-erp/shared/artifact-lock.json`（生成物指纹）
- 实时数据：21 个 MCP 工具、63 条业务路由（含 2 条健康探针、20 条未实施）、3 个行业模板、35 个功能点、3 个已上架连接器 pack。

不存在的材料，后续工作不得编造：客户 logo、案例、报价、SLA、上线时间、性能基准。

## Product Principles

1. **可核验优先**：任何数字都要能指回一个文件；不能指回的就不要写。
2. **边界即产品**：明确不宣称与缺口是这一页的一等公民，不是附录。
3. **不假装成别的形态**：不摆表单、不摆仪表盘、不摆「立即购买」，因为它不是那种产品。
4. **一个真源**：页面上没有一笔是手写的；改内容先改数据。

## Accessibility & Inclusion

- 目标 WCAG 2.1 AA：正文对比度 ≥ 4.5:1，大字 ≥ 3:1，全键盘可达，`prefers-reduced-motion` 下关闭动效。
- 表格使用语义 `<th scope>`；示意图提供文本等价说明。
