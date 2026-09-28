"""Resumable full-market daily-bar downloads.

The persisted coverage intervals, rather than a job cursor, decide what to fetch.
Restarting an interrupted job therefore retries failed ranges without duplicating
the dates which were already verified.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from collections import deque
from datetime import date
from typing import Any

from . import catalog, db, market

LOG = logging.getLogger(__name__)


def job_details(job_id: str, failure_limit: int = 100) -> dict[str, Any] | None:
    job = db.row("SELECT * FROM jobs WHERE id=?", (job_id,))
    if job is None:
        return None
    job["failures"] = db.rows(
        "SELECT code,error FROM job_failures WHERE job_id=? ORDER BY code LIMIT ?", (job_id, failure_limit))
    job["failure_count"] = db.row(
        "SELECT COUNT(*) AS count FROM job_failures WHERE job_id=?", (job_id,))["count"]
    return job


def latest_job() -> dict[str, Any] | None:
    row = db.row("SELECT id FROM jobs ORDER BY started_at DESC, rowid DESC LIMIT 1")
    return job_details(row["id"]) if row else None


class MarketJobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._priority: deque[str] = deque()

    def start(self, kind: str = "update") -> dict[str, Any]:
        if kind not in {"initial", "update", "retry"}:
            raise ValueError(f"Invalid market job kind: {kind}")
        with self._lock:
            active = db.row("SELECT id FROM jobs WHERE status='running' LIMIT 1")
            if active:
                result = job_details(active["id"])
                assert result is not None
                result["already_running"] = True
                return result
            job_id = uuid.uuid4().hex
            try:
                db.execute(
                    "INSERT INTO jobs(id,kind,status,started_at,message) VALUES(?,?,'running',?,?)",
                    (job_id, kind, db.utc_now(), "等待后台任务开始"),
                )
            except sqlite3.IntegrityError:
                active = db.row("SELECT id FROM jobs WHERE status='running' LIMIT 1")
                if active is None:
                    raise
                result = job_details(active["id"])
                assert result is not None
                result["already_running"] = True
                return result
            self._thread = threading.Thread(target=self._run, args=(job_id,),
                                            name=f"market-update-{job_id[:8]}", daemon=True)
            self._thread.start()
            result = job_details(job_id)
            assert result is not None
            result["already_running"] = False
            return result

    def bootstrap(self) -> dict[str, Any] | None:
        """Call once during web startup, after SQLite has been initialized."""
        catalog.seed_catalog()
        latest = latest_job()
        if latest is None or latest["status"] in {"interrupted", "partial"}:
            return self.start("initial" if latest is None else "retry")
        return latest

    def prioritize(self, code: str) -> dict[str, Any]:
        if db.row("SELECT code FROM symbols WHERE code=?", (code,)) is None:
            raise ValueError(f"未知股票代码: {code}")
        job = self.start("update")
        with self._lock:
            if code not in self._priority:
                self._priority.append(code)
        job["queued_code"] = code
        return job

    def _failure(self, job_id: str, code: str, error: Exception | str, *, index: bool = False) -> None:
        message = str(error)[:1000]
        LOG.warning("Market sync failed for %s: %s", code, message)
        with db.connection() as connection:
            connection.execute(
                "INSERT INTO job_failures(job_id,code,error) VALUES(?,?,?) "
                "ON CONFLICT(job_id,code) DO UPDATE SET error=excluded.error",
                (job_id, code, message),
            )
            table = "indexes" if index else "symbols"
            connection.execute(f"UPDATE {table} SET sync_error=? WHERE code=?", (message, code))

    def _progress(self, job_id: str, result: str, code: str) -> None:
        column = "skipped" if result == "skipped" else "done" if result == "updated" else "failed"
        db.execute(f"UPDATE jobs SET {column}={column}+1,current_code=?,message=? WHERE id=?",
                   (code, f"已处理 {code}", job_id))

    def _run(self, job_id: str) -> None:
        target = market.completed_bar_cutoff()
        try:
            self._execute(job_id, target)
        except Exception as exc:
            LOG.exception("Market job %s stopped unexpectedly", job_id)
            self._failure(job_id, "_job", exc)
        finally:
            with self._lock:
                self._priority.clear()
            counts = db.row("SELECT failed,total,done,skipped FROM jobs WHERE id=?", (job_id,))
            assert counts is not None
            source_errors = db.row("SELECT COUNT(*) AS count FROM job_failures WHERE job_id=? AND substr(code,1,1)='_'", (job_id,))
            has_errors = bool(counts["failed"] or (source_errors and source_errors["count"]))
            status = "partial" if has_errors else "completed"
            summary = (f"已更新 {counts['done']}，已跳过 {counts['skipped']}，"
                       f"失败 {counts['failed']}；目标收盘日 {target.isoformat()}")
            db.execute("UPDATE jobs SET status=?,current_code=NULL,message=?,finished_at=? WHERE id=?",
                       (status, summary, db.utc_now(), job_id))

    def _execute(self, job_id: str, target: date) -> None:
        # Indexes are useful immediately, before a multi-hour stock download.
        db.execute("UPDATE jobs SET message=?,total=? WHERE id=?",
                   ("正在更新大盘指数", len(market.INDEXES), job_id))
        for code, name in market.INDEXES.items():
            try:
                result = market.sync_index(code, target=target)
                outcome = str(result["status"])
            except Exception as exc:
                self._failure(job_id, code, exc, index=True)
                outcome = "failed"
            self._progress(job_id, outcome, f"{name} ({code})")

        db.execute("UPDATE jobs SET message=? WHERE id=?", ("正在刷新股票及退市清单", job_id))
        report = catalog.refresh_catalog()
        for number, error in enumerate(report["errors"], 1):
            self._failure(job_id, f"_catalog_{number}", error)
        symbols = db.rows("SELECT code FROM symbols ORDER BY code")
        db.execute("UPDATE jobs SET total=?,message=? WHERE id=?",
                   (len(market.INDEXES) + len(symbols), f"准备更新 {len(symbols)} 只股票", job_id))
        pending = {symbol["code"] for symbol in symbols}
        order = iter(symbol["code"] for symbol in symbols)
        while pending:
            code = None
            with self._lock:
                while self._priority and code is None:
                    candidate = self._priority.popleft()
                    if candidate in pending:
                        code = candidate
            if code is None:
                code = next(candidate for candidate in order if candidate in pending)
            pending.remove(code)
            db.execute("UPDATE jobs SET current_code=? WHERE id=?", (code, job_id))
            try:
                result = market.sync_stock(code, target=target)
                outcome = str(result["status"])
                if outcome in {"updated", "skipped"}:
                    db.execute("UPDATE symbols SET sync_error=NULL WHERE code=?", (code,))
            except Exception as exc:
                self._failure(job_id, code, exc)
                outcome = "failed"
            self._progress(job_id, outcome, code)


manager = MarketJobManager()
