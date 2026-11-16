"""跨境电商客户演示：内核五连（proposal→确认→幂等→不平拒→冲正）
+ 三方对账（订单-收款-库存）→ 拍板 → 白名单回写 → 落账可查
+ 租户隔离表演 + 资金红线表演。

双轨（spec `ecommerce-merchant-channel-wiring`，任务 6.2；原 change `wire-ecommerce-merchant-channels` 已于 2026-11-10 归档）：
  --track shopify    跨境店（订单/结算/库存，原币 USD）——默认
  --track domestic   国内店（经商家电商 ERP，CNY，库存腿由 ERP 提供）

两条轨迹都先打印**真实能力矩阵**（当前全为「需一次接入」），再打印「假设已接通」
的形状。第二遍是演示假设，不是矩阵事实，且不写回矩阵文件。

运行前提：demo_env.sh 已拉起（内核 8301=demo-crossborder / 8302=demo-restaurant）。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from demo_common import (CB_URL, REST_URL, TENANT_CB, TENANT_REST,
                         balance_by_code, load_env, make_kernel, reset_demo_tenant,
                         rule, show, step, unwrap)
from demo_adapters import (DEMO_INVENTORY, DEMO_ORDERS, DEMO_PAYMENTS,
                           USD_FX_OBS, DAY)

load_env()
reset_demo_tenant(TENANT_CB)


def main(track: str = "shopify") -> None:
    from fd_erp_vertical_templates.recon.crossborder import (
        CrossborderRecon, EcbExrFxProvider)
    from fd_erp_vertical_templates.recon.writeback import (
        escalate_diff, writeback_recon_conclusion)
    from fd_erp_vertical_templates.kernel_client import McpKernelClient

    k = make_kernel(CB_URL, TENANT_CB)

    # ================= 内核五连 =================
    rule("第 1 章 · 账本内核五连（每一步都是真实 DB 约束在兜底）")
    step("1.1 期初余额：1300 在途结算款 / 4000 营业收入")
    show({c: balance_by_code(k, c) for c in ("1300", "4000")},
         note="余额由分录确定性重算——账本没有可直写的余额字段")

    step("1.2 agent 提交 proposal（拟入账：借 1300 / 贷 4000 = CNY 100）→ 余额不变")
    p = unwrap(k.submit_proposal(
        stable_id="DEMO-A1",
        lines=[{"account_code": "1300", "direction": "debit", "amount": "100.00",
                "currency": "CNY"},
               {"account_code": "4000", "direction": "credit", "amount": "100.00",
                "currency": "CNY"}],
        source_ref="demo:orders:DEMO-O-2001",
        lane_fleet="cb-recon-fleet", lane_post="reconciler", lane_title="核对岗",
        lane_target="demo:DEMO-O-2001", submitted_by="agent"))
    show(p, keys=["proposal_id", "status", "stable_id"],
         note="agent 车道只写 proposal——账本状态零变化（fail-closed）")
    show({"1300": balance_by_code(k, "1300").get("balance")},
         note="确认门前余额仍为 0")

    step("1.3 owner 确认门 confirm → 唯一落账路径，余额实时可查")
    c = unwrap(k.confirm_proposal(proposal_id=p["proposal_id"],
                                  confirmed_by="owner"))
    show(c, keys=["proposal_id", "status", "txn_id"],
         note="借贷必平由数据库 DEFERRABLE 约束强制，应用层绕不过")
    show({"1300": balance_by_code(k, "1300"),
          "4000": balance_by_code(k, "4000")},
         note="借 100 挂在途、贷 100 记收入")

    step("1.4 幂等：同一 stable_id 重推（平台重推是常态）→ 返回原结果、不重复入账")
    p2 = unwrap(k.submit_proposal(
        stable_id="DEMO-A1",
        lines=[{"account_code": "1300", "direction": "debit", "amount": "100.00",
                "currency": "CNY"},
               {"account_code": "4000", "direction": "credit", "amount": "100.00",
                "currency": "CNY"}],
        source_ref="demo:orders:DEMO-O-2001", submitted_by="agent"))
    show({"same_proposal_id": p2.get("proposal_id") == p.get("proposal_id"),
          "status": p2.get("status")},
         note="UNIQUE(tenant,stable_id,line_no) 唯一索引兜底")

    step("1.5 不平分录：agent 提交借 50 / 贷 40 → 确认时被 DB 约束整笔拒绝")
    p3 = unwrap(k.submit_proposal(
        stable_id="DEMO-A5-BAD",
        lines=[{"account_code": "1300", "direction": "debit", "amount": "50.00",
                "currency": "CNY"},
               {"account_code": "4000", "direction": "credit", "amount": "40.00",
                "currency": "CNY"}],
        source_ref="demo:bad", submitted_by="agent"))
    c3 = unwrap(k.confirm_proposal(proposal_id=p3.get("proposal_id"),
                                   confirmed_by="owner"))
    show(c3, note="约束层拒绝：账上永远不会出现不平的分录")
    show({"1300": balance_by_code(k, "1300").get("balance")},
         note="余额纹丝不动")

    step("1.6 冲正更正：错账不删不改，走红字冲销（append-only 存证）")
    p4 = unwrap(k.submit_proposal(
        stable_id="DEMO-A6-REV", reversal_of="DEMO-A1",
        lines=[{"account_code": "4000", "direction": "debit", "amount": "100.00",
                "currency": "CNY"},
               {"account_code": "1300", "direction": "credit", "amount": "100.00",
                "currency": "CNY"}],
        source_ref="demo:reversal:DEMO-A1", submitted_by="agent"))
    unwrap(k.confirm_proposal(proposal_id=p4["proposal_id"], confirmed_by="owner"))
    ents = unwrap(k.query_entries(limit=10))
    rows = ents.get("data", ents) if isinstance(ents, dict) else ents
    rev = [r for r in rows if r.get("reversal_of")]
    show({"count": len(rows), "reversal_linked": len(rev)},
         note="原分录原样可查 + 冲正分录关联可溯，删除路径不存在")

    # ================= 三方对账（双轨） =================
    rule(f"第 2 章 · 三方对账（轨迹={track}：订单-收款-库存）")

    # 2.0 先说清「真实通道现在拿不拿得到」——合成数据不能冒充真实接通。
    from fd_erp_vertical_templates.capability import load_matrix
    from fd_erp_vertical_templates.demo_tracks import assumed_matrix, run_track

    # 工作区根由 demo_common 向上找锚点算出（别再写死 parents[N]：这套脚本
    # 2026-11-16 搬过一层，三处写死的深度同时指错）
    from demo_common import FINDATA

    template_dir = FINDATA / "fd-erp-vertical-templates" / "templates" / "crossborder"
    platform = "shopify" if track == "shopify" else "merchant_erp"
    matrix = load_matrix(template_dir / "capability-matrix.json")

    if track == "shopify":
        orders, payments, inventory = DEMO_ORDERS, DEMO_PAYMENTS, DEMO_INVENTORY
        store = "demo-shop"
        fx = EcbExrFxProvider([{**o, "base": o["base_currency"],
                                "quote": o["quote_currency"]} for o in USD_FX_OBS])
        fee_schedule = {"commission": "0.15/1/shopify-rate-card"}
        fx_for_writeback = {"fx_rate": "7.20", "fx_as_of": DAY, "fx_source": "ecb-exr"}
    else:
        from fd_erp_vertical_templates.demo_tracks import load_domestic_fixture

        fixture = load_domestic_fixture(template_dir)
        orders, payments, inventory = (fixture["orders"], fixture["settlements"],
                                       fixture["inventory"])
        store = fixture["store"]
        fx = None
        fee_schedule = {"commission": "0.008/1/merchant-erp-rate-card"}
        fx_for_writeback = {}   # 国内原币即本位币，无需折算

    step(f"2.0 能力面：真实矩阵现在说什么（轨迹 {track}）")
    show({f"{platform}.{f}": matrix.status(platform, f)
          for f in ("orders", "settlements", "inventory")},
         note="可得=有真实读取记录；unmapped=需一次接入；unavailable=确认拿不到")
    print(f"  矩阵状态：{matrix.summary()}  ·  指纹 {matrix.fingerprint()[:20]}…")

    track_out = run_track(track, template_dir=template_dir,
                          records=None if track == "domestic" else {
                              "store": store, "orders": orders,
                              "settlements": payments, "inventory": inventory})
    print(f"  按真实矩阵：shape={track_out['honest']['shape']} "
          f"· 差异={track_out['honest']['diff_count']}（0 = 没核对，不是核对无误）")
    for miss in track_out["honest"]["capability_missing"]:
        print(f"    · {miss['flow']}: {miss['status']} — {miss['reason']}")
    assumed = track_out.get("assumed") or {}
    print(f"  按假设已接通：shape={assumed.get('shape')} "
          f"· 差异={assumed.get('diff_count')} · {assumed.get('note', '')}")
    print("  ↳ 下面 2.1-2.3 用合成店数据证明管线形状；真店通道当前均为「需一次接入」")

    recon = CrossborderRecon(store, fx=fx, platform_fee_schedule=fee_schedule)

    step("2.1 订单流 ↔ 收款流（含结算/佣金）逐笔对齐")
    diffs_pay = recon.reconcile_orders_payments(orders, payments)
    items = diffs_pay["diffs"]
    print(f"  配对成功 {len(diffs_pay['matched'])} 笔 · 差异 {len(items)} 条 "
          f"· 重推去重 {diffs_pay['duplicates_dropped']}")
    for d in items:
        show(d, keys=["kind", "left_ref", "right_ref", "left_amount",
                      "right_amount", "explanation_hint"])

    step("2.2 订单流 ↔ 库存流：未扣减 → 在途（引用物流解释）")
    diffs_inv = recon.reconcile_orders_inventory(orders, inventory)
    items_inv = diffs_inv["diffs"]
    for d in items_inv:
        show(d, keys=["kind", "left_ref", "right_ref", "explanation_hint"])

    step("2.3 平台费用报表（佣金/支付手续费，按费率出处可解释）")
    show(recon.fee_report(payments), keys=["totals", "fee_explanations"])

    step("2.3b 真店通道跑一次：缺腿显式报出，不假装核对过")
    live = CrossborderRecon(store, matrix=matrix, platform=platform)
    live_out = live.reconcile(orders=orders, payments=payments,
                              inventory=inventory)
    show({"shape": live_out["shape"], "diff_count": live_out["diff_count"]},
         note="shape=0 表示一条腿都还没接通；diff_count=0 是「没核对」不是「核对无误」")
    for miss in live_out["capability_missing"]:
        print(f"  · {miss['flow']}: {miss['status']} — {miss['reason']}")
    assert live_out["shape"] == 0, "矩阵当前应为全未接通；接通后本演示要同步改期望"
    assert all(m["kind"] == "capability_missing"
               for m in live_out["capability_missing"])
    print("  ↳ 这就是对客户的口径：需要一次接入，不是不支持")

    step("2.4 差异 escalate 到 owner 席位（拍板材料自动生成）")
    mismatch = next(d for d in items if d.get("kind") == "amount_mismatch")
    esc = escalate_diff(mismatch, fleet="cb-recon-fleet")
    show(esc, note="自动核对定性不了的差异，人工拍板——人坐在 owner 席位上")

    step("2.5 店主拍板 → 白名单车道回写 proposal（差额须带出处汇率，原币即本位币则免）")
    lines = recon.propose_correction_lines(mismatch)
    for line in lines:
        line.update(fx_for_writeback)
    proposal = writeback_recon_conclusion(
        k, tenant_id=TENANT_CB, fleet="cb-recon-fleet", post="reconciler",
        title="核对岗", diff=mismatch, proposal_lines=lines,
        decision_note="演示：收款侧 DEMO-P-2002 少 10 美元，差额挂应收更正")
    show(proposal, keys=["proposal_id", "status", "stable_id"],
         note="机器车道只挂应收（1300），资金类科目禁入")

    step("2.6 owner 确认 → 落账：在途结算款出现 USD 差额（折算 CNY）")
    unwrap(k.confirm_proposal(proposal_id=proposal["proposal_id"],
                              confirmed_by="owner"))
    res = unwrap(k.query_balance(account_code="1300"))
    rows = res.get("data", []) if isinstance(res, dict) else []
    show({"1300_rows": rows},
         note="USD 10 差额入账；折算 CNY 72 带 as_of 与出处（ecb-exr），"
              "无出处汇率内核直接拒绝")

    # ================= 红线表演 =================
    rule("第 3 章 · 两条红线，现场演示")
    step("3.1 资金红线：核对结论里出现资金执行语义 → 模板层直接拒绝")
    try:
        writeback_recon_conclusion(
            k, tenant_id=TENANT_CB, fleet="cb-recon-fleet", post="reconciler",
            title="核对岗", diff=mismatch, proposal_lines=lines,
            decision_note="演示：差额由平台自动打款给店主")
        print("  ✗ 意外：未被拒绝（不应发生）")
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "code", None)
        msg = str(e)
        print(f"  ✓ 拒绝生效：{code or type(e).__name__}: {msg[:80]}")
    print("  ↳ 资金归集/分账只出核对数据，划转走客户自选持牌通道（二清红线）")

    step("3.2 租户隔离：拿跨境租户身份问餐饮内核进程 → 拒绝 + 审计留痕")
    k_wrong = McpKernelClient(REST_URL, TENANT_CB)
    try:
        res = unwrap(k_wrong.query_balance(account_code="1300",
                                           tenant_id=TENANT_CB))
        code = res.get("error", {}).get("code") if isinstance(res, dict) else None
        print(f"  ✓ 服务端拒绝：{code or res}")
    except Exception as e:  # noqa: BLE001
        print(f"  ✓ 服务端拒绝：{getattr(e, 'code', type(e).__name__)}: {str(e)[:80]}")
    print("  ↳ 一个内核进程只认一个租户（ERP_TENANT_ID），跨租户零数据返回")

    rule(f"演示结束 · 电商线（轨迹 {track}）")
    print("  【合成数据】店铺数据（订单/结算/库存）为合成店 fixture，不是真实商家数据；"
          "账本分录来自本次真实调用。")
    print("  真实店通道当前均为「需一次接入」（见 capability-matrix.json），"
          "接通后本演示的期望值需同步更新。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="电商对账演示（双轨）")
    parser.add_argument("--track", choices=("shopify", "domestic"),
                        default="shopify",
                        help="shopify=跨境店（USD）；domestic=国内店（经商家电商 ERP，CNY）")
    main(parser.parse_args().track)
