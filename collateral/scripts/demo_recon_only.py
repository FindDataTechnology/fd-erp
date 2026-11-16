#!/usr/bin/env python3
"""无内核版对账演示（spec `ecommerce-merchant-channel-wiring`，任务 6.3；原 change `wire-ecommerce-merchant-channels` 已于 2026-11-10 归档）。

主演示 `demo_crossborder.py` 需要 demo_env.sh 拉起两个内核才跑得起来；这个入口
只跑**对账章节**，不需要内核，因此可以在 CI、评审、以及内核不在线的机器上验证
「双轨都能跑 + 缺腿显式标注」。

它不替代主演示：拍板、白名单回写、租户隔离那几段必须在内核上真跑，这里不演示。

用法：
  python3 fd-erp/collateral/scripts/demo_recon_only.py --track shopify
  python3 fd-erp/collateral/scripts/demo_recon_only.py --track domestic
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

sys.path.insert(0, str(HERE))

from demo_common import FINDATA, rule, show, step  # noqa: E402

TEMPLATES = FINDATA / "fd-erp-vertical-templates" / "templates" / "crossborder"


def _records(track: str) -> dict | None:
    if track != "shopify":
        return None
    sys.path.insert(0, str(HERE))
    from demo_adapters import DEMO_INVENTORY, DEMO_ORDERS, DEMO_PAYMENTS
    return {"store": "demo-shop", "orders": DEMO_ORDERS,
            "settlements": DEMO_PAYMENTS, "inventory": DEMO_INVENTORY}


def main(track: str = "shopify") -> int:
    from fd_erp_vertical_templates.capability import load_matrix
    from fd_erp_vertical_templates.demo_tracks import TRACK_PLATFORM, run_track

    rule(f"对账演示（无内核版）· 轨迹 {track}")
    matrix = load_matrix(TEMPLATES / "capability-matrix.json")
    platform = TRACK_PLATFORM[track]

    step("1. 真实能力矩阵：现在拿不拿得到")
    show({f"{platform}.{f}": matrix.status(platform, f)
          for f in ("orders", "settlements", "inventory")},
         note="可得=有真实读取记录；unmapped=需一次接入；unavailable=确认拿不到")
    print(f"  矩阵状态：{matrix.summary()} · 指纹 {matrix.fingerprint()[:20]}…")

    step("2. 按真实矩阵对账：缺腿逐条列出，不出零差异")
    out = run_track(track, template_dir=TEMPLATES, records=_records(track))
    honest = out["honest"]
    print(f"  可对齐腿数 shape={honest['shape']} · 差异条数={honest['diff_count']}"
          "（0 = 没核对，不是核对无误）")
    for miss in honest["capability_missing"]:
        print(f"    · {miss['flow']}: {miss['status']} — {miss['reason']}")
    if not honest["capability_missing"]:
        print("    （无缺腿：该平台三腿均已接通）")

    step("3. 假设已接通：只展示形状，不是矩阵事实")
    assumed = out.get("assumed") or {}
    print(f"  shape={assumed.get('shape')} · 差异={assumed.get('diff_count')} "
          f"· 差异类型={assumed.get('diff_kinds')}")
    print(f"  {assumed.get('note', '')}")
    if assumed.get("skipped_legs"):
        print(f"  跳过的腿（变体声明不可得）：{assumed['skipped_legs']}")

    rule("结束 · 以上第 3 段为演示假设；第 1/2 段才是当前可对外承诺的口径")
    print("  【合成数据】本演示的订单/结算/库存均为合成店数据，不是真实商家数据；"
          "真实通道当前均为「需一次接入」。")
    # 退出码：真实矩阵下有缺腿属预期；只要「假设」段形状与缺腿自洽就算通过。
    ok = assumed.get("shape") is not None and honest["shape"] <= assumed["shape"]
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="电商对账演示（无内核版，双轨）")
    parser.add_argument("--track", choices=("shopify", "domestic"), default="shopify")
    raise SystemExit(main(parser.parse_args().track))
