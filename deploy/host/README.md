# fd-erp 的宿主机侧配置（版本化副本）

这三段配置原本只存在于机器上（宿主机 nginx 配置**不在任何仓里**）。重装、重铺配置、
或换一台源站，改动就无声消失。所以把线上实际内容拉回这里做版本化副本。

| 文件 | 落点 | 用途 |
|---|---|---|
| `nginx-erp-subdomain.conf` | `fd-deploy:/etc/nginx/sites-enabled/erp.finddatatech.cloud` | `erp.finddatatech.cloud` 静态站（:80；TLS 由前置雷池终止） |
| `nginx-www-erp-docs.snippet.conf` | 插进 `fd-deploy:/etc/nginx/sites-enabled/www.finddatatech.cloud` 的 `location / {` 之前 | `www.finddatatech.cloud/erp-docs/`（当前**唯一公网可用**路径，复用 www 证书） |
| `caddy-erp-route.conf` | 追加到 `root@103.236.89.212:/etc/caddy/Caddyfile` | 雷池同机 Caddy 按 Host 转发到源站 124.220.7.175:80 |

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
ssh root@103.236.89.212 'cp -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date +%Y%m%d)'
scp fd-erp/deploy/host/caddy-erp-route.conf root@103.236.89.212:/tmp/erp.caddy
ssh root@103.236.89.212 'cat /tmp/erp.caddy >> /etc/caddy/Caddyfile && caddy validate --config /etc/caddy/Caddyfile && caddy reload --config /etc/caddy/Caddyfile'
```

## 验收（不看 200，看正文指纹）

```bash
# 源站
curl -s --resolve erp.finddatatech.cloud:80:124.220.7.175 http://erp.finddatatech.cloud/ | sha256sum
# 边缘
ssh root@103.236.89.212 'curl -s -H "Host: erp.finddatatech.cloud" http://172.22.222.1:8080/ | sha256sum'
# 公网
curl -s https://www.finddatatech.cloud/erp-docs/ | sha256sum
# 三者都必须等于本地 site/index.html 的 sha256
```

## 坑（都踩过）

1. **nginx 备份不能留在 `sites-enabled/`** —— 该目录下所有文件都会被 include，
   备份会被当成第二份配置加载，`nginx -t` 报 `duplicate listen options`。
   备份放 `/root/` 或 `/etc/nginx/backups/`。
2. **Caddy 块要写 `bind 127.0.0.1 172.22.222.1`** —— 不写就在所有网卡应答 :8080，
   暴露面比需要的宽。雷池转发目标就是 `172.22.222.1:8080`。
3. **`erp.finddatatech.cloud` 的公网入口在雷池** —— 雷池里没有该站点时，`:80` 返回
   雷池自己的 404 页、`:443` 因 SNI 无匹配证书而握手失败。这一段本仓代办不了
   （控制台需登录凭据，且那台没有 OpenAPI token）。
