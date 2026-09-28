from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from .config import DB_PATH


def utc_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=30000")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def init_db() -> None:
    with connection() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS symbols (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                exchange TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'listed',
                listing_date TEXT,
                delisting_date TEXT,
                catalog_source TEXT NOT NULL,
                raw_first TEXT,
                raw_last TEXT,
                adjusted_first TEXT,
                adjusted_last TEXT,
                bar_count INTEGER NOT NULL DEFAULT 0,
                data_source TEXT,
                sync_error TEXT,
                updated_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
            CREATE INDEX IF NOT EXISTS idx_symbols_status ON symbols(status);
            CREATE TABLE IF NOT EXISTS coverage (
                code TEXT NOT NULL,
                adjustment TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                source TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                PRIMARY KEY(code,adjustment,start_date,end_date)
            );
            CREATE INDEX IF NOT EXISTS idx_coverage_code ON coverage(code,adjustment);
            CREATE TABLE IF NOT EXISTS indexes (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                first_date TEXT,
                last_date TEXT,
                bar_count INTEGER NOT NULL DEFAULT 0,
                sync_error TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                total INTEGER NOT NULL DEFAULT 0,
                done INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0,
                skipped INTEGER NOT NULL DEFAULT 0,
                current_code TEXT,
                message TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS job_failures (
                job_id TEXT NOT NULL,
                code TEXT NOT NULL,
                error TEXT NOT NULL,
                PRIMARY KEY(job_id,code),
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            );
            CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                source TEXT NOT NULL,
                path TEXT NOT NULL,
                imported_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS backtests (
                id TEXT PRIMARY KEY,
                code TEXT NOT NULL,
                strategy TEXT NOT NULL,
                created_at TEXT NOT NULL,
                params_json TEXT NOT NULL,
                result_path TEXT NOT NULL
            );
            """
        )
        db.execute("UPDATE jobs SET status='interrupted', finished_at=? WHERE status='running'", (utc_now(),))
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_running ON jobs(status) WHERE status='running'")


def rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connection() as db:
        return [dict(row) for row in db.execute(sql, params).fetchall()]


def row(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    result = rows(sql, params)
    return result[0] if result else None


def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
    with connection() as db:
        db.execute(sql, params)
