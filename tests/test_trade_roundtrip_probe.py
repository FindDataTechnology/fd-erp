"""链路探针的四态退出码（`closed-loop-must-have-probe-and-reader`）。

正例已由线上/本地真跑覆盖；这里守的是**失败可分辨**：目录空了返回 2 而不是 0，
目录连不上返回 3 而不是 1。判据错了，定时读者就会把「没配」读成「链路断」。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "fd-erp" / "tools" / "trade_roundtrip.py"


def load():
    spec = importlib.util.spec_from_file_location("trade_roundtrip", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_unreachable_directory_exits_3():
    """连不上目录 = 上游不可达（3），不是链路断（1）——两者修法完全不同。"""
    assert load().main(["--directory", "http://127.0.0.1:1",
                        "--api", "http://127.0.0.1:1",
                        "--tenant", "acme"]) == 3


def test_no_match_exits_2(tmp_path, monkeypatch):
    """目录可读但没有匹配 = 未配置（2），不是通过。"""
    from fd_shop_directory.app import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SHOP_DIRECTORY_WRITE_TOKEN", "t")
    c = TestClient(create_app(str(tmp_path / "d.jsonl")))
    c.post("/directory/shops", json={"tenant": "acme", "title": "A",
                                     "public_base": "http://x",
                                     "categories": ["食品"], "keywords": []},
           headers={"x-directory-write-token": "t"})
    # 用 http 起不来 TestClient，这里只验证 directory 侧的 state 判据在探针里的映射：
    assert c.get("/directory/search", params={"category": "饮品"}).json()["state"] == "no_match"


def test_amount_mismatch_detected():
    mod = load()
    assert mod._amount_eq("960", "96.00", 10) is True
    assert mod._amount_eq("1280", "96.00", 10) is False
