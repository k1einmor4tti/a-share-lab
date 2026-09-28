from __future__ import annotations

from datetime import date

import pandas as pd

from app import catalog, db, market


def sample_bars(start: date, end: date, source: str = "东方财富", close: float = 10.0) -> pd.DataFrame:
    dates = pd.date_range(start, end, freq="D")
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": close, "high": close + 1, "low": close - 1, "close": close,
        "volume": 1000.0, "amount": close * 1000, "turnover": 1.0, "source": source,
    })[market.BAR_COLUMNS]


def setup_market(tmp_path, monkeypatch, cutoff: date):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "market.sqlite3")
    monkeypatch.setattr(market, "BARS_DIR", tmp_path / "bars")
    monkeypatch.setattr(market, "history_start", lambda: date(2026, 9, 16))
    monkeypatch.setattr(market, "completed_bar_cutoff", lambda: cutoff)
    db.init_db()
    catalog.upsert_symbols([("600000", "浦发银行", None, None)], "listed", "test")


def test_incremental_update_only_checks_new_range(tmp_path, monkeypatch):
    setup_market(tmp_path, monkeypatch, date(2026, 9, 20))
    calls = []

    def fetch(_code, first, last, adjustment):
        calls.append((first, last, adjustment))
        return sample_bars(first, last), "东方财富"

    monkeypatch.setattr(market, "fetch_stock", fetch)
    first = market.sync_stock("600000")
    assert first["bars"] == 5
    calls.clear()
    monkeypatch.setattr(market, "completed_bar_cutoff", lambda: date(2026, 9, 24))
    second = market.sync_stock("600000")
    assert second["new_bars"] == 4
    assert (date(2026, 9, 21), date(2026, 9, 24), "raw") in calls
    assert (date(2026, 9, 21), date(2026, 9, 24), "qfq") in calls
    assert len(market.read_bars("600000", "raw")) == 9
    assert market.sync_stock("600000")["status"] == "skipped"


def test_failed_interior_range_is_retried(tmp_path, monkeypatch):
    setup_market(tmp_path, monkeypatch, date(2026, 9, 21))
    for adjustment in ("raw", "qfq"):
        market.mark_verified("600000", adjustment, date(2026, 9, 16), date(2026, 9, 17), "东方财富")
        market.mark_verified("600000", adjustment, date(2026, 9, 19), date(2026, 9, 20), "东方财富")
        market._write_bars(market.bar_path("600000", adjustment), sample_bars(date(2026, 9, 16), date(2026, 9, 17)))
    calls = []

    def fetch(_code, first, last, adjustment):
        calls.append((first, last, adjustment))
        return sample_bars(first, last), "东方财富"

    monkeypatch.setattr(market, "fetch_stock", fetch)
    outcome = market.sync_stock("600000")
    assert outcome["status"] == "updated"
    assert (date(2026, 9, 18), date(2026, 9, 18), "raw") in calls
    assert (date(2026, 9, 21), date(2026, 9, 21), "raw") in calls
    assert market.unchecked_ranges("600000", "raw", date(2026, 9, 16), date(2026, 9, 21)) == []


def test_adjustment_rebase_replaces_old_prices(tmp_path, monkeypatch):
    setup_market(tmp_path, monkeypatch, date(2026, 9, 20))
    current_qfq = {"close": 10.0}

    def fetch(_code, first, last, adjustment):
        value = current_qfq["close"] if adjustment == "qfq" else 10.0
        return sample_bars(first, last, close=value), "东方财富"

    monkeypatch.setattr(market, "fetch_stock", fetch)
    market.sync_stock("600000")
    current_qfq["close"] = 9.0
    monkeypatch.setattr(market, "completed_bar_cutoff", lambda: date(2026, 9, 21))
    outcome = market.sync_stock("600000")
    assert outcome["rebased"] is True
    assert market.read_bars("600000", "qfq")["close"].iloc[0] == 9.0
    assert market.verified_intervals("600000", "qfq") == [(date(2026, 9, 16), date(2026, 9, 21))]
