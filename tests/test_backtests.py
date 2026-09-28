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
        market.mark_verified("600000", adjustment, days[0].date(), days[-1].date(), "synthetic")
    market._write_bars(market.bar_path("sh000300", "index", index=True), bars)
    market.mark_verified("sh000300", "index", days[0].date(), days[-1].date(), "synthetic")
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


def test_split_does_not_create_false_equity_crash(tmp_path, monkeypatch):
    bars = setup_bars(tmp_path, monkeypatch)
    raw = bars.copy()
    adjusted = bars.copy()
    for column in ("open", "high", "low", "close"):
        raw.loc[40:, column] *= .5
        adjusted.loc[:39, column] *= .5
    market._write_bars(market.bar_path("600000", "raw"), raw)
    market._write_bars(market.bar_path("600000", "qfq"), adjusted)
    report = backtests.run_backtest("600000", "buy_hold")
    assert report["metrics"]["total_return_pct"] > -10
    assert "前复权成交代理" in report["adjustment"]


def test_missing_interior_session_blocks_backtest(tmp_path, monkeypatch):
    bars = setup_bars(tmp_path, monkeypatch)
    missing = bars.loc[20, "date"]
    incomplete = bars[bars["date"] != missing]
    for adjustment in ("raw", "qfq"):
        market._write_bars(market.bar_path("600000", adjustment), incomplete)
        db.execute("DELETE FROM coverage WHERE code=? AND adjustment=?", ("600000", adjustment))
        market.mark_verified("600000", adjustment, date.fromisoformat(bars.loc[0, "date"]),
                             date.fromisoformat(bars.loc[19, "date"]), "synthetic")
        market.mark_verified("600000", adjustment, date.fromisoformat(bars.loc[21, "date"]),
                             date.fromisoformat(bars.iloc[-1]["date"]), "synthetic")
    with pytest.raises(ValueError, match="未验证日期"):
        backtests.run_backtest("600000", "buy_hold")


def test_benchmark_aligns_to_first_stock_session_and_requires_full_tail(tmp_path, monkeypatch):
    bars = setup_bars(tmp_path, monkeypatch)
    first_stock_day = bars.loc[5, "date"]
    stock = bars[bars["date"] >= first_stock_day]
    for adjustment in ("raw", "qfq"):
        market._write_bars(market.bar_path("600000", adjustment), stock)
    report = backtests.run_backtest("600000", "buy_hold", start=bars.loc[0, "date"])
    assert report["benchmark_equity"][0]["date"] == first_stock_day
    assert report["benchmark_equity"][0]["value"] == 100_000
    stale_index = bars.iloc[:-1]
    market._write_bars(market.bar_path("sh000300", "index", index=True), stale_index)
    with pytest.raises(ValueError, match="基准缺少"):
        backtests.run_backtest("600000", "buy_hold", start=bars.loc[0, "date"])
