"""餐饮连锁客户演示：门店建档（确认车道）→ 门店日结（日报三段）
→ 差异拍板 → 白名单回写 → 分成对账单（零资金执行面）→ 资金红线表演。

运行前提：demo_env.sh 已拉起（内核 8302=demo-restaurant）。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from demo_common import (REST_URL, TENANT_REST, balance_by_code, load_env,
                         make_kernel, rule, show, step, unwrap)
from demo_adapters import (DemoAlipay, DemoMeituanDelivery, DemoPos,
                           DemoWechat, demo_pos_store_a)

load_env()


def main() -> None:
    from fd_erp_vertical_templates.stores import StoreMasterData
    from fd_erp_vertical_templates.recon.restaurant import StoreDailyClose
    from fd_erp_vertical_templates.recon.shares import (
        assert_no_execution, build_share_statement,
        build_verification_instructions)
    from fd_erp_vertical_templates.recon.writeback import (
        writeback_recon_conclusion)
    from fd_erp_vertical_templates.kernel_client import McpKernelClient

    k = make_kernel(REST_URL, TENANT_REST)

    # ================= 门店建档 =================
    rule("第 1 章 · 门店主数据建档（每一步都走确认车道，留痕可查）")
    with tempfile.TemporaryDirectory() as td:
        md = StoreMasterData(TENANT_REST, Path(td) / "master-data")
        step("1.1 新建门店 A（加盟店）→ 待确认")
        st_a = md.create_entity("store", {"name": "演示奶茶店·中山公园店",
                                          "operation_mode": "franchise"})
        show(st_a, keys=["entity_id", "state", "request_id"],
             note="建档是 request，等确认")
        md.confirm_request(st_a["request_id"])
        step("1.2 owner 确认 → 开业生命周期")
        md.set_lifecycle(st_a["entity_id"], "open")
        md.confirm_request(md.pending_requests()[0]["request_id"])
        stores = md.list_entities(kind="store", state="open")
        show({"open_stores": [s["entity_id"] for s in stores]},
             note="未开业的门店不参与日结")

        # ================= 门店日结 =================
        rule("第 2 章 · 门店日结（POS 流水 ↔ 微信/支付宝 ↔ 美团外卖，三方逐笔）")
        close_a = StoreDailyClose(
            st_a["entity_id"], pos_adapter=demo_pos_store_a(),
            channel_adapters={"wechat-pay": DemoWechat(), "alipay": DemoAlipay()},
            delivery_adapter=DemoMeituanDelivery())
        step("2.1 日结：日报三段（流水 / 收款 / 差异）")
        daily_a = close_a.daily_close("2026-11-07")
        sections = daily_a["report"]
        show({"pos_total": sections["flows"]["pos_total"],
              "wechat_fee_total": sections["receipts"]["wechat-pay"]["fee_total"]},
             note="流水段汇总 POS 营业额；收款段汇总各渠道结算与手续费")
        step("2.2 差异清单（每条含双侧原始引用 + 解释提示）")
        for d in sections["diffs"]["items"]:
            show(d, keys=["kind", "pair", "left_ref", "right_ref",
                          "explanation_hint"])
        print(f"  ↳ 差异共 {sections['diffs']['diff_count']} 条："
              f"人工对账每天一小时，这里三秒出清单")

        # ================= 拍板回写 =================
        rule("第 3 章 · 差异拍板 → 白名单车道回写 → 确认门落账")
        mismatch = next(d for d in sections["diffs"]["items"]
                        if d["kind"] == "amount_mismatch"
                        and d.get("pair") == "pos↔wechat-pay")
        lines = close_a.propose_correction_lines(mismatch)
        proposal = writeback_recon_conclusion(
            k, tenant_id=TENANT_REST, fleet="rest-dailyclose-fleet",
            post="reconciler", title="核对岗", diff=mismatch,
            proposal_lines=lines,
            decision_note="演示：微信 45 元流水结算 44 元，差额 1 元挂应收更正")
        show(proposal, keys=["proposal_id", "status", "stable_id"],
             note="机器车道只挂应收（1300），禁写资金类科目")
        unwrap(k.confirm_proposal(proposal_id=proposal["proposal_id"],
                                  confirmed_by="owner"))
        show({"1300": balance_by_code(k, "1300")},
             note="差额 1 元入账，append-only 可追溯")

        # ================= 分成核对 =================
        rule("第 4 章 · 加盟分成：只出对账单与核对指令，零资金执行面")
        statement = build_share_statement(
            period="2026-11-07", brand="demo-brand", franchisee="demo-operator",
            daily_results=[daily_a],
            share_terms={"brand_rate": "0.20",
                         "rate_source": "加盟协议 DEMO-2026-001"})
        show(statement, keys=["period", "rows", "totals"],
             note="费率带协议出处——无出处的分成口径双方没法核对，直接拒")
        instructions = build_verification_instructions(statement)
        show({"instructions": len(instructions)},
             note="核对指令数据：对接品牌方自选持牌分账产品的输入")
        assert_no_execution(statement)
        print("  ✓ assert_no_execution 通过：对账单不含任何资金执行字段")

        step("4.1 资金红线表演：核对结论出现「自动打款」→ 现场拒绝")
        try:
            writeback_recon_conclusion(
                k, tenant_id=TENANT_REST, fleet="rest-dailyclose-fleet",
                post="reconciler", title="核对岗", diff=mismatch,
                proposal_lines=lines,
                decision_note="演示：品牌分成由平台自动打款给加盟商")
            print("  ✗ 意外：未被拒绝（不应发生）")
        except Exception as e:  # noqa: BLE001
            print(f"  ✓ 拒绝生效：{getattr(e, 'code', type(e).__name__)}: "
                  f"{str(e)[:80]}")
        print("  ↳ 平台不经手资金：划转由品牌方经持牌通道执行（二清红线）")

    rule("演示结束 · 餐饮连锁线（全部数字来自本次真实调用）")


if __name__ == "__main__":
    main()
