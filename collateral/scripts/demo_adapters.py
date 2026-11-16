"""演示合成数据适配器（只读，零外部写入，零真实凭证）。

⚠️ 本文件所有业务记录均为演示合成数据（stable_id 带 DEMO-/d 前缀），
   不含任何真实客户数据、真实凭证；适配器只实现 read 面。
"""
from __future__ import annotations

from typing import Any

DAY = "2026-11-07"


def rec(rid: str, amount: str, *, day: str = DAY, currency: str = "CNY",
        status: str = "posted", raw: dict | None = None,
        side: str = "L") -> dict[str, Any]:
    return {"stable_id": rid, "amount": amount, "currency": currency,
            "status": status, "occurred_at": f"{day}T10:00:00",
            "source_ref": f"{side}:{rid}", "raw": raw or {}}


# ---------------------------------------------------------------------------
# 跨境：Demo Shop（合成 Shopify 店）订单/收款/库存三流
# ---------------------------------------------------------------------------

DEMO_ORDERS = [
    rec("DEMO-O-2001", "100.00", currency="USD", raw={"order_id": "DEMO-O-2001", "channel": "shopify"}),
    rec("DEMO-O-2002", "250.00", currency="USD", raw={"order_id": "DEMO-O-2002", "channel": "shopify"}),
    rec("DEMO-O-2003", "80.00", currency="USD", raw={"order_id": "DEMO-O-2003", "channel": "shopify"}),
    rec("DEMO-O-2004", "60.00", currency="USD", status="shipped",
        raw={"order_id": "DEMO-O-2004", "channel": "shopify"}),
]

DEMO_PAYMENTS = [
    rec("DEMO-P-2001", "100.00", currency="USD",
        raw={"order_id": "DEMO-O-2001", "fees": {"commission": "15", "payment_fee": "2"}}),
    rec("DEMO-P-2002", "240.00", currency="USD",
        raw={"order_id": "DEMO-O-2002"}),  # 金额不符：订单 250 收款 240
    rec("DEMO-P-2999", "500.00", currency="USD",
        raw={"order_id": "DEMO-X-999"}),   # 多出：收款无订单
]

DEMO_INVENTORY = [
    rec("DEMO-I-2001", "1", currency="EA", raw={"order_id": "DEMO-O-2001", "status": "deducted"}),
    rec("DEMO-I-2002", "1", currency="EA", raw={"order_id": "DEMO-O-2002", "status": "deducted"}),
    rec("DEMO-I-2003", "1", currency="EA", raw={"order_id": "DEMO-O-2003", "status": "deducted"}),
    # DEMO-O-2004 无库存扣减 → 在途（物流解释引用）
]

USD_FX_OBS = [{"quote_currency": "USD", "rate": "7.20", "as_of": DAY,
               "source": "ecb-exr", "base_currency": "CNY"}]


# ---------------------------------------------------------------------------
# 餐饮：门店 A（加盟）合成 POS/收款渠道/外卖结算
# ---------------------------------------------------------------------------

class DemoPos:
    vendor = "demo-pos-synthetic"  # 演示合成 POS（真实厂商适配器待首单客户定）

    def __init__(self, flows: list[dict]):
        self._flows = flows

    def read_day_flows(self, store_id: str, day: str) -> list[dict]:
        return [f for f in self._flows if f.get("day", DAY) == day]


class DemoWechat:
    channel = "wechat-pay"

    def read_settlements(self, store_id: str, day: str) -> list[dict]:
        return [rec("DEMO-wa1", "120.5", side="R", raw={"fee": "0.6"}),
                rec("DEMO-wa2", "44", side="R", raw={"fee": "0.2"})]  # 金额不符：流水 45


class DemoAlipay:
    channel = "alipay"

    def read_settlements(self, store_id: str, day: str) -> list[dict]:
        return [rec("DEMO-aa1", "80", side="R", raw={"fee": "0.3"})]


class DemoMeituanDelivery:
    channel = "meituan"

    def read_settlements(self, store_id: str, day: str) -> list[dict]:
        # 外卖结算：佣金 20/220，费率出处未配置 → unexplained
        return [rec("DEMO-ma1", "200", side="R",
                    raw={"fee": "20", "order_amount": "220"})]


def demo_pos_store_a() -> DemoPos:
    return DemoPos([
        rec("DEMO-pa1", "120.5", raw={"channel": "wechat-pay"}),
        rec("DEMO-pa2", "80", raw={"channel": "alipay"}),
        rec("DEMO-pa3", "45", raw={"channel": "wechat-pay"}),
    ])
