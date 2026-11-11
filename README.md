# fd-erp — ERP 板块独立维护根

> 本文件由 `fd-erp/tools/gen_erp_docs.py` 从 `fd-erp/manifest.json` 与各仓机器可读产物派生，**不要手改**。
> 生成日期：2026-11-11。改归属/改资产位置请先改 `manifest.json` 再重跑生成器。

ERP 是**板块**，一十百千万 ladder 之外，与营销/客服台板块同级；不是第六条产品线。章程 `openspec/specs/erp-board/spec.md`；对外口径唯一出处 `docs/erp/README.md`。

## 1. 代码仓

| 角色 | 目录 | 远端 | 形态 | 源码 / 测试 | 边界 |
|---|---|---|---|---|---|
| 账本内核（行业无关） | `fd-erp-ledger-mcp` | `git@github.com:scs001/fd-erp-ledger-mcp.git` | MCP 工具面 | 4456 / 2895 行 | 行业无关；不存行业逻辑；写路径只出 proposal |
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

## 3. 跨仓耦合点（ERP 代码活在别人仓里）

| 内容 | 位置 | 所属仓 | 为什么必须在那 |
|---|---|---|---|
| 同源入口代理（剥 X-ERP-* → 按会话重注入 → 无会话 401） | `paas/server/routes/erp-proxy.js` | `git@gitee.com:FindDataTechnology/fd-craw-private.git` | 必须挂在网关进程（3100）而非 server.js，且早于 SPA 兜底 |
| 四端页面集客户端接线（UE/SE/SP/CP） | `paas/miniapp/src/pagesets` | `git@gitee.com:FindDataTechnology/fd-craw-private.git` | ERP 唯一前端形态；必须建在壹座 miniapp 底座上，不另起框架 |

## 4. 共享组件债（同一契约的 N 份实现）

| 组件 | 实现数 | 位置 | 问题 |
|---|---|---|---|
| `kernel_client` | 2 | `fd-erp-vertical-templates/fd_erp_vertical_templates/kernel_client.py`<br>`fd-erp-vertical-api/fd_erp_vertical_api/kernel_client.py` | 同一 21 工具面在两仓各写一份（Protocol+Mcp 版 vs InProcess+ReconProxy 版）。已落声明式契约 + 覆盖面闸（声明覆盖 19/11），签名不再靠人肉对齐；真正收敛为单一共享包仍待办（需先解决跨仓依赖的 CI 可见性） |
| `errors / error_codes` | 3 | `fd-erp-ledger-mcp/fd_erp_ledger_mcp/errors.py`<br>`fd-erp-vertical-templates/fd_erp_vertical_templates/errors.py`<br>`fd-erp-vertical-api/fd_erp_vertical_api/errors.py` | 错误码封闭集三处各维护，新增码要改三仓。已落跨仓语义契约 + 闸（内核封闭集=镜像、7 个共享码语义逐字一致、仓自有码须声明），仍未收敛为单一常量源 |
| `observability` | 2 | `fd-erp-ledger-mcp/fd_erp_ledger_mcp/observability.py`<br>`fd-erp-vertical-api/fd_erp_vertical_api/observability.py` | 指标/结构化日志两套实现，指标名与字段不保证同形。已落指标命名式 + 跨服务重名闸 + 桶集偏差声明；日志字段名仍待对齐 |
| `config` | 2 | `fd-erp-ledger-mcp/fd_erp_ledger_mcp/config.py`<br>`fd-erp-vertical-api/fd_erp_vertical_api/config.py` | 环境变量名与默认值分散，无单一契约 |

### 4.1 内核工具面 × 客户端覆盖面（声明式契约）

工具面真源 `fd-erp-ledger-mcp/tool-surface.json`；谁必须盖哪些、哪些故意不盖及理由，写在 `fd-erp/shared/kernel-client-contract.json`。两侧漂移由 `fd-erp/tools/check_kernel_client_contract.py` 判红（声明 ≠ 实际、发明工具面之外的方法、不覆盖却没给理由，三种都拦）。

| 消费仓 | 覆盖 | 声明不覆盖 |
|---|---|---|
| `fd-erp-vertical-templates` | 19 | 2 |
| `fd-erp-vertical-api` | 11 | 10 |

> 注：tenant 由客户端绑定、不逐方法透传（一进程一租户）；`approved_by` / `submitted_by` / `reversed_by` 不透传，由内核按默认值填 （`human` / `ops` / `human`）—— 这是审计口径的已知取舍，不是漏参。

### 4.2 跨仓语义契约（错误码 / 指标名）

码表与指标名一律从源码 AST 现读，契约文件只写「必须逐字一致的部分」与「允许不同但必须声明的部分」。闸：`fd-erp/tools/check_semantics_contract.py`。

- 错误码：内核封闭集 **17** 个，与 `tool-surface.json` 镜像逐一对照；跨仓共享 **7** 个（语义类别 / 可重试 / 默认提示必须逐字一致）；api 自有 9 个、模板层自有 9 个，均须在契约里声明并给理由
- 指标：内核 11 个 / api 3 个，同一 Prometheus 下不得跨服务重名
- 闸门状态：通过
- 已声明偏差（histogram_buckets，fd-erp-vertical-api）：erp_api_request_seconds 的桶集比内核 erp_tool_latency_seconds 少一个 10.0 上界；待办 `establish-erp-independent-root 3.5`

## 5. 部署实况

集群 `fd-prod` / 命名空间 `fd-prod`。

| 工作负载 | 类型 | 镜像 | Ready | 暴露面 |
|---|---|---|---|---|
| `fd-erp-ledger-mcp` | Deployment | `ccr.ccs.tencentyun.com/finddata-business/fd-erp-ledger-mcp:sha-64bd819` | 1 | NodePort 31910（MCP over HTTP） |
| `fd-erp-vertical-api` | Deployment | `ccr.ccs.tencentyun.com/finddata-business/fd-erp-vertical-api:sha-a07c97c` | 1 | ClusterIP only（唯一入口是 paas 网关 /erp/supply-chain/v1/*） |

| CronJob | 计划 | 时区 | 挂起 | 上次触发 | 说明 |
|---|---|---|---|---|---|
| `erp-daily-billing` | `10 0 * * *` | Asia/Shanghai | **是** | 从未 | 日终计费快照，当前挂起且从未触发 |
| `erp-event-archive-backup` | `37 3 * * *` | 未声明 | 否 | 2026-11-10T19:37:00Z | 事件档备份；清单未写 timeZone（按集群本地时区解释） |
| `erp-ledger-backup` | `12 4 * * *` | Asia/Shanghai | 否 | 2026-11-10T20:12:00Z | 账本库备份 |

## 6. 独立站发布

站点 `erp.finddatatech.cloud`，内容 `fd-erp/site/index.html`（生成物，勿手改）。

| 环节 | 位置 | 备注 |
|---|---|---|
| 源站 | `fd-deploy`（124.220.7.175）`/opt/fd/erp/site` | nginx `/etc/nginx/sites-enabled/erp.finddatatech.cloud` |
| 边缘 | 雷池 WAF（终止 TLS）+ 同机 Caddy（按 Host 分发）（103.236.89.212） | Caddy `/etc/caddy/Caddyfile`，upstream `124.220.7.175:80` |

**公网状态：blocked** —— 雷池控制台需新增站点 erp.finddatatech.cloud（端口 80 + 443_ssl，upstream http://172.22.222.1:8080，并申请含该域名的证书）。该机无 OpenAPI token，控制台需登录凭据，故此项不由本仓代办。

已验证：
- 源站：curl --resolve erp.finddatatech.cloud:80:124.220.7.175 → 200，正文与生成物逐字节一致（2026-11-11）
- 边缘：curl -H 'Host: erp.finddatatech.cloud' http://172.22.222.1:8080/ → 200，正文同上（2026-11-11）
- 公网：http 404（雷池自身页面）/ https 握手失败（无该域名证书）

## 7. 能力与缺口（派生，勿手写）

- 可宣称能力：**12** 条（每条带仓内可解析证据）
- 不可宣称：**7** 条（对外材料出现肯定句式即被 `claim_gate.py` 判红）
- 连接器缺口：**4** 条（每项带机器判据）

## 8. 待办（结构性）

- [ ] 把 collateral-erp 与 docs/erp 纳入版本控制（当前不在任何 git 仓内）
- [ ] 为 ERP 建独立 openspec 根，或将 19 条 erp-*/ecommerce-* 规格迁出全仓 358 条共用根
- [ ] kernel_client 收敛为单一共享包（当前仅声明式契约 + 覆盖面闸；跨仓依赖受 CI 可见性限制）
- [ ] 错误码 / 指标名收敛到单一常量源（当前为契约 + 闸，仍是各仓各写一份）
- [ ] 日志字段名对齐（指标名已闸，日志键名尚未）
- [ ] histogram 桶集统一（当前 api 少 10.0 上界，已在契约里声明为偏差）
- [ ] ERP 独立介绍/文档站（本仓 site/）的英文版与发布通道
- [ ] 确认 erp-daily-billing 挂起是否为预期（当前 suspend=true 且从未触发）
