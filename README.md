# fd-erp — ERP 板块独立维护根

> 本文件由 `fd-erp/tools/gen_erp_docs.py` 从 `fd-erp/manifest.json` 与各仓机器可读产物派生，**不要手改**。
> 生成日期：2026-11-12。改归属/改资产位置请先改 `manifest.json` 再重跑生成器。

ERP 是**板块**，一十百千万 ladder 之外，与营销/客服台板块同级；不是第六条产品线。章程 `openspec/specs/erp-board/spec.md`；对外口径唯一出处 `docs/erp/README.md`。

## 1. 代码仓

| 角色 | 目录 | 远端 | 形态 | 源码 / 测试 | 边界 |
|---|---|---|---|---|---|
| 账本内核（行业无关） | `fd-erp-ledger-mcp` | `git@github.com:scs001/fd-erp-ledger-mcp.git` | MCP 工具面 | 4456 / 2895 行 | 行业无关；不存行业逻辑；agent 写路径只出 proposal，外部事实经导入车道直收 |
| 行业模板工厂（差异全部上移至此） | `fd-erp-vertical-templates` | `git@github.com:scs001/fd-erp-vertical-templates.git` | 模板资产 + 连接器绑定 + 能力矩阵 | 10715 / 8536 行 | 零旁路账务、零直连库表、回写仅经内核白名单车道、对外部系统零写入（boundary.py 机械审计） |
| 纵向 REST 服务面 | `fd-erp-vertical-api` | `git@github.com:scs001/fd-erp-vertical-api.git` | REST 65 路由（含 20 placeholder） | 3174 / 1797 行 | 单副本；闸序 租户→页面集→grant→身份域；不直连内核库 |

## 2. 资产与规格

| 资产 | 位置 | 有版本控制 | 归属 | 注意 |
|---|---|---|---|---|
| ERP 舰队/角色/技能包（3 个） | `fleet-packs/erp` | 是 | `git@gitee.com:FindDataTechnology/fleet-packs.git` | 与 ERP 仓分离维护，漂移风险高 |
| 客户演示包（跨境 / 餐饮，可复跑） | `collateral-erp` | **否** | — | 不在任何 git 仓内 —— 改动无历史、无法回滚 |
| 对外口径唯一出处（章程 + 不可宣称清单 + 发布状态） | `docs/erp` | **否** | — | 不在任何 git 仓内；claims 的 surfaces 直接引用此路径 |
| ERP 全部主规格（15 erp-* + 4 ecommerce-*） | `openspec/specs` | 是 | `git@gitee.com:FindDataTechnology/finddata-openspec.git` | 与全仓 358 条规格共用一个根；ERP 无自己的 openspec 根 |
| 官网 ERP 板块落地页（双语） | `fd-official-web/src/components/ErpLanding.astro` | 是 | `git@gitee.com:FindDataTechnology/fd-official-web.git` | 在官网仓内，与五线共用布局与 LineTabs |
| 内核工具面 × 客户端覆盖面声明（谁盖哪些、哪些故意不盖及理由） | `fd-erp/shared/kernel-client-contract.json` | 是 | `fd-erp（本根仓）` | 跨仓契约：声明 ≠ 实际即被 check_kernel_client_contract.py 判红 |
| 跨仓语义契约（错误码封闭集 + 指标命名；码表不抄写，从源码 AST 现读） | `fd-erp/shared/semantics-contract.json` | 是 | `fd-erp（本根仓）` | 闸：check_semantics_contract.py；新增仓自有码必须在 service_specific_codes 声明并给理由 |
| 环境变量契约（跨仓同名变量的默认值/必填性 + 含凭据字段的 repr 保护） | `fd-erp/shared/config-contract.json` | 是 | `fd-erp（本根仓）` | 闸：check_config_contract.py；变量清单与默认值从源码 AST 现读 |
| 结构化日志契约（信封字段 + 打码规则 + 可执行向量） | `fd-erp/shared/log-contract.json` | 是 | `fd-erp（本根仓）` | 闸：check_log_redaction.py —— 拿真函数跑真向量，不靠读源码判断有没有保护 |

## 3. 跨仓耦合点（ERP 代码活在别人仓里）

| 内容 | 位置 | 所属仓 | 为什么必须在那 |
|---|---|---|---|
| 同源入口代理（剥 X-ERP-* → 按会话重注入 → 无会话 401） | `paas/server/routes/erp-proxy.js` | `git@gitee.com:FindDataTechnology/fd-craw-private.git` | 必须挂在网关进程（3100）而非 server.js，且早于 SPA 兜底 |
| 四端页面集客户端接线（UE/SE/SP/CP） | `paas/miniapp/src/pagesets` | `git@gitee.com:FindDataTechnology/fd-craw-private.git` | ERP 唯一前端形态；必须建在壹座 miniapp 底座上，不另起框架 |

## 4. 共享组件债（同一契约的 N 份实现）

| 组件 | 实现数 | 位置 | 问题 |
|---|---|---|---|
| `kernel_client` | 2 | `fd-erp-vertical-templates/fd_erp_vertical_templates/kernel_client.py`<br>`fd-erp-vertical-api/fd_erp_vertical_api/kernel_client.py` | 同一工具面在两仓各写一份（Protocol+Mcp 版 vs InProcess+ReconProxy 版）。已落声明式契约 + 覆盖面闸（声明覆盖 19/11），签名不再靠人肉对齐；真正收敛为单一共享包仍待办（需先解决跨仓依赖的 CI 可见性） |
| `errors / error_codes` | 3 | `fd-erp-ledger-mcp/fd_erp_ledger_mcp/errors.py`<br>`fd-erp-vertical-templates/fd_erp_vertical_templates/errors.py`<br>`fd-erp-vertical-api/fd_erp_vertical_api/errors.py` | 错误码封闭集三处各维护，新增码要改三仓。已落跨仓语义契约 + 闸（内核封闭集=镜像、7 个共享码语义逐字一致、仓自有码须声明），仍未收敛为单一常量源 |
| `observability` | 3 | `fd-erp-ledger-mcp/fd_erp_ledger_mcp/observability.py`<br>`fd-erp-vertical-api/fd_erp_vertical_api/observability.py`<br>`fd-erp-vertical-api/fd_erp_vertical_api/logs.py` | 指标/日志两套实现（内核 observability.py + API observability.py/logs.py），指标名不保证同形。指标已闸（命名式 + 跨服务重名 + 桶集偏差声明，api 少 10.0 上界为已声明的偏差）；日志打码是两份代码，由同一组 12 条向量**双跑**钉住同语义（并修掉 apiKey 漏拦与顶层 list 抛异常）；2026-11-11 起 REST 面也有逐请求 JSON 日志（信封同构、默认只记失败）。模板层仍不写日志（审计靠事件档）。仍未收敛为单一实现——两份代码靠闸同语义，不靠共享包 |
| `config` | 2 | `fd-erp-ledger-mcp/fd_erp_ledger_mcp/config.py`<br>`fd-erp-vertical-api/fd_erp_vertical_api/config.py` | 环境变量名与默认值分散，无单一契约。已落配置契约 + 闸（4 个共享变量默认值逐字一致、命名式、含凭据字段必须 repr=False）；仍未收敛为单一常量源 |

### 4.1 内核工具面 × 客户端覆盖面（声明式契约）

工具面真源 `fd-erp-ledger-mcp/tool-surface.json`；谁必须盖哪些、哪些故意不盖及理由，写在 `fd-erp/shared/kernel-client-contract.json`。两侧漂移由 `fd-erp/tools/check_kernel_client_contract.py` 判红（声明 ≠ 实际、发明工具面之外的方法、不覆盖却没给理由，三种都拦）。

| 消费仓 | 覆盖 | 声明不覆盖 |
|---|---|---|
| `fd-erp-vertical-templates` | 25 | 7 |
| `fd-erp-vertical-api` | 17 | 15 |

> 注：tenant 由客户端绑定、不逐方法透传（一进程一租户）；`approved_by` / `submitted_by` / `reversed_by` 不透传，由内核按默认值填 （`human` / `ops` / `human`）—— 这是审计口径的已知取舍，不是漏参。

### 4.2 跨仓语义契约（错误码 / 指标名）

码表与指标名一律从源码 AST 现读，契约文件只写「必须逐字一致的部分」与「允许不同但必须声明的部分」。闸：`fd-erp/tools/check_semantics_contract.py`。

- 错误码：内核封闭集 **24** 个，与 `tool-surface.json` 镜像逐一对照；跨仓共享 **12** 个（语义类别 / 可重试 / 默认提示必须逐字一致）；api 自有 9 个、模板层自有 9 个，均须在契约里声明并给理由
- 指标：内核 11 个 / api 3 个，同一 Prometheus 下不得跨服务重名
- 闸门状态：通过
- 已声明偏差（histogram_buckets，fd-erp-vertical-api）：erp_api_request_seconds 的桶集比内核 erp_tool_latency_seconds 少一个 10.0 上界；待办 `establish-erp-independent-root 3.5`

### 4.3 环境变量契约

变量清单与默认值从源码 AST 现读；契约只声明「哪些是跨仓共享的」与约定本身。闸：`fd-erp/tools/check_config_contract.py`。

| 仓 | 读取的 `ERP_` 变量数 |
|---|---|
| `fd-erp-ledger-mcp` | 5 |
| `fd-erp-vertical-api` | 11 |
| `fd-erp-vertical-templates` | 8 |

- 跨仓共享且已登记：**4** 个 —— `ERP_BASE_CURRENCY`、`ERP_CREDIT_RESERVATION_MAX_DAYS`、`ERP_LEDGER_DATABASE_URL`、`ERP_TENANT_ID`
- 共享变量默认值必须逐字一致（同名不同默认值 = 同一份部署清单在两个进程里两种行为）
- 含凭据的 Settings 字段必须 `field(repr=False)`：日志层打码不覆盖异常栈 / pprint / REPL
- 闸门状态：通过

### 4.4 结构化日志与打码向量

只看源码里有没有 `password` 关键字不算验证 —— 本闸把向量喂给内核**真的** `redact()`，断言凭据值不出现在输出里、非敏感值不被过度打码、任何形态都不许抛异常。闸：`fd-erp/tools/check_log_redaction.py`。

| 服务 | 结构化日志 | 说明 |
|---|---|---|
| `fd-erp-ledger-mcp` | 有 | 9 个事件 |
| `fd-erp-vertical-api` | 有 | 2 个事件 |
| `fd-erp-vertical-templates` | **无** | 模板层不写日志（审计靠 JSONL 事件档与内核日志）。事件档本身是业务事实，不等同运行日志。 |

- 打码向量：**12** 条；闸门状态：通过

## 5. 部署实况

集群 `fd-prod` / 命名空间 `fd-prod`。

| 工作负载 | 类型 | 镜像 | Ready | 暴露面 |
|---|---|---|---|---|
| `fd-erp-ledger-mcp` | Deployment | `ccr.ccs.tencentyun.com/finddata-business/fd-erp-ledger-mcp:sha-e67fa40` | 1 | NodePort 31910（MCP over HTTP） |
| `fd-erp-vertical-api` | Deployment | `ccr.ccs.tencentyun.com/finddata-business/fd-erp-vertical-api:sha-f9a92c6` | 1 | ClusterIP only（唯一入口是 paas 网关 /erp/supply-chain/v1/*；网关侧 ERP_API_UPSTREAM 钉 ClusterIP http://10.43.153.194，因 platform pod 解不了集群 DNS） |

| CronJob | 计划 | 时区 | 挂起 | 上次触发 | 说明 |
|---|---|---|---|---|---|
| `erp-daily-billing` | `10 0 * * *` | Asia/Shanghai | **是** | 从未 | 日终计费快照。suspend=true 是**有意挂账**（清单头已写明）：--snapshot-file 需要 WMS 日终库存快照，而 WMS 只读 provider 未接通（connector-status.json: wms candidates=[]/install_blocked=true）；接通后改 false 并指向 WMS 同步产出 |
| `erp-event-archive-backup` | `37 3 * * *` | Asia/Shanghai | 否 | 2026-11-10T19:37:00Z | 事件档备份。实测 lastScheduleTime 19:37Z = 03:37 CST（集群 controller 按 CST解释未声明 timeZone 的任务）；2026-11-11 已补显式 timeZone，去掉隐式依赖 |
| `erp-ledger-backup` | `12 4 * * *` | Asia/Shanghai | 否 | 2026-11-10T20:12:00Z | 账本库备份。**两处落盘**：本地 PVC（近端快取）+ 异地 103.236.89.174:/opt/backups/erp-ledger（2026-11-11 新增，两端 sha256 逐字节核对，不一致即 Job 失败）。与事件档备份实际相隔 35 分钟（03:37/04:12 CST），均为秒级，不争 IO。残余：备份机本身仍是单点（30G 盘，73% used） |

## 6. 独立站发布

站点 `erp.finddatatech.cloud`，内容 `fd-erp/site/index.html`（生成物，勿手改）。

| 环节 | 位置 | 备注 |
|---|---|---|
| 源站 | `fd-deploy`（124.220.7.175）`/opt/fd/erp/site` | nginx `/etc/nginx/sites-enabled/erp.finddatatech.cloud` |
| 边缘 | 雷池 WAF（终止 TLS）+ 同机 Caddy（按 Host 分发）（103.236.89.212） | Caddy `/etc/caddy/Caddyfile`，upstream `124.220.7.175:80` |

**公网状态：live（子域 https://erp.finddatatech.cloud/ + 官网子路径 /erp-docs/，两处同一份生成物）**

| 公开地址 | 状态 | 形态 | 验收 |
|---|---|---|---|
| https://www.finddatatech.cloud/erp-docs/ | **live** | www 站点 nginx 加 location /erp-docs/ → alias /opt/fd/erp/site/（复用 www 现成证书，经腾讯 CDN） | 2026-11-11 curl 200 / 19087 字节 / md5 与生成物一致 |
| https://erp.finddatatech.cloud/ | **live** | 雷池站点 35（ports 80+443_ssl）→ 同机 Caddy :8080 → 源站 124.220.7.175:80；证书 66 由 acme.sh 签发并入库，续期走 /data/safeline/renew-and-push.sh | 2026-11-11 curl 200 / 19087 字节 / sha256 2012a9038d33205a 与生成物一致；TLS 指纹 BF:1B:B4:44:…:71:32 与 cert_66.crt 相同；六个邻居站同时回归正常（www 200 / platform 200 / mcp 302 / token 200 / lawbench 401 / facet 200） |

已验证：
- 源站：curl --resolve erp.finddatatech.cloud:80:124.220.7.175 → 200，正文与生成物 md5 一致（2026-11-11）
- 边缘：curl -H 'Host: erp.finddatatech.cloud' http://172.22.222.1:8080/ → 200，md5 同上（2026-11-11）
- 公网（子域）：http 404（雷池自身页面）/ https 握手失败（无该域名证书）—— 见未打通说明
- 公网（官网子路径）：https://www.finddatatech.cloud/erp-docs/ → 200 / 19087 字节 / md5 与生成物一致（经腾讯 CDN）

## 7. 能力与缺口（派生，勿手写）

- 可宣称能力：**16** 条（每条带仓内可解析证据）
- 不可宣称：**7** 条（对外材料出现肯定句式即被 `claim_gate.py` 判红）
- 连接器缺口：**7** 条（每项带机器判据）

### 7.1 每格谁在做

- 承揽：**12** 格由智能体团队承担、**0** 格由模板资产承担、**9** 格无承担者（需一次接入或明确不做，各带原因）
- agent 侧工具书：`fd-erp-ledger-mcp/toolkit/`（8 组卡 + `catalog.json`），判据 `scripts/check_toolkit.py`；团队编制见 `fleet-packs/erp/`，判据 `scripts/check_erp_team_coverage.py`
- 承担者：
  - 总账 → `erp-payables-fleet`
  - 应收应付 → `erp-payables-fleet`
  - 多币种与汇率 → `erp-payables-fleet`
  - 对账 → `erp-invoice-fleet`
  - 计费 → `erp-billing-fleet`
  - 信用额度 → `erp-credit-fleet`
  - 销售与订单 → `erp-order-to-cash-fleet`
  - 采购 → `erp-order-to-cash-fleet`
  - 库存（数量面） → `erp-fact-intake-fleet`
  - 仓储与物流 → `supply-chain-warehousing-fleet`
  - 审批流 → `erp-posting-fleet`
  - 主数据 → `erp-order-to-cash-fleet`

团队按平台既有形状落地（fleet 模板 + 逐岗 preset），装包后在管理面板「智能体团队」的看板/驾驶舱/决策队列/运行台账里直接可见——**不为 ERP 另建专用面板**：并行呈现面会成为第二份团队数据。

<!-- claim-gate:begin:marketing-producers -->
### 7.2 事实层的第二个生产者

事件层是**多生产者**的：同一张只追加流水上，每条事实带 `producer` 标记（`erp` / `marketing`），纪律一套（幂等键、定型粒度、只追加、状态只许`pending→accepted|rejected→reversed`）。营销板块当前可生产 **3** 类事实，每类都能指到仓内真实载体：

| 事件类型 | 事实 | 载体出处 | 过账 |
| --- | --- | --- | --- |
| `marketing.content.published` | 内容发布（营销：fd-wire 中已发布的 artifact 版本行） | `fd-wire/api/fd_wire_api/artifacts/models.py#artifact_versions` | 否（只记事实，不入账） |
| `marketing.desk.conversation_closed` | 客服会话关闭（营销：外部 Chatwoot 会话回流，只读） | `chatwoot:conversations` | 否（只记事实，不入账） |
| `marketing.channel.order_paid` | 渠道订单付款（营销：电商连接器只读面回流；付款事实，不是下单事实） | `connector:shopify_admin.orders` | 否（只记事实，不入账） |

- **只有这三类**：投放花费、线索、活动、转化四类在仓内没有任何载体，登记即被黑名单拒绝（`ERP_EVENT_FABRICATED_FACT`）——「先补载体再登记类型」，不许先登记再找人填数。
- **营销账不并入 ERP 账本**：两侧共用的是事件流水与纪律，不是账。营销事件全部 `requires_posting=false`，ERP 的账本仍只由 ERP 的过账规则产生；跨板块看数是同租户内的**只读聚合**（按 `producer` 过滤），不是并账。（`line-integration-charter`：六本账不并成一本。）
- 闸：类型注册表的前缀自洽、载体出处必填、黑名单三条判据在 `fd-erp-ledger-mcp/tests/test_marketing_producers.py`；接线脚本 `fd-wire/scripts/publish_facts_to_kernel.py`（可手动跑、可重放，不进常驻调度）。
<!-- claim-gate:end:marketing-producers -->

## 8. 待办（结构性）

- [ ] 把 collateral-erp 与 docs/erp 纳入版本控制（当前不在任何 git 仓内）
- [ ] 为 ERP 建独立 openspec 根，或将 19 条 erp-*/ecommerce-* 规格迁出全仓 358 条共用根
- [ ] kernel_client 收敛为单一共享包（当前仅声明式契约 + 覆盖面闸；跨仓依赖受 CI 可见性限制）
- [ ] 错误码 / 指标名 / 环境变量收敛到单一常量源（当前为契约 + 闸，仍是各仓各写一份）
- [ ] REST 面访问日志已落（默认 errors 模式）：后续若要接日志平台，需评估 all 模式的量
- [ ] histogram 桶集统一（当前 api 少 10.0 上界，已在契约里声明为偏差）
- [ ] ERP 独立介绍/文档站的英文版
- [ ] erp-daily-billing 启用前置：WMS 日终快照只读 provider 接通（open-connector-mt 侧）
- [ ] 备份机（103.236.89.174）本身是单点：ERP 账本与事件档的异地副本都在它上面，30G 盘 73% used
- [ ] 源站 fd-deploy 上 certbot 为 erp 域名留了一张用不上的证书（TLS 在雷池终止），其 timer 仍每 60 天穿到雷池验域；清理需人工确认：sudo certbot delete --cert-name erp.finddatatech.cloud
- [ ] ERP API 的单副本 + Recreate + local-path PV 钉在 liuliangjkiimypbdzxa：该机一旦 DiskPressure，Pod 无处调度即整服务不可用（2026-11-11 19:34–19:52 实际发生 18 分钟）。缓解=该机 kubelet 已加 ephemeral 预留+软硬阈值；根治=把事件档 PVC 换成可跨节点的存储，或允许双副本（需先解决 JSONL 双写）
