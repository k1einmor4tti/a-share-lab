from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from app import catalog, db, jobs, market, server


def test_dashboard_routes_and_input_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "market.sqlite3")
    monkeypatch.setattr(market, "BARS_DIR", tmp_path / "bars")
    monkeypatch.setattr(jobs.manager, "bootstrap", lambda: None)
    with TestClient(server.app) as client:
        catalog.upsert_symbols([("600000", "浦发银行", "1999-11-10", None)], "listed", "test")
        frame = pd.DataFrame([{"date": "2025-01-02", "open": 10.0, "high": 11.0, "low": 9.0,
                               "close": 10.5, "volume": 1000.0, "amount": 10500.0,
                               "turnover": 1.0, "source": "test"}])[market.BAR_COLUMNS]
        market._write_bars(market.bar_path("600000", "qfq"), frame)
        market.mark_verified("600000", "qfq", pd.Timestamp("2025-01-02").date(),
                             pd.Timestamp("2025-01-02").date(), "test")
        assert client.get("/").status_code == 200
        assert client.get("/assets/app.js").status_code == 200
        response = client.get("/api/market")
        assert response.status_code == 200
        assert len(response.json()["indexes"]) == 5
        assert client.get("/api/stocks", params={"q": "浦发"}).json()["items"][0]["code"] == "600000"
        bars = client.get("/api/stocks/600000/bars").json()
        assert bars["bars"][0]["source"] == "test"
        assert bars["coverage"][0]["start"] == "2025-01-02"
        assert bars["unverified_ranges"]
        assert bars["target_range"]["start"] >= "2000-01-01"
        assert client.get("/api/stocks/600000/bars", params={"adjustment": "../../bad"}).status_code == 422
        assert client.get("/api/stocks/400001/bars").status_code == 422
        assert client.get("/api/indexes/sh000001/bars").status_code == 200
        assert client.get("/api/indexes/unknown/bars").status_code == 404
        assert {item["key"] for item in client.get("/api/strategies").json()["modules"]} == {
            "buy_hold", "ma_cross", "turtle", "rsi", "bollinger"}
        assert client.post("/api/backtests", json={"code": "600000", "strategy": "buy_hold"}).status_code == 422


def test_backtest_result_and_download_routes(tmp_path, monkeypatch):
    from app import backtests

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "market.sqlite3")
    monkeypatch.setattr(market, "BARS_DIR", tmp_path / "bars")
    monkeypatch.setattr(backtests, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(jobs.manager, "bootstrap", lambda: None)
    with TestClient(server.app) as client:
        catalog.upsert_symbols([("600000", "测试股票", None, None)], "listed", "test")
        days = pd.date_range("2025-01-01", periods=5, freq="B")
        frame = pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "open": [10, 11, 12, 13, 14],
                              "high": [11, 12, 13, 14, 15], "low": [9, 10, 11, 12, 13],
                              "close": [10, 11, 12, 13, 14], "volume": 100_000.0,
                              "amount": 1_000_000.0, "turnover": 1.0, "source": "test"})[market.BAR_COLUMNS]
        for adjustment in ("raw", "qfq"):
            market._write_bars(market.bar_path("600000", adjustment), frame)
            market.mark_verified("600000", adjustment, days[0].date(), days[-1].date(), "test")
        market._write_bars(market.bar_path("sh000300", "index", index=True), frame)
        market.mark_verified("sh000300", "index", days[0].date(), days[-1].date(), "test")
        created = client.post("/api/backtests", json={"code": "600000", "strategy": "buy_hold"})
        assert created.status_code == 200, created.text
        run_id = created.json()["id"]
        assert client.get(f"/api/backtests/{run_id}").json()["id"] == run_id
        assert client.get("/api/backtests").json()["items"][0]["id"] == run_id
        exported = client.get(f"/api/backtests/{run_id}/export")
        assert exported.status_code == 200
        assert exported.content[:2] == b"PK"
