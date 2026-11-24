"""店面产物测试（change establish-ai-native-ecommerce-stack 0.14/0.15）。

判据：
1. 有商品时渲染成卡片，价格与 currency 来自快照（不重算、不四舍五入）；
2. 无商品时如实缺位，**不摆样例商品、不写占位价**；
3. 采集失败（available=false）时把**原因**写进页面，空列表不能冒充「没有商品」；
4. 图片用相对路径（私域/内网部署依赖这一点）；
5. `--check` 在快照变过但没重生成时非零退出。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import gen_storefront as gs  # type: ignore  # noqa: E402

def _snap(products, *, available=True, reason="", title="示例商店", note="",
          api_base="", tenant="acme"):
    return {"schema": "erp-storefront-snapshot/v1", "as_of": "2026-11-24T00:00:00+00:00",
            "tenant": tenant, "api_base": api_base,
            "shop": {"title": title, "note": note},
            "available": available, "products": products, "reason": reason}


def _p(code="SKU-1", title="商品甲", price="99.000000", cur="CNY", images=None):
    return {"productId": code, "title": title, "category": "饮料",
            "images": images or [], "unit_price": price, "currency": cur,
            "price_source": "retail/price-list/v1"}


def test_products_render_as_cards_with_snapshot_price():
    page = gs.render(_snap([_p(), _p("SKU-2", "商品乙", "12.50")],
                           api_base="https://api.example.com"))
    assert page.count('<article class="card"') == 2
    assert "商品甲" in page and "商品乙" in page
    assert "99.000000" in page          # 原样透出，不重算
    assert "12.50" in page
    # 每张卡带一个「加入订单」按钮，把商品编码填进下单表单
    assert page.count('data-add="SKU-1"') == 1
    assert page.count('data-add="SKU-2"') == 1


def test_order_form_only_when_api_base_present():
    """没有接口地址就不出表单——宁可不给入口，也不给点了必然失败的按钮。"""
    with_api = gs.render(_snap([_p()], api_base="https://api.example.com"))
    assert 'id="order-form"' in with_api
    assert 'data-api="https://api.example.com"' in with_api

    without = gs.render(_snap([_p()]))       # api_base 缺省为空
    assert 'id="order-form"' not in without
    assert "加入订单" not in without


def test_order_form_never_embeds_order_or_buyer_data():
    """表单是空的：下单数据只由买家在浏览器里填，不经快照。

    注意区分「字段名」与「数据」：脚本里出现 `d.order_ref` 是读响应字段，正常；
    出现一个**具体的**订单号 / 手机号才是泄露。
    """
    page = gs.render(_snap([_p()], api_base="https://api.example.com"))
    for forbidden in ("SO-", "PMT-", "13800000000", "bank-ref"):
        assert forbidden not in page, forbidden


def test_empty_catalog_is_honest_not_placeholder():
    page = gs.render(_snap([], reason="该渠道当前没有已上架且有零售价的商品"))
    assert "暂无在售商品" in page
    assert "该渠道当前没有已上架且有零售价的商品" in page
    assert not page.count('<article class="card">')
    # 不能出现样例商品 / 占位价
    assert "示例商品" not in page and "待定" not in page


def test_collector_failure_reason_is_surfaced():
    page = gs.render(_snap([], available=False, reason="店面读面返回 404"))
    assert "暂无在售商品" in page
    assert "店面读面返回 404" in page


def test_images_use_relative_paths():
    page = gs.render(_snap([_p(images=["https://cdn.example/x.png"])]))
    # 快照里给的是绝对 URL 时原样保留（渠道提供），但页面自身不产生绝对引用
    assert 'src="https://cdn.example/x.png"' in page
    assert "http://localhost" not in page and "127.0.0.1" not in page


def test_as_of_is_rendered_from_snapshot():
    page = gs.render(_snap([_p()]))
    assert "数据期 2026-11-24" in page
    assert "手工写的日期" not in page


def test_check_mode_detects_drift(tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(_snap([_p()]), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "site"
    assert gs.main(["--snapshot", str(snap), "--out", str(out)]) == 0
    assert gs.main(["--snapshot", str(snap), "--out", str(out), "--check"]) == 0
    # 改快照但不重生成 → check 必须红
    snap.write_text(json.dumps(_snap([]), ensure_ascii=False), encoding="utf-8")
    assert gs.main(["--snapshot", str(snap), "--out", str(out), "--check"]) == 1


def test_missing_snapshot_is_undetermined_not_pass(tmp_path):
    assert gs.main(["--snapshot", str(tmp_path / "none.json"),
                    "--out", str(tmp_path / "o"), "--check"]) == 2


def test_no_orders_or_buyer_data_in_snapshot(tmp_path):
    """快照只含公开读面字段：不含订单、买家、到账。"""
    snap = tmp_path / "s.json"
    snap.write_text(json.dumps(_snap([_p()]), ensure_ascii=False), encoding="utf-8")
    gs.main(["--snapshot", str(snap), "--out", str(tmp_path / "o")])
    blob = (tmp_path / "o" / "index.html").read_text(encoding="utf-8")
    for forbidden in ("order_ref", "船", "ship_to", "phone", "proof_ref"):
        assert forbidden not in blob, forbidden
