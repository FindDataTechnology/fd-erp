# fd-erp 的宿主机侧配置（版本化副本）

这三段配置原本只存在于机器上（宿主机 nginx 配置**不在任何仓里**）。重装、重铺配置、
或换一台源站，改动就无声消失。所以把线上实际内容拉回这里做版本化副本。

| 文件 | 落点 | 用途 |
|---|---|---|
| `nginx-erp-subdomain.conf` | `fd-deploy:/etc/nginx/sites-enabled/erp.finddatatech.cloud` | `erp.finddatatech.cloud` 静态站（源站 :80；TLS 由雷池终止，证书见下节） |
| `nginx-www-erp-docs.snippet.conf` | 插进 `fd-deploy:/etc/nginx/sites-enabled/www.finddatatech.cloud` 的 `location / {` 之前 | `www.finddatatech.cloud/erp-docs/`（复用 www 证书） |
| `caddy-erp-route.conf` | 追加到 `root@<edge-host>:/etc/caddy/Caddyfile` | 雷池同机 Caddy 按 Host 转发到源站 <origin-host>:80；**含 acme-challenge 处理器，别删** |

## 边缘 TLS（雷池站点 35 / 证书 66）

详细行值、续期链路与回滚见 **[safeline-erp-site.md](safeline-erp-site.md)**。这里只留最
容易踩坏的三条。

`erp.finddatatech.cloud` 的证书由雷池终止，链条是：acme.sh（HTTP-01，webroot
`/var/www/acme`）→ 上传到雷池（拿到 cert id）→ 绑给站点 35。**站点 35 的端口必须是
`["80","443_ssl"]`**，只留 `["80"]` 时 :443 会落到默认站点证书上，浏览器报 CN 不匹配
（`curl` 不加 `-k` 直接 000）。

现状（2026-11-11 实测）：

| 项 | 值 |
|---|---|
| 雷池站点 | id **35**，`server_names=["erp.finddatatech.cloud"]`，`ports=["80","443_ssl"]`，upstream `http://<edge-gateway>:8080` |
| 证书 | id **66**，`CN=erp.finddatatech.cloud`，Let's Encrypt（YE2），有效期至 2027-02-09；线上指纹已与签发文件核对一致 |
| 私钥/全链 | acme.sh 的站点证书目录（续期走 雷池的续期脚本 → `push-cert.py`：每次上传新证书再 PUT 站点，**不写死 cert id**，所以「现在绑 66」不影响续期） |
| 续期 | 已加入 雷池的续期脚本 的 `CERTS` 数组，`--cron` 到期自动重签+推送 |
| 孤儿行 | 证书 **65**（同日 18:20 早一次上传）已不被任何站点引用，下次推送由 `push-cert.py` 清理段删除；**不要手工绑回** |

**acme.sh 的两个硬要求**（少一个就签不出来）：

```bash
# 1) 必须显式指定 --server letsencrypt：默认 CA 是 ZeroSSL，而本机没注册账号，
#    会报 "Please update your account with an email address first" 直接失败。
# 2) 必须 --setenv=HOME=/root：否则 systemd-run 下 acme.sh 找不到自己的账户目录。
systemd-run --unit=acme-erp --collect --setenv=HOME=/root \
  acme.sh --issue --force --server letsencrypt \
  -d erp.finddatatech.cloud -w /var/www/acme
```

**雷池开放 API 的三个坑**（都实测过）：

- `POST /api/open/cert` **不能建 ACME 型证书**（JSON 报 "Content-Type isn't
  multipart/form-data"，multipart 报 "Error occurred when extracting params"）；
  只能 acme.sh 签好之后按 **manual** 上传：`{"manual":{"crt","key"},"type":2}`。
- `PUT /api/open/site` 里写 `is_enabled: false` **返回 200 但不生效**（`updated_at`
  变了、值没变）——别把 200 当成功，必须回读比对。
- `DELETE /api/open/site/{id}` 不存在（回 "404 page not found"）。想下线一个站点，
  只能在 Caddy 侧显式回 410（jenkins 就是这么处理的）。

## 内容发布（只这一条）

```bash
scp fd-erp/site/index.html fd-deploy:/opt/fd/erp/site/index.html
```

边缘不持有内容副本，所以**改内容不用碰 nginx / Caddy**。`site/index.html` 由
`fd-erp/tools/gen_erp_docs.py` 生成，禁止手改（CI 用 `artifact-lock.json` 拦）。

## 重新铺配置（换机器 / 配置丢失时）

```bash
# 1) 源站：准备目录
ssh fd-deploy 'sudo mkdir -p /opt/fd/erp/site && sudo chown -R ubuntu:ubuntu /opt/fd/erp'

# 2) 源站：erp 子域 server 块
scp fd-erp/deploy/host/nginx-erp-subdomain.conf fd-deploy:/tmp/erp.conf
ssh fd-deploy 'sudo install -m 644 /tmp/erp.conf /etc/nginx/sites-enabled/erp.finddatatech.cloud'

# 3) 源站：www 的 /erp-docs/ 片段（必须放在 location / 之前，幂等：先查再插）
ssh fd-deploy 'grep -q "location /erp-docs/" /etc/nginx/sites-enabled/www.finddatatech.cloud || echo "需手工插入片段"'

# 4) 两处都要：nginx -t 才 reload
ssh fd-deploy 'sudo nginx -t && sudo systemctl reload nginx'

# 5) 边缘：追加 Caddy 块（先备份，再 validate，最后 reload）
ssh root@<edge-host> 'cp -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date +%Y%m%d)'
scp fd-erp/deploy/host/caddy-erp-route.conf root@<edge-host>:/tmp/erp.caddy
ssh root@<edge-host> 'cat /tmp/erp.caddy >> /etc/caddy/Caddyfile && caddy validate --config /etc/caddy/Caddyfile && caddy reload --config /etc/caddy/Caddyfile'
```

## 验收（不看 200，看正文指纹）

```bash
# 源站
curl -s --resolve erp.finddatatech.cloud:80:<origin-host> http://erp.finddatatech.cloud/ | sha256sum
# 边缘
ssh root@<edge-host> 'curl -s -H "Host: erp.finddatatech.cloud" http://<edge-gateway>:8080/ | sha256sum'
# 公网
curl -s https://www.finddatatech.cloud/erp-docs/ | sha256sum
# 三者都必须等于本地 site/index.html 的 sha256
```

**再加一条 TLS 验收（不带 `-k`）**。带 `-k` 只能证明"有人在应答"，证明不了证书对得上：

```bash
echo | openssl s_client -connect erp.finddatatech.cloud:443 \
  -servername erp.finddatatech.cloud 2>/dev/null | openssl x509 -noout -subject -ext subjectAltName
# 必须 CN=erp.finddatatech.cloud，且 SAN 里有 DNS:erp.finddatatech.cloud
curl -s -o /dev/null -w 'erp %{http_code} %{size_download}\n' https://erp.finddatatech.cloud/
# 必须是 200 且 19000B 量级（空 body 说明站点还没配 443_ssl 或证书没绑上）
```

**外加一条：旁证一个别的域名。** 只验 erp 自己 200 是不够的——上面坑 2 的故障下
erp 恰恰仍是 200，而其它全站是空 200，所以"只验自己"的验收会给出假绿（2026-11-11
就是这么放了两次故障上线）。每次改完边缘配置，必须同时验一条**共享 :8080 的邻居**：

```bash
curl -s -o /dev/null -w 'lawbench/healthz %{http_code} %{size_download}\n' \
  https://lawbench.finddatatech.cloud/healthz   # 必须 200 且有非零 body（约 53B）
```

`tools/check_host_configs.py --live` 把这条和"地址集是否分叉"一起自动判。

## 坑（都踩过）

1. **nginx 备份不能留在 `sites-enabled/`** —— 该目录下所有文件都会被 include，
   备份会被当成第二份配置加载，`nginx -t` 报 `duplicate listen options`。
   备份放 `/root/` 或 `/etc/nginx/backups/`。
2. **绝对不要给单站点写 `bind 127.0.0.1 <edge-gateway>`** —— 这行曾两次把整个平台打白。

   Caddy 按**监听地址集**分组 server，不是按端口。给 erp 这一个站点写
   `bind 127.0.0.1 <edge-gateway>`，Caddy 会为这组地址单开一个 server（`srv1`），
   并把 `<edge-gateway>:8080` **从共享的 `:8080` server 里抢走**（更具体的地址胜出）。
   而雷池的转发目标恰好就是 `<edge-gateway>:8080` —— 于是所有
   `*.finddatatech.cloud` 的请求都落到 srv1 上，那里只有 erp 一条路由，
   其余 37 条路由的 host 匹配不上 → 返回**空 200**（`http=200 size=0`，不是 404、
   不是 502，所以任何"看状态码"的巡检都会说它是健康的）。

   实测：`srv1 ['127.0.0.1:8080','<edge-gateway>:8080'] routes=1` vs
   `srv2 [':8080'] routes=37`。

   **想让 :8080 少暴露**，用这两个办法之一，别用单站点 bind：
   - 不动 Caddy，在防火墙上收口：
     `iptables -I INPUT -p tcp --dport 8080 ! -s <edge-gateway> -j DROP`（雷池同机，
       源地址就是本机对外地址）；
   - 或者给**每一个** :8080 站点块写**同一组** bind（这样仍是一个 server）——
     38 个块要一起改，漏一个就复现上面的故障，所以不推荐。

   正本守卫：`tools/check_host_configs.py`（本地静态检查 `deploy/host/*.conf`，
   `--live` 还能连上边缘校验线上 Caddyfile 有没有出现地址集分叉）。
   `:9000` 那个 `bind <object-store-host>` 是安全的——该端口上只有它一个站点。
3. **`erp.finddatatech.cloud` 的公网入口在雷池** —— 雷池里没有该站点时，`:80` 返回
   雷池自己的 404 页（14591B）、`:443` 因 SNI 无匹配证书而握手失败（curl 000）。
   2026-11-11 已登记为站点 35 并配好证书，现状见上文「边缘 TLS」。
4. **雷池的 200 不等于改成功** —— `PUT /api/open/site` 写 `is_enabled` 会被静默忽略，
   `DELETE /api/open/site/{id}` 直接 404。每次 PUT 之后必须 **GET 回读逐字段比对**，
   否则「改完了」只是「请求发出去了」。
5. **空 200 的另一种来源**：Caddy 有 server 但**没有该 host 的路由**时也回空 200。
   jenkins 一直如此（服务早已下线，WAF 站点 27 还在转发），状态码巡检永远看不见。
   现已在该 host 上显式 `respond ... 410`，让残留书签和监控立刻看到「已删除」。
   判断口诀：**200 但 body 为 0，先问是"上游真回了空"还是"根本没有路由"**。
6. **显式回错误时，必须给 ACME 挑战路径开白闸** —— 给 jenkins 加 410 之后，
   `/.well-known/acme-challenge/*` 同属该 block，一起被 410 吃掉，于是 acme.sh 的
   HTTP-01 失败、每晚 cron 报错（实测撞过）。正确顺序是 challenge 的 `handle` 在前、
   `respond ... 410` 在后；改完立刻验一次：挑战路径应是 file_server 的 404（不是 410），
   根路径才是 410。同理适用于任何 403/404/维护页。
7. **多域证书里有一个死域名，整张证书都续不了** —— `file.finddatatech.cloud` 那张证书
   曾挂着 `rancher`/`harbor`（既无雷池站点、也无 Caddy 块，打过去是雷池自己的
   404/14591B），HTTP-01 永远失败 → 连续几晚 `Error renewing`，而证书 12-04 就到期。
   排查口诀：**续期失败先逐个域名 `curl http://<d>/`，回 `404/14591` 的就是没有 WAF 站点的
   死 SAN，从证书里摘掉**。
