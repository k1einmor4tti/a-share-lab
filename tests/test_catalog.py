from __future__ import annotations

import json

import pandas as pd

from app import catalog, db


def test_catalog_seed_refresh_and_delisted_search(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite3")
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([
        {"f12": "600000", "f14": "浦发银行", "f26": 19991110},
        {"f12": "200001", "f14": "B股", "f26": 19920101},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(catalog, "SEED_LIST", seed)
    db.init_db()
    assert catalog.seed_catalog() == 1
    assert db.row("SELECT listing_date FROM symbols WHERE code='600000'")["listing_date"] == "1999-11-10"

    monkeypatch.setattr(catalog, "_baostock_universe", lambda: (
        [("600000", "浦发银行", "1999-11-10", None)], []))
    monkeypatch.setattr(catalog, "_eastmoney_active", lambda: [
        ("600000", "浦发银行", "1999-11-10", None),
        ("301001", "测试科技", "2021-01-01", None),
    ])
    monkeypatch.setattr(catalog.ak, "stock_info_sh_delist", lambda **_: pd.DataFrame([
        {"公司代码": "600001", "公司简称": "已退市", "上市日期": "1998-01-22", "暂停上市日期": "2009-12-29"},
        {"公司代码": "600000", "公司简称": "旧名", "上市日期": "1998-01-22", "暂停上市日期": "2009-12-29"},
    ]))
    monkeypatch.setattr(catalog.ak, "stock_info_sz_delist", lambda **_: pd.DataFrame())
    monkeypatch.setattr(catalog.ak, "stock_zh_a_stop_em", lambda: pd.DataFrame())
    report = catalog.refresh_catalog()
    assert not report["errors"]
    assert report["total"] == 3
    assert db.row("SELECT status FROM symbols WHERE code='600000'")["status"] == "listed"
    assert db.row("SELECT status FROM symbols WHERE code='600001'")["status"] == "delisted"
    assert catalog.search_symbols("退市")[0]["code"] == "600001"
    assert catalog.search_symbols("301")[0]["code"] == "301001"


def test_catalog_keeps_seed_when_remote_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite3")
    db.init_db()
    catalog.upsert_symbols([("000001", "平安银行", "1991-04-03", None)], "listed", "local")

    def fail(*_args, **_kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr(catalog, "_baostock_universe", fail)
    monkeypatch.setattr(catalog, "_eastmoney_active", fail)
    monkeypatch.setattr(catalog.ak, "stock_info_sh_delist", fail)
    monkeypatch.setattr(catalog.ak, "stock_info_sz_delist", fail)
    monkeypatch.setattr(catalog.ak, "stock_zh_a_stop_em", fail)
    report = catalog.refresh_catalog()
    assert len(report["errors"]) == 5
    assert catalog.search_symbols("000001")[0]["name"] == "平安银行"
