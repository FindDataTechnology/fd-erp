# 店面上线 runbook（change establish-ai-native-ecommerce-stack 0.16）

> 目标：一个商家从「有货」到「能匿名下单并被确认」，四步全部真发生。
> **四步链路 = 开张的判据**（spec `ecommerce-tenant-provisioning`「开张判据以真实读取为证」）；
> 只部署成功不算开张。

## 0. 开一家新店的唯一入口

```bash
cp tenants/example-shop.json tenants/<你的店>.json   # 改 tenant_id / shop_title / retail_channel
python3 fd-erp/tools/open_shop.py tenants/<你的店>.json --dry-run   # 先校验
python3 fd-erp/tools/open_shop.py tenants/<你的店>.json             # 建 schema + 数据根
```

脚本做四件事：校验清单 → 建租户 schema（内核侧，幂等）→ 建店面数据根 →
打印部署三件套（环境变量、快照命令、四步验收）。

**不改代码**。清单缺项逐条点名并拒绝，不产生任何 schema 或目录。

### 隔离靠进程边界，不靠同进程多租户

每个商家店是**一个绑定单一租户的进程** + 它自己的数据根。**不要**让同一进程服务两个租户：
`/shop/{tenant}` 的路径参数校验只是「这个进程是不是这个租户」的一道确认，
真正的隔离来自进程与数据根分离。第二家店 = 第二个进程。

（实测：甲店进程读 `/shop/shop_b/products` → 404，且响应不回显 `shop_b`。）

## 0.1 前置：这台机器能做什么

| 项 | 要求 | 怎么验 |
|---|---|---|
| API 进程 | `fd-erp-vertical-api` 在跑，`ERP_TENANT_ID` 已设 | `curl /health` → `{"ok":true,...}` |
| 零售渠道 | `ERP_RETAIL_CHANNEL` 已设（**不设 = 店面关闭**） | 见 §1 |
| 内核 | 已跑过 migration（含 `0022_retail_payment_event`） | `fd-erp-ledger-mcp schema-version` → 0022 |
| 静态托管 | 任意静态 HTTP 服务（nginx/Caddy/python -m http.server） | §4 |

## 1. 配零售渠道并上架第一个可售商品

零售价是取价引擎的**第四层**，作用域是 (租户, 零售渠道, 商品)。
**不配置零售价 = 该商品不可售**（不会回落 B2B 价或商品主档 base_price）。

```bash
# 1.1 设置渠道（进程级；pod 里是 env）
export ERP_RETAIL_CHANNEL=retail-online

# 1.2 商品必须：已建档(active) + 在零售渠道可见的商品池内 + 有 retail 层价目
#     三条缺任一，公开读面都不会出它（这是「只出零售渠道商品」的判据）
```

价目经 `PricingRuleBook` 的确认车道写入（`add_rule` → `confirm_rule`），
缺 `rate_source` 的规则会被拒（无出处规则拒绝参与取价）。

## 2. 四步链路验收（**全部真发生才算开张**）

```bash
BASE=http://<api-host>          # 例：http://10.43.153.194
TENANT=<ERP_TENANT_ID>

# ── 步骤 1：读商品（匿名）─────────────────────────────────────────
curl -s "$BASE/shop/$TENANT/products" | python3 -m json.tool
# 判据：HTTP 200；data 非空；每件带 unit_price 与 price_source；
#       **不含** entity_id / supplier_id / base_price

# ── 步骤 2：下单（匿名，预付）─────────────────────────────────────
curl -s -X POST "$BASE/shop/$TENANT/orders" \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: acceptance-$(date +%s)" \
  -d '{"lines":[{"productId":"<code>","qty":1}],
       "shipTo":{"name":"验收收货人","phone":"13800000000"}}' | python3 -m json.tool
# 判据：200；settlement_mode=prepaid；payment_state=awaiting_payment；
#       记下 order_ref（形如 SO-XXXXXXXXXX）
# 负例：去掉 shipTo → 400 且 detail.missing=shipTo

# ── 步骤 3：确认到账（商家身份）───────────────────────────────────
curl -s -X POST "$BASE/shop/$TENANT/orders/<order_ref>/payment" \
  -H "X-ERP-Tenant: $TENANT" -H 'Content-Type: application/json' \
  -d '{"amount":"<订单金额>","proofRef":"<银行流水号>"}' | python3 -m json.tool
# 判据：200；requires_posting=false（平台不落分录）；duplicate=false
# 负例：同参数再打一次 → duplicate=true，事件层不新增
# 负例：去掉 X-ERP-Tenant → 401

# ── 步骤 4：进入履约（确认门）───────────────────────────────────
# 未到账时确认必须被拒（确认即放货）：
#   confirm_order(request_id) → 409 WORKFLOW_STATE「预付单尚未到账」
# 到账后确认 → status=confirmed + handoff_ref 产生
python3 - <<'PY'
# 在 API 进程内或经运维入口调用：
#   drivers.orders.confirm_order(request_id)
PY
curl -s "$BASE/shop/$TENANT/orders/<order_ref>" | python3 -m json.tool
# 判据：status=confirmed；payment_state=received
```

## 3. 店面静态产物

产物**只展示公开读面**，不含订单、买家、到账（那些不是公开数据）。

```bash
# 3.1 从运行中的 API 拉快照（只读公开面）
STOREFRONT_API_BASE="$BASE" STOREFRONT_TENANT="$TENANT" \
  python3 fd-erp/tools/collect_storefront_snapshot.py

# 3.2 生成静态页（零网络、零 npm）
python3 fd-erp/tools/gen_storefront.py

# 3.3 校验产物与快照一致
python3 fd-erp/tools/gen_storefront.py --check
```

快照三种状态如实区分（不要把它们当成一回事）：

| `available` | `products` | 页面显示 | 含义 |
|---|---|---|---|
| true | 非空 | 商品卡片 | 正常 |
| true | 空 | 「暂无在售商品 + 该渠道当前没有…」 | 店面开着但没货 |
| false | 空 | 「暂无在售商品 + 具体原因」 | **取数失败**（未配置地址/连不上/API 报错） |

## 4. 部署与回滚

```bash
# 部署：静态产物整目录同步（含任何子目录，别只传 index.html）
rsync -az fd-erp/site/shop/ <web-host>:/opt/fd/shop/
# 域名 / TLS：与既有站点同法（边缘 WAF 终止 TLS，源站只提供 :80）

# 回滚 = 撤部署，不涉及数据删除：
#   1) 移除静态目录 / 改 nginx 指向 404 页
#   2) 若要把店面整个关掉：unset ERP_RETAIL_CHANNEL 并重启 API
#      → 公开读面立刻返回空集合（不是回落成全量商品可见）
```

## 5. 验收判据汇总（机器可核）

- [ ] `GET /shop/{tenant}/products` 匿名 200，且响应里**没有** `entity_id`/供应商/成本价
- [ ] 跨租户 `GET /shop/other-tenant/products` → 404，响应体不含请求里的租户名
- [ ] `POST /shop/{tenant}/orders` 缺 `shipTo` → 400 且 `detail.missing=shipTo`
- [ ] 预付单**不产生任何信用占用行**（占用明细零新增）
- [ ] 未到账确认 → 409；到账后确认 → confirmed + handoff
- [ ] 同一 `Idempotency-Key`/同一到账幂等键重复 → 返回首次，不新增事实
- [ ] 店面产物与快照一致（`gen_storefront.py --check` 退出 0）
- [ ] 无商品时页面写「暂无在售商品 + 原因」，无样例商品、无占位价

## 已知限制

- **限流是进程内的**（按来源地址滑动窗）。多副本时各进程各计，实际上限 = 副本数 × 120/分钟；
  正式接管方应是边缘层。见 `storefront.py` 的 `_RATE_BUCKETS` 注释。
- **下单幂等表也是进程内的**（`_ORDER_IDEMPOTENCY`）。多副本部署前必须换成共享存储。
- 在线支付通道本版未接：首版只做「线下转账 + 商家人工确认到账」。
- 店面 UI 是单页静态（无购物车持久化、无会员）：下单靠页面直接 POST API。
