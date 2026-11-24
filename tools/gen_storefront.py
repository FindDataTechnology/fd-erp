#!/usr/bin/env python3
"""店面静态产物生成器（change establish-ai-native-ecommerce-stack 0.14/0.15）。

**零网络、零 npm**：只读 `shared/storefront-snapshot.json`，产出静态 HTML。
为什么不用 Astro：两个既有对外站（fd-erp/site、fd-marketing-web）已经证明
「Python 生成 + 静态托管」这条路在本仓能跑；而本机只有 8 GB，npm 构建会把
swap 顶满（用户明令禁止本地 build）。店面产物只需「展示快照」，不需要框架。

快照由 `tools/collect_storefront_snapshot.py` 从**运行中的 API**拉取：
  ① GET /shop/{tenant}/products（匿名读面，公开安全）；
  ② 不拉订单：订单是买家的，落盘到静态产物里就是泄露。
所以本产物只展示「有什么可卖」，下单走 API（浏览器直接 POST）。

**缺位如实**（0.15）：快照里 `products` 为空、或 `available=false`（采集没跑通）
时，页面展示「暂无在售商品 + 原因」，**MUST NOT** 摆样例商品或占位价。
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import date
from pathlib import Path

FD_ERP = Path(__file__).resolve().parents[1]
ROOT = FD_ERP.parent
SNAPSHOT = FD_ERP / "shared" / "storefront-snapshot.json"
OUT = FD_ERP / "site" / "shop"

CSS = """
:root{--ink:#16211d;--ink2:#46564e;--ink3:#525f58;--paper:#fbfaf7;
--rule:#e2e0d8;--accent:#1f5c46;--mono:ui-monospace,SFMono-Regular,Menlo,monospace;}
*{box-sizing:border-box;}
body{margin:0;background:var(--paper);color:var(--ink);
font:16px/1.65 system-ui,-apple-system,"Noto Sans SC",sans-serif;}
.wrap{max-width:960px;margin:0 auto;padding:32px 20px 64px;}
header{border-bottom:1px solid var(--rule);padding-bottom:20px;margin-bottom:28px;}
h1{font-size:28px;font-weight:600;margin:0 0 6px;}
.sub{color:var(--ink3);font-size:14px;}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:20px;}
.card{border:1px solid var(--rule);border-radius:3px;background:#fff;overflow:hidden;}
.card img{width:100%;height:170px;object-fit:cover;display:block;background:#f2f1ea;}
.card .body{padding:14px 16px 18px;}
.card h2{font-size:16px;font-weight:600;margin:0 0 4px;}
.card .cat{color:var(--ink3);font-size:12px;}
.price{margin-top:10px;font-family:var(--mono);font-size:18px;color:var(--accent);}
.price small{font-size:12px;color:var(--ink3);margin-left:6px;}
.card button{margin-top:12px;width:100%;padding:9px 12px;border:1px solid var(--accent);
border-radius:2px;background:var(--accent);color:#fff;font:inherit;font-size:14px;cursor:pointer;}
.card button:disabled{opacity:.5;cursor:default;}
form.order{border:1px solid var(--rule);border-radius:3px;background:#fff;padding:20px;
margin-top:28px;}
form.order h2{font-size:18px;margin:0 0 4px;}
form.order .hint{color:var(--ink3);font-size:13px;margin-bottom:14px;}
form.order label{display:block;margin:10px 0 4px;font-size:13px;color:var(--ink2);}
form.order input{width:100%;padding:8px 10px;border:1px solid var(--rule);border-radius:2px;
font:inherit;font-size:14px;}
form.order .row{display:grid;grid-template-columns:1fr 1fr;gap:12px;}
form.order button{margin-top:16px;padding:10px 18px;border:1px solid var(--accent);
border-radius:2px;background:var(--accent);color:#fff;font:inherit;cursor:pointer;}
#order-result{margin-top:16px;font-size:14px;white-space:pre-wrap;}
#order-result.err{color:#a33;}
#order-result.ok{color:var(--accent);}
.empty{border:1px dashed var(--rule);border-radius:3px;padding:40px 20px;text-align:center;
color:var(--ink3);}
.empty strong{display:block;color:var(--ink);font-size:18px;margin-bottom:8px;}
.note{margin-top:28px;font-size:12.5px;color:var(--ink3);border-top:1px solid var(--rule);
padding-top:14px;}
"""


def _order_form() -> str:
    """下单表单 + 提交脚本。

    为什么表单在页面里而数据不在：页面是静态产物（可缓存、可私域部署），
    但下单必须打 API —— 所以只带**接口地址**（`api_base`，从快照来），不带任何
    订单数据。买家填的收货信息只经浏览器直接 POST 给 API，不经过本页任何存储。
    """
    return """
<form class="order" id="order-form">
  <h2>下单</h2>
  <div class="hint">预付单：提交后本店会告知付款方式，钱进本店自有账户，平台不经手资金。</div>
  <div class="row">
    <div><label for="ship-name">收货人</label><input id="ship-name" name="name" required></div>
    <div><label for="ship-phone">联系电话</label><input id="ship-phone" name="phone" required></div>
  </div>
  <label for="ship-address">收货地址</label><input id="ship-address" name="address">
  <div class="row">
    <div><label for="line-code">商品编码</label><input id="line-code" name="code" required></div>
    <div><label for="line-qty">数量</label><input id="line-qty" name="qty" type="number" min="1" value="1" required></div>
  </div>
  <button type="submit" id="order-submit">提交订单</button>
  <div id="order-result" role="status" aria-live="polite"></div>
</form>
<script>
(function () {
  var API = document.body.dataset.api;
  var tenant = document.body.dataset.tenant;
  var form = document.getElementById("order-form");
  var out = document.getElementById("order-result");
  var submit = document.getElementById("order-submit");
  // 「加入订单」把编码填进表单：不引入购物车状态，页面保持无状态
  document.querySelectorAll("[data-add]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.getElementById("line-code").value = btn.getAttribute("data-add");
      document.getElementById("line-qty").focus();
    });
  });
  form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    if (!API || !tenant) {
      out.className = "err";
      out.textContent = "本页未配置店面接口地址，无法提交订单。";
      return;
    }
    submit.disabled = true;
    out.className = "";
    out.textContent = "提交中…";
    try {
      var res = await fetch(API.replace(/\\/+$/, "") + "/shop/" + encodeURIComponent(tenant) + "/orders", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "idempotency-key": "web-" + Date.now() + "-" + Math.random().toString(36).slice(2)
        },
        body: JSON.stringify({
          lines: [{ productId: form.code.value.trim(), qty: Number(form.qty.value) }],
          shipTo: { name: form.name.value.trim(), phone: form.phone.value.trim(), address: form.address.value.trim() }
        })
      });
      var body = await res.json();
      if (!res.ok || !body.ok) {
        var err = (body && body.error) || {};
        out.className = "err";
        out.textContent = "下单未成功：" + (err.message || res.status) +
          (err.detail && err.detail.missing ? "（缺 " + err.detail.missing + "）" : "");
        return;
      }
      var d = body.data;
      out.className = "ok";
      out.textContent = "已受理。订单号 " + d.order_ref + "，金额 " + d.amount_total + " " +
        d.currency + "。当前状态：待付款——付款方式由本店另行告知。";
    } catch (e) {
      out.className = "err";
      out.textContent = "网络错误：" + (e && e.message ? e.message : e);
    } finally {
      submit.disabled = false;
    }
  });
})();
</script>
"""


def _esc(v) -> str:
    return html.escape(str(v if v is not None else ""))


def render(snapshot: dict) -> str:
    products = snapshot.get("products") or []
    reason = snapshot.get("reason") or ""
    as_of = snapshot.get("as_of") or ""
    shop = snapshot.get("shop") or {}
    title = shop.get("title") or "网上商店"
    note = shop.get("note") or ""
    # 接口地址与租户来自快照（**不含任何订单/买家数据**），用于页内下单表单。
    # 二者为空时不出表单：宁可不给入口，也不给一个点了必然失败的按钮。
    api_base = str(snapshot.get("api_base") or "").strip()
    tenant = str(snapshot.get("tenant") or "").strip()

    body: list[str] = []
    if not snapshot.get("available", False):
        body.append('<div class="empty"><strong>暂无在售商品</strong>'
                    f'<span>{_esc(reason or "取数通道未接通")}</span></div>')
    elif not products:
        body.append('<div class="empty"><strong>暂无在售商品</strong>'
                    f'<span>{_esc(reason or "该渠道当前没有已上架且有零售价的商品")}</span></div>')
    else:
        body.append('<div class="grid">')
        for p in products:
            img = (p.get("images") or [None])[0]
            code = _esc(p.get("productId"))
            body.append(f'<article class="card" data-product="{code}">')
            if img:
                # 相对路径：私域/内网部署时绝对 URL 会失效（0.16 验收项之一）
                body.append(f'<img src="{_esc(img)}" alt="{_esc(p.get("title"))}" loading="lazy">')
            body.append(f'<div class="body"><h2>{_esc(p.get("title"))}</h2>'
                        f'<span class="cat">{_esc(p.get("category"))}</span>'
                        f'<div class="price">{_esc(p.get("unit_price"))}'
                        f'<small>{_esc(p.get("currency"))}</small></div>'
                        + (f'<button type="button" data-add="{code}">加入订单</button>'
                           if api_base else '')
                        + '</div>')
            body.append("</article>")
        body.append("</div>")
        if api_base:
            body.append(_order_form())

    as_of_line = (f'<span class="sub">数据期 {_esc(as_of[:10])}</span>' if as_of else "")
    return "\n".join([
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f'<title>{_esc(title)}</title><style>{CSS}</style></head>',
        f'<body data-api="{_esc(api_base)}" data-tenant="{_esc(tenant)}"><div class="wrap">',
        '<header>',
        f'<h1>{_esc(title)}</h1>',
        f'<div class="sub">{_esc(note)}</div>{as_of_line}',
        '</header>',
        *body,
        '<div class="note">'
        '本页是静态快照：商品与价格由店面 API 的公开读面导出，'
        '页面只展示「当前可售」的商品。下单经同一 API 提交（预付单，钱进商家自有账户，'
        '平台不经手资金）。无可售商品时如实标注，不摆样例，不写占位价。'
        '</div>',
        '</div></body></html>',
    ]) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="店面静态产物生成器（只读快照）")
    ap.add_argument("--snapshot", default=str(SNAPSHOT))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--check", action="store_true", help="只比对不落盘")
    args = ap.parse_args(argv)

    snap_path = Path(args.snapshot)
    if not snap_path.is_file():
        print(f"判不出：快照不存在（{snap_path}）——先跑 collect_storefront_snapshot.py")
        return 2
    try:
        snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"判不出：快照不是合法 JSON（{exc}）")
        return 2

    page = render(snapshot)
    target = Path(args.out) / "index.html"
    if args.check:
        if not target.is_file():
            print(f"产物不存在：{target}——先跑一次生成")
            return 1
        if target.read_text(encoding="utf-8") != page:
            print(f"产物与快照不一致：{target}（快照变过但没重新生成）")
            return 1
        print(f"一致：{target}")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding="utf-8")
    print(f"写入 {target}（{len(page)} 字节，{len(snapshot.get('products') or [])} 件商品）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
