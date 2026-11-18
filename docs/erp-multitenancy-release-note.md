# ERP 多租户：已上线能力的边界（release note / 运维手册共用）

> 覆盖两个已完成并上产的 change：`erp-tenant-from-session`（平台侧按会话算租户）
> 与 `erp-tenant-upstream-routing`（平台侧按租户选上游）。
> 内核侧的 schema 隔离在 `erp-tenant-schema-isolation`（已归档）。
>
> **一句话**：平台侧现在**有能力**算出租户并按租户选上游；但**真正的多租户还没成立**——
> 还差给每个租户竖一份上游实例。别把它读成「改完就支持多租户」。

## 1. 已经能做的（现在就是这种行为）

| 能力 | 行为 | 判据 |
|---|---|---|
| 按会话算租户 | 绑定表 `tenant` 字段 → 部署缺省 `ERP_TENANT_ID` → 都没有则拒绝 | `403 tenant-unbound`，**不注入**空值头 |
| 算不出租户 | 拒绝，不匿名兜底、不静默用别人的租户 | 同上 |
| 客户端伪造 `X-ERP-Tenant` | 一律剥离后重算 | 客户端值不出现在上游请求的任何位置 |
| 一个会话多个租户 | 不支持，且表现明确 | 同一邮箱恒得同一租户 |
| 按租户选上游 | `ERP_API_UPSTREAM_MAP` 命中则用该实例，否则回落 `ERP_API_UPSTREAM` | 头里写的租户与该请求发往的实例同源 |
| 该租户没配上游 | 拒绝，**不回落**到别人的实例 | `503 UPSTREAM_NOT_CONFIGURED`，消息点名该租户 |
| 租户标识形状非法 | 平台侧就判配置错误，不飘到上游 | `400 invalid-tenant` |
| **不配** `ERP_API_UPSTREAM_MAP` | 与本次变更前逐字节相同（单上游，零行为变化） | `scripts/test-erp-proxy-zero-change.mjs` |

**上线时的实际状态（2026-11-18）**：生产 `fd-prod/platform` 的 env 里
`ERP_API_UPSTREAM=http://10.43.153.194`、`ERP_TENANT_ID=acme`、
**没有** `ERP_API_UPSTREAM_MAP`，绑定表里两个邮箱都没有 `tenant` 字段。
因此现网走的是「单上游 + 部署缺省租户」这条路径，与变更前一致。

## 2. 还没成立的多租户（MUST NOT 被误读）

要让第二个租户真正可用，还需要**部署动作**（不在代码里）：

1. 为每个租户竖一份 `fd-erp-vertical-api`（同一份 `fd-infra-deploy/all-services/prod/fd-erp-vertical-api.yaml`，改三处）：
   - `metadata.name` / Service 名加租户后缀
   - `ERP_TENANT_ID` 取该租户的值
   - `ERP_LEDGER_DATABASE_URL` 可共用（内核侧已 schema 隔离）
2. 平台侧加一条 env：`ERP_API_UPSTREAM_MAP={"acme":"http://…-acme:8000","other":"http://…-other:8000"}`
3. 在绑定表里给该租户的账号填 `tenant` 字段

**在这三步之前**：`fd-erp-vertical-api` 是**一进程一租户**的（`tenant_gate` 比对
`X-ERP-Tenant` 与进程常量），所以除缺省租户外的任何租户都会在上游被拒。
这不是平台侧的过错，是「上游只有一份」。

## 3. 租户标识的写法（两侧必须一致）

| 概念 | 形式 | 例子 |
|---|---|---|
| 租户**标识**（绑定表 `tenant`、`X-ERP-Tenant` 头、`ERP_API_UPSTREAM_MAP` 的键） | 不带前缀的 slug：`^[a-z0-9_]+$`，≤32；`default` 是租户 0 | `acme` |
| schema 名（内核由标识派生） | `tenant_<标识>`；`default` 映射到 `public` | `tenant_acme` |

**别写 `tenant_acme` 当标识**——那是 schema 名，会被派生成 `tenant_tenant_acme`。

判据不是靠人记：平台仓 `scripts/erp-tenant-slug-cases.json` 与内核仓
`fd-erp-ledger-mcp/tests/erp-tenant-slug-cases.json` 各存一份取值清单，各自 CI 断言
自己的实现正确；两份清单是否相同由工作区脚本
`scripts/check_erp_tenant_slug_contract.py` 判（两个仓的 CI 互相看不见，只能在都可见处判）。

## 4. 排查指引（按看到的错误码）

| 现象 | 含义 | 查哪里 |
|---|---|---|
| `401 AUTH_REQUIRED` | 没有会话 | 登录态；网关是否注入了身份头 |
| `403 tenant-unbound` | 有会话，但算不出租户 | 绑定表有没有这个邮箱；`ERP_TENANT_ID` 是否设了 |
| `400 invalid-tenant` | 租户标识形状非法（中文/连字符/大写/超长/空） | 绑定表的 `tenant` 值或 `ERP_TENANT_ID` |
| `503 UPSTREAM_NOT_CONFIGURED` | 该租户没有配置上游 | `ERP_API_UPSTREAM_MAP` 的键是否与标识逐字相同 |
| 上游回 `TENANT_DENIED` | 请求打到了**另一个租户的实例** | 该实例的 `ERP_TENANT_ID` 与 map 的键是否一致 |
| 上游回 `INVALID_ARGUMENT`（租户 id） | 标识到了内核侧才被拒 | 平台侧白名单本应拦住——查两侧判据是否漂移 |
