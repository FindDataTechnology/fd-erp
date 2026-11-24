"""开店脚本测试（change establish-ai-native-ecommerce-stack，C6 判据）。

判据：
1. 清单缺项 / 非法租户 id / 非法结算方式 → 逐条点名并拒绝，**不产生任何副作用**；
2. `--dry-run` 不建 schema、不建目录；
3. 合法清单给出部署三件套（环境变量、快照命令、四步验收）；
4. 无 DSN 时如实报「schema 未建」，不假装成功（退出码 2）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import open_shop as os_  # type: ignore  # noqa: E402

GOOD = {
    "tenant_id": "shop_new",
    "shop_title": "新店",
    "retail_channel": "retail-online",
    "settlement": "offline_transfer",
    "payee": "商家自有银行账户",
    "fulfillment": "own_warehouse",
}


def _write(tmp_path, body) -> Path:
    p = tmp_path / "shop.json"
    p.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return p


def test_missing_fields_are_all_reported_at_once(tmp_path):
    body = {"tenant_id": "shop_new"}
    problems = os_.validate(body)
    # 五个必填项一次报全，不是改一条跑一次
    assert len([p for p in problems if p.startswith("缺必填项")]) == 5
    assert os_.main([str(_write(tmp_path, body)), "--dry-run"]) == 1


def test_invalid_tenant_ids_rejected():
    for bad in ("Shop-New", "shop new", "", "a" * 33, "shop.new"):
        m = {**GOOD, "tenant_id": bad}
        assert any("tenant_id 非法" in p or "缺必填项 tenant_id" in p
                   for p in os_.validate(m)), bad


def test_default_tenant_rejected():
    """default 是租户 0（生产库本体 public schema），不能被当成一家店。"""
    problems = os_.validate({**GOOD, "tenant_id": "default"})
    assert any("不得为 default" in p for p in problems)


def test_invalid_settlement_rejected():
    problems = os_.validate({**GOOD, "settlement": "credit_card"})
    assert any("settlement" in p for p in problems)


def test_dry_run_creates_nothing(tmp_path, capsys):
    data_dir = tmp_path / "data"
    body = {**GOOD, "data_dir": str(data_dir)}
    assert os_.main([str(_write(tmp_path, body)), "--dry-run"]) == 0
    assert not data_dir.exists(), "--dry-run 不得建目录"
    out = capsys.readouterr().out
    assert "ERP_TENANT_ID=shop_new" in out
    assert "ERP_RETAIL_CHANNEL=retail-online" in out
    assert f"/shop/shop_new/products" in out


def test_rejected_manifest_creates_nothing(tmp_path):
    data_dir = tmp_path / "data"
    body = {"tenant_id": "shop_new", "data_dir": str(data_dir)}   # 缺多项
    assert os_.main([str(_write(tmp_path, body))]) == 1
    assert not data_dir.exists()


def test_provision_data_root_uses_tenant_scoped_files(tmp_path):
    root = os_.provision_data_root("shop_new", tmp_path / "d")
    assert Path(root["dir"]).is_dir()
    # 文件按租户命名：两家店同一目录下也不串
    for name in root["files"]:
        assert name.endswith("-shop_new.jsonl")


def test_schema_provision_reports_unconfigured_dsn():
    r = os_.provision_schema("shop_new", None)
    assert r["ok"] is False
    assert "未配置" in r["reason"]


def test_full_run_without_dsn_exits_two_and_says_so(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("ERP_LEDGER_DATABASE_URL", raising=False)
    body = {**GOOD, "data_dir": str(tmp_path / "d")}
    code = os_.main([str(_write(tmp_path, body)), "--dsn-env", "ERP_LEDGER_DATABASE_URL"])
    assert code == 2, "无 DSN 是「判不出/未完成」，不是「通过」"
    assert "内核 schema 未建" in capsys.readouterr().out


def test_bad_json_manifest_exits_cleanly(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit):
        os_.main([str(p), "--dry-run"])
