"""开张验收脚本测试（change establish-ai-native-ecommerce-stack 5.3）。

spec `ecommerce-tenant-provisioning`：「已开张」以一次真实匿名下单链路为判据，
MUST NOT 以部署成功/构建成功/配置存在作为开张证据。

这组测试守的是「这条判据真的会红」——一个永远返回 ok 的验收脚本比没有更糟。
用假 HTTP 层替掉网络，判据逻辑本身照真跑。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import verify_shop_opening as vso  # type: ignore  # noqa: E402

BASE = "http://shop.test"


def _patch(monkeypatch, responses: dict):
    """responses: {(method, path_suffix): (status, body)}。未登记的路径即测试失败。"""
    def fake(method, url, body=None, headers=None, timeout=20):
        for (m, suffix), resp in responses.items():
            if m == method and url.endswith(suffix):
                return resp
        raise AssertionError(f"未预期的请求：{method} {url}")
    monkeypatch.setattr(vso, "_req", fake)


PRODUCT = {"productId": "SKU-1", "title": "商品", "unit_price": "88",
           "currency": "CNY", "price_source": "retail/price-list/v1"}


def test_four_steps_pass_means_opened(monkeypatch):
    _patch(monkeypatch, {
        ("GET", "/shop/acme/products?limit=5"): (200, {"ok": True, "data": [PRODUCT]}),
        ("POST", "/shop/acme/orders"): (200, {"ok": True, "data": {
            "order_ref": "SO-1", "amount_total": "88", "currency": "CNY",
            "settlement_mode": "prepaid", "payment_state": "awaiting_payment"}}),
        ("POST", "/shop/acme/orders/SO-1/payment"): (200, {"ok": True, "data": {
            "received": True, "requires_posting": False}}),
        ("GET", "/shop/acme/orders/SO-1"): (200, {"ok": True, "data": {
            "status": "pending", "payment_state": "received"}}),
    })
    r = vso.verify(BASE, "acme")
    assert r["opened"] is True
    assert [s["ok"] for s in r["steps"]] == [True] * 4


def test_empty_catalog_means_not_opened(monkeypatch):
    """店面关闭 / 无货 → 第 1 步就红，且不继续往下打。"""
    _patch(monkeypatch, {
        ("GET", "/shop/acme/products?limit=5"): (200, {"ok": True, "data": []}),
    })
    r = vso.verify(BASE, "acme")
    assert r["opened"] is False
    assert len(r["steps"]) == 1
    assert "零售渠道" in r["steps"][0]["reason"]


def test_leaked_internal_fields_block_opening(monkeypatch):
    """公开读面带内部口径（entity_id / 成本 / 供应商）即不算开张。"""
    _patch(monkeypatch, {
        ("GET", "/shop/acme/products?limit=5"): (200, {"ok": True, "data": [
            {**PRODUCT, "entity_id": "abc", "base_price": "10"}]}),
    })
    r = vso.verify(BASE, "acme")
    assert r["opened"] is False
    assert set(r["steps"][0]["leak"]) == {"entity_id", "base_price"}


def test_order_not_prepaid_blocks(monkeypatch):
    """下单没按预付走（或没返回 payment_state）即不算。"""
    _patch(monkeypatch, {
        ("GET", "/shop/acme/products?limit=5"): (200, {"ok": True, "data": [PRODUCT]}),
        ("POST", "/shop/acme/orders"): (200, {"ok": True, "data": {
            "order_ref": "SO-1", "amount_total": "88", "settlement_mode": "credit"}}),
    })
    r = vso.verify(BASE, "acme")
    assert r["opened"] is False
    assert r["steps"][1]["step"] == "2-place-order"


def test_payment_posting_true_blocks(monkeypatch):
    """到账事实若 requires_posting=true（平台落了分录）即不算——钱不该进我们的账。"""
    _patch(monkeypatch, {
        ("GET", "/shop/acme/products?limit=5"): (200, {"ok": True, "data": [PRODUCT]}),
        ("POST", "/shop/acme/orders"): (200, {"ok": True, "data": {
            "order_ref": "SO-1", "amount_total": "88", "currency": "CNY",
            "settlement_mode": "prepaid", "payment_state": "awaiting_payment"}}),
        ("POST", "/shop/acme/orders/SO-1/payment"): (200, {"ok": True, "data": {
            "received": True, "requires_posting": True}}),
    })
    r = vso.verify(BASE, "acme")
    assert r["opened"] is False
    assert r["steps"][2]["step"] == "3-record-payment"


def test_payment_not_received_blocks_fourth_step(monkeypatch):
    """到账没落（payment_state 仍是 awaiting）→ 第 4 步红。"""
    _patch(monkeypatch, {
        ("GET", "/shop/acme/products?limit=5"): (200, {"ok": True, "data": [PRODUCT]}),
        ("POST", "/shop/acme/orders"): (200, {"ok": True, "data": {
            "order_ref": "SO-1", "amount_total": "88", "currency": "CNY",
            "settlement_mode": "prepaid", "payment_state": "awaiting_payment"}}),
        ("POST", "/shop/acme/orders/SO-1/payment"): (200, {"ok": True, "data": {
            "received": True, "requires_posting": False}}),
        ("GET", "/shop/acme/orders/SO-1"): (200, {"ok": True, "data": {
            "status": "pending", "payment_state": "awaiting_payment"}}),
    })
    r = vso.verify(BASE, "acme")
    assert r["opened"] is False
    assert r["steps"][3]["step"] == "4-ready-for-fulfillment"


def test_cli_exit_codes(monkeypatch, capsys):
    _patch(monkeypatch, {
        ("GET", "/shop/acme/products?limit=5"): (200, {"ok": True, "data": []}),
    })
    assert vso.main(["--base", BASE, "--tenant", "acme"]) == 1

    _patch(monkeypatch, {
        ("GET", "/shop/acme/products?limit=5"): (200, {"ok": True, "data": [PRODUCT]}),
        ("POST", "/shop/acme/orders"): (200, {"ok": True, "data": {
            "order_ref": "SO-1", "amount_total": "88", "currency": "CNY",
            "settlement_mode": "prepaid", "payment_state": "awaiting_payment"}}),
        ("POST", "/shop/acme/orders/SO-1/payment"): (200, {"ok": True, "data": {
            "received": True, "requires_posting": False}}),
        ("GET", "/shop/acme/orders/SO-1"): (200, {"ok": True, "data": {
            "status": "pending", "payment_state": "received"}}),
    })
    capsys.readouterr()          # 清掉上一次非 json 调用的输出
    assert vso.main(["--base", BASE, "--tenant", "acme", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["opened"] is True
