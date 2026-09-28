from __future__ import annotations

import threading

from app import catalog, db, jobs, market


def test_job_progress_failure_and_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite3")
    db.init_db()
    catalog.upsert_symbols([
        ("600000", "浦发银行", "1999-11-10", None),
        ("000001", "平安银行", "1991-04-03", None),
    ], "listed", "test")
    monkeypatch.setattr(market, "INDEXES", {"sh000001": "上证指数"})
    monkeypatch.setattr(market, "sync_index", lambda code, target: {"status": "updated"})
    monkeypatch.setattr(catalog, "refresh_catalog", lambda: {"errors": []})
    calls = []

    def sync_stock(code, target):
        calls.append(code)
        if code == "600000" and calls.count(code) == 1:
            raise ConnectionError("source temporarily unavailable")
        return {"status": "skipped" if code == "000001" else "updated"}

    monkeypatch.setattr(market, "sync_stock", sync_stock)
    manager = jobs.MarketJobManager()
    first = manager.start("initial")
    assert first["already_running"] is False
    assert manager._thread is not None
    manager._thread.join(timeout=5)
    saved = jobs.job_details(first["id"])
    assert saved is not None
    assert (saved["total"], saved["done"], saved["skipped"], saved["failed"]) == (3, 1, 1, 1)
    assert saved["status"] == "partial"
    assert saved["failures"][0]["code"] == "600000"
    assert db.row("SELECT sync_error FROM symbols WHERE code='600000'")["sync_error"]

    second = manager.start("retry")
    assert manager._thread is not None
    manager._thread.join(timeout=5)
    retried = jobs.job_details(second["id"])
    assert retried is not None and retried["status"] == "completed"
    assert db.row("SELECT sync_error FROM symbols WHERE code='600000'")["sync_error"] is None
    assert calls.count("600000") == 2


def test_duplicate_click_returns_active_job(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite3")
    db.init_db()
    entered = threading.Event()
    release = threading.Event()
    manager = jobs.MarketJobManager()

    def hold(_job_id, _target):
        entered.set()
        assert release.wait(timeout=5)

    monkeypatch.setattr(manager, "_execute", hold)
    first = manager.start("update")
    assert entered.wait(timeout=5)
    duplicate = manager.start("update")
    assert duplicate["already_running"] is True
    assert duplicate["id"] == first["id"]
    assert db.row("SELECT COUNT(*) AS n FROM jobs")["n"] == 1
    release.set()
    assert manager._thread is not None
    manager._thread.join(timeout=5)
