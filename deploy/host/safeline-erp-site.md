# 雷池站点 35 / 证书 66（`erp.finddatatech.cloud` 的公网入口）

公网入口在**雷池**（`<edge-host>`），不在源站。源站只提供 :80 静态内容，TLS 与
按 Host 分发都在这一层。这段配置**不在任何仓里**，只存在于雷池的 PostgreSQL 行与
它生成的 nginx 文件里，重装/换机就无声消失，所以把事实与回滚步骤记在这里。

## 现状（2026-11-11 实测）

| 项 | 值 |
|---|---|
| 站点行 | `mgt_website.id = 35`：`server_names=["erp.finddatatech.cloud"]`，`ports=["80","443_ssl"]`，`cert_id=66`，`cert_type=2`，`is_enabled=true` |
| 上游 | `upstreams=["http://172.22.222.1:8080"]`（同机 Caddy 的 :8080，见 `caddy-erp-route.conf`） |
| 证书行 | `mgt_ssl_cert.id = 66`：`CN=erp.finddatatech.cloud`，issuer `YE2`（Let's Encrypt），`valid_before = 2027-02-09 17:15:55+08` |
| 线上实际指纹 | `sha256 BF:1B:B4:44:6F:F2:56:36:AC:E5:7B:5D:70:FE:3F:41:2F:F3:36:03:18:96:2F:FF:0D:A1:FD:33:E0:15:71:32`（`openssl s_client` 取到的与 `cert_66.crt` 逐个字符相同） |
| 生成文件 | `/data/safeline/resources/nginx/sites-enabled/IF_backend_35`（容器内 `/etc/nginx/sites-enabled/`）、`tamper-enabled/site_35`、`custom_params/backend_35` |
| 证书文件 | `/data/safeline/resources/nginx/certs/cert_66.crt`、`cert_66.key`（key 权限 600） |
| DB 连接 | `docker exec safeline-pg psql -U safeline-ce -d safeline-ce`（注意库名与角色都叫 `safeline-ce`，`-U safeline` 会报 role 不存在） |

## 为什么是「DB 行 + 生成文件」两处都要

雷池的控制面（`mgt`）把站点/证书读出来渲染成 `IF_backend_<id>` 并 reload tengine。
**只改 DB 不生成文件**：控制台显示已配置，但 tengine 不加载，公网照旧 404/证书不匹配。
**只写文件不改 DB**：下一次控制台任意保存都会把文件覆盖回去。

所以本仓记录的是**两处的最终形态**。IF 文件是由 `IF_backend_30`（demo 站）克隆改出来的，
可读性好、也是当时唯一可行路径（该机没有 OpenAPI 建站接口所需的 token 形态）。

## 续期链路（不要绕过它手工改 cert_id）

```
acme.sh（雷池本机，webroot /var/www/acme，Caddy 侧有 acme-challenge 处理器）
  └─ /data/safeline/renew-and-push.sh   ← 每天 cron，md5 门控只在证书真变了才推
       └─ /data/safeline/push-cert.py <cert_dir> <site_id> <domain>
            ├─ POST /api/open/cert  上传新证书，拿到**新的** cert id
            ├─ GET  /api/open/site/35 → PUT 带新 cert_id（不写死 65/66）
            └─ 清理：同域名、未被任何站点引用、且不是新证书的旧行
```

**关键点：`push-cert.py` 不写死证书 id**，每次上传新行再把站点指过去。所以
「站点 35 现在绑 66」不会让续期失效——续期后它会变成 67、68……这是对的。
反过来，**手工把 cert_id 改回某个旧值才是错的**：旧行可能已被清理逻辑删掉。

`/data/safeline/renew-and-push.sh` 的 `CERTS` 数组里已经有
`"/root/.acme.sh/erp.finddatatech.cloud_ecc|35|erp.finddatatech.cloud"`，
新增站点时**必须**同时补这一行，否则证书 90 天后过期而没人推。

## 已知残留

1. **证书行 65 是孤儿**（issuer `YE1`，同日 18:20 上传，站点已改指 66）。它不被任何
   站点引用，`push-cert.py` 的清理段会在下次推送时删掉它。不要手工把它绑回去。
2. **源站 `fd-deploy` 上还有一张 certbot 签的同名证书**（`/etc/letsencrypt/live/
   erp.finddatatech.cloud/`）。TLS 在雷池终止，源站这张**用不上**，但 certbot 的
   timer 仍会每 60 天去验一次域（会穿到雷池）。清理方法（需人工确认后执行）：
   `sudo certbot delete --cert-name erp.finddatatech.cloud`。
   在此之前它只是噪音，不影响服务。

## 回滚（下线这个站点）

```bash
# 1) 先确认没有别人在用（否则会把 38 个邻居站一起打白，见 README 坑 2）
curl -s -o /dev/null -w 'lawbench %{http_code} %{size_download}\n' https://lawbench.finddatatech.cloud/healthz

# 2) 删站点行与证书行，移除生成文件，再 reload
ssh root@<edge-host> '
  docker exec safeline-pg psql -U safeline-ce -d safeline-ce -c "delete from mgt_website where id=35;"
  docker exec safeline-pg psql -U safeline-ce -d safeline-ce -c "delete from mgt_ssl_cert where id in (65,66);"
  rm -f /data/safeline/resources/nginx/sites-enabled/IF_backend_35 \
        /data/safeline/resources/nginx/tamper-enabled/site_35 \
        /data/safeline/resources/nginx/custom_params/backend_35
  docker exec safeline-tengine nginx -t && docker exec safeline-tengine nginx -s reload
'

# 3) 验收必须包含**邻居**：erp 自己 404 很正常（已下线），
#    但 www / platform / lawbench 都必须还是原来的状态码
```

## 踩过的坑（按发生顺序）

1. **`server_names` 里必须只放一个域名**。克隆 `IF_backend_30` 时，`if ($host !~*
   ^(demo\.finddatatech\.cloud)$)` 这行改写不彻底，会让**所有**请求重写到
   `not_found`——表现出来是「站点建好了但永远是 404」，而 nginx 配置本身合法。
   改完必须 `grep -c 'demo\.'` 确认为 0。
2. **`ports` 只写 `["80"]` 时 :443 会落到默认站点证书**：浏览器报 CN 不匹配，
   `curl` 不加 `-k` 直接 000。必须是 `["80","443_ssl"]` + `cert_id`。
3. **证书 PEM 入库要用 dollar-quoting**：`cert_content` 里是多行 PEM，用
   `$cert$…$cert$` 包住写 SQL 文件再 `docker cp` 进容器执行，别在 `psql -c` 里拼引号。
4. **验收不看 200，看指纹**：`curl` 200 + 19KB 只能说明「有人在应答」。
   必须比对 `openssl s_client` 的 sha256 与 `cert_66.crt` 一致，且**旁证一个邻居站**。
