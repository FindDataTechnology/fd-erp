---
version: 1
slug: "site-index-html"
primary_target: "site/index.html"
related_targets: []
---

# Surface: ERP 板块说明页（site/index.html）

## Scope and mode

单文件静态页，两处入口（`erp.finddatatech.cloud/` 与 `www.finddatatech.cloud/erp-docs/`）。混合模式：**首屏 Persuade**（决策者判断这东西是什么、能不能用），**下半 Read**（工程人员逐条核对接口面、工具面与边界）。内容全部由 `gen_erp_docs.py` 从仓内数据派生；本页只改呈现，不改事实。

## Audience, job, action, proof

- **决策者**：30 秒内要能说出「它不是单体 ERP，是一个账内核 + 模板资产，边界写得很清楚」。动作：继续往下读，或去官网了解寻数。
- **工程/集成方**：要能按面找到路由、工具、未实施项、缺口。动作：用科目索引跳转，用脚注核到源文件。
- **证据**：12 条可宣称（逐条带证据数与类型）、7 条明确不宣称、4 条缺口（3 open）、20 条未实施路由——负面项同样是证据，且是这一页最可信的部分。
- **约束**：`claim_gate` 逐句扫描，事实文案逐字保留；不写入价格/客户数/用量/上线日期；不能硬编码任何数字（现有「65 路由」写死即缺陷）。

## Chosen direction

**账簿纸 · 复式记账**（用户指定，优先于任何轮盘分配，故不跑 direction roll）。理由：产品本体就是一个复式事件账内核，账簿是这个世界的原生材料，而不是给技术产品套一层「科技感」。

旗标式记忆点：**试算表摘要 + 脚注溯源**——四行「项目 / 数量 / 出处」，每个数字带脚注标记，指回页脚的文件清单。它把「每个数字都能被核验」这条定位变成可操作的动作。

未决：是否公开一个联系入口。当前只用两个文中锚点 + 一个指向官网的真实外链，不编造联系方式。

## Direction contract

**THESIS** 这一页是一份可以被逐笔核对的账簿，不是 SaaS 的能力卡片墙。它拒绝这个品类的默认布置：英雄区大数字 + 三列图标卡片 + 特性网格 + 结尾 CTA 大横幅。

**OWN-WORLD** 淡绿灰账簿纸（`#eef1ec`）上的铁胆墨（`#1a2320`）；细分栏线 `#c8d2c9`、重线 `#a9b8ad`；左侧金额栏竖线贯穿正文列；标题下双横线（合计线）；表头浅色带；数字一律衬线等宽（tabular lining numerals）；红字只用于「不宣称 / 未实施 / open」，绿字只用于「已实施 / 已上架」。宋体承担叙述与标题，无衬线承担表格与界面标签，等宽只给代码与标识。

**STORY** 先看懂它是什么（账内核 + 模板资产，不是单体 ERP），再相信每个数字都有出处（脚注指回源文件），最后顺着科目索引查到接口面、工具面与边界。

**FIRST VIEWPORT** 顶部一条细线报头（左：FIND DATA；右：文档名 + 日期）。其下两行宋体 h1（「ERP 板块」/「能力、接口与边界」），`clamp(2.4rem,6vw,3.9rem)`，紧贴一条双横线；导语限 62ch；再下是四行试算表摘要（项目 / 数量 / 出处脚注），数字右对齐等宽；主行动是摘要下方的两个文中锚点。全屏 CTA 块、按钮组、图标网格一律不做。

**FORM** 账簿纸印刷体；候选序列第 1 位（用户指定，唯一候选）；seed key `user-pinned-ledger-paper`。

**FINISH** unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.
