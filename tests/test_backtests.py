from __future__ import annotations

import json
import io
import zipfile
from datetime import date

import pandas as pd
import pytest

from app import backtests, catalog, db, market


def setup_bars(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite3")
    monkeypatch.setattr(market, "BARS_DIR", tmp_path / "bars")
    monkeypatch.setattr(backtests, "RESULTS_DIR", tmp_path / "results")
    db.init_db()
    catalog.upsert_symbols([("600000", "测试股票", "2025-01-01", None)], "listed", "test")
    days = pd.date_range("2025-01-01", periods=85, freq="B")
    close = [10 + i * .04 + (i % 9 - 4) * .12 for i in range(len(days))]
    bars = pd.DataFrame({
        "date": days.strftime("%Y-%m-%d"),
        "open": close, "high": [x + .2 for x in close], "low": [x - .2 for x in close],
        "close": close, "volume": 100_000.0, "amount": 1_000_000.0,
        "turnover": 1.0, "source": "synthetic",
    })[market.BAR_COLUMNS]
    for adjustment in ("raw", "qfq"):
        market._write_bars(market.bar_path("600000", adjustment), bars)
    market._write_bars(market.bar_path("sh000300", "index", index=True), bars)
    return bars


@pytest.mark.parametrize("strategy,params", [
    ("buy_hold", {}), ("ma_cross", {"fast": 3, "slow": 9}),
    ("turtle", {"entry": 9, "exit": 4}),
    ("rsi", {"period": 4, "oversold": 35, "overbought": 65}),
    ("bollinger", {"window": 6, "width": 1.5}),
])
def test_registered_modules_run_through_akquant(tmp_path, monkeypatch, strategy, params):
    setup_bars(tmp_path, monkeypatch)
    report = backtests.run_backtest("600000", strategy, params)
    assert report["versions"]["akquant"]
    assert report["metrics"]["total_bars"] == 85
    assert len(report["equity"]) == 85
    assert report["benchmark_equity"]
    assert (tmp_path / "results" / report["id"] / "stock-input.parquet").exists()
    assert backtests.saved_backtest(report["id"])["metrics"] == report["metrics"]


def test_buy_hold_executes_next_day_in_lots_and_snapshot_survives_market_change(tmp_path, monkeypatch):
    bars = setup_bars(tmp_path, monkeypatch)
    report = backtests.run_backtest("600000", "buy_hold")
    buys = [order for order in report["orders"] if order.get("side") == "buy" and order.get("status") == "filled"]
    assert buys
    assert buys[0]["quantity"] % 100 == 0
    assert buys[0]["updated_at"][:10] == "2025-01-02"
    assert report["equity"][0]["value"] == 100_000
    path = tmp_path / "results" / report["id"] / "stock-input.parquet"
    before = path.read_bytes()
    bars["close"] = 1000
    market._write_bars(market.bar_path("600000", "raw"), bars)
    assert path.read_bytes() == before
    assert json.loads((path.parent / "result.json").read_text())["input_sha256"] == report["input_sha256"]
    with zipfile.ZipFile(io.BytesIO(backtests.export_backtest(report["id"]))) as archive:
        assert {"result.json", "stock-input.parquet", "benchmark-input.parquet", "equity.csv", "orders.csv"}.issubset(archive.namelist())


def test_backtest_explains_missing_local_data(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite3")
    monkeypatch.setattr(market, "BARS_DIR", tmp_path / "bars")
    db.init_db()
    catalog.upsert_symbols([("600000", "测试股票", None, None)], "listed", "test")
    with pytest.raises(ValueError, match="请先更新该股票"):
        backtests.run_backtest("600000", "buy_hold")
