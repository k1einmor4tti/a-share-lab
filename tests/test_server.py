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
        assert client.get("/api/stocks/600000/bars", params={"adjustment": "../../bad"}).status_code == 422
        assert client.get("/api/stocks/400001/bars").status_code == 422
        assert client.get("/api/indexes/sh000001/bars").status_code == 200
        assert client.get("/api/indexes/unknown/bars").status_code == 404
