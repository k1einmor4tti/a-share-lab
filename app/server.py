"""Local-only FastAPI application for A Share Lab."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import catalog, db, jobs, market

WEB_DIR = Path(__file__).resolve().parent / "web"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    jobs.manager.bootstrap()
    yield


app = FastAPI(title="A Share Lab", lifespan=lifespan, docs_url="/api/docs", redoc_url=None)
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


@app.get("/")
def home() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/market")
def market_overview() -> dict[str, Any]:
    counts = db.row(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN status='delisted' THEN 1 ELSE 0 END) AS delisted,
                  SUM(CASE WHEN bar_count>0 THEN 1 ELSE 0 END) AS with_bars,
                  SUM(CASE WHEN sync_error IS NOT NULL THEN 1 ELSE 0 END) AS failed
           FROM symbols"""
    ) or {"total": 0, "delisted": 0, "with_bars": 0, "failed": 0}
    return {"indexes": market.index_cards(), "catalog": {key: value or 0 for key, value in counts.items()},
            "job": jobs.latest_job(), "cutoff": market.completed_bar_cutoff().isoformat()}


@app.post("/api/update")
def update_market() -> dict[str, Any]:
    return jobs.manager.start("update")


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    result = jobs.job_details(job_id)
    if result is None:
        raise HTTPException(404, "未找到更新任务")
    return result


@app.get("/api/jobs/{job_id}/failures")
def job_failures(job_id: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    if db.row("SELECT id FROM jobs WHERE id=?", (job_id,)) is None:
        raise HTTPException(404, "未找到更新任务")
    return {"items": db.rows("SELECT code,error FROM job_failures WHERE job_id=? ORDER BY code LIMIT ? OFFSET ?",
                             (job_id, limit, offset)), "offset": offset, "limit": limit}


@app.get("/api/stocks")
def stocks(q: str = "", limit: int = Query(30, ge=1, le=100)) -> dict[str, Any]:
    return {"items": catalog.search_symbols(q, limit)}


def _bars(frame: pd.DataFrame, start: str | None, end: str | None, limit: int) -> list[dict[str, Any]]:
    if start:
        frame = frame[frame["date"] >= start]
    if end:
        frame = frame[frame["date"] <= end]
    if len(frame) > limit:
        frame = frame.tail(limit)
    return json.loads(frame.to_json(orient="records"))


@app.get("/api/stocks/{code}/bars")
def stock_bars(code: str, adjustment: str = "qfq", start: str | None = None,
               end: str | None = None, limit: int = Query(6000, ge=1, le=10000)) -> dict[str, Any]:
    if not catalog.is_a_share(code):
        raise HTTPException(422, "股票代码必须是六位 A 股代码")
    if adjustment not in {"raw", "qfq"}:
        raise HTTPException(422, "复权类型只能是 raw 或 qfq")
    symbol = db.row("SELECT * FROM symbols WHERE code=?", (code,))
    if symbol is None:
        raise HTTPException(404, "股票不在目录中")
    frame = market.read_bars(code, adjustment)
    return {"symbol": symbol, "adjustment": adjustment,
            "coverage": [{"start": first.isoformat(), "end": last.isoformat()}
                         for first, last in market.verified_intervals(code, adjustment)],
            "bars": _bars(frame, start, end, limit), "total_bars": len(frame)}


@app.get("/api/indexes/{code}/bars")
def index_bars(code: str, start: str | None = None, end: str | None = None,
               limit: int = Query(6000, ge=1, le=10000)) -> dict[str, Any]:
    if code not in market.INDEXES:
        raise HTTPException(404, "未知指数")
    frame = market.read_bars(code, index=True)
    return {"code": code, "name": market.INDEXES[code], "bars": _bars(frame, start, end, limit),
            "total_bars": len(frame)}
