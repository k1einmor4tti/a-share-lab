from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any, Callable

import akshare as ak
import pandas as pd

from .config import SEED_LIST
from .db import connection, row, rows

LOG = logging.getLogger(__name__)
CODE_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def normalize_code(value: object) -> str | None:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    match = CODE_PATTERN.search(text.zfill(6) if text.isdigit() else text)
    return match.group(1) if match else None


def is_a_share(code: str | None) -> bool:
    return bool(code and len(code) == 6 and code.isdigit()
                and code[0] in "036489" and not code.startswith(("200", "900")))


def exchange_of(code: str) -> str:
    if code.startswith("6"):
        return "SH"
    if code.startswith(("0", "3")):
        return "SZ"
    return "BJ"


def date_text(value: object) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        try:
            return datetime.strptime(text, "%Y%m%d").date().isoformat()
        except ValueError:
            return None
    try:
        return pd.Timestamp(text).date().isoformat()
    except (ValueError, TypeError):
        return None


def upsert_symbols(items: list[tuple[str, str, str | None, str | None]], status: str, source: str,
                   active_codes: set[str] | None = None) -> int:
    count = 0
    with connection() as db:
        for code, name, listing_date, delisting_date in items:
            if not is_a_share(code) or (status == "delisted" and active_codes and code in active_codes):
                continue
            db.execute(
                """INSERT INTO symbols(code,name,exchange,status,listing_date,delisting_date,catalog_source)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(code) DO UPDATE SET
                   name=excluded.name, exchange=excluded.exchange, status=excluded.status,
                   listing_date=COALESCE(excluded.listing_date,symbols.listing_date),
                   delisting_date=COALESCE(excluded.delisting_date,symbols.delisting_date),
                   catalog_source=excluded.catalog_source""",
                (code, (name or code).strip() or code, exchange_of(code), status,
                 listing_date, delisting_date, source),
            )
            count += 1
    return count


def seed_catalog() -> int:
    """Use a previously saved Eastmoney list only as a catalog seed, never bars."""
    if row("SELECT code FROM symbols LIMIT 1") or not SEED_LIST.exists():
        return 0
    try:
        payload = json.loads(SEED_LIST.read_text(encoding="utf-8"))
        items = []
        for entry in payload:
            code = normalize_code(entry.get("f12"))
            if is_a_share(code):
                items.append((code, str(entry.get("f14", code)), date_text(entry.get("f26")), None))
        return upsert_symbols(items, "listed", "本地东方财富清单快照")
    except (OSError, ValueError, TypeError) as exc:
        LOG.warning("Could not seed stock catalog: %s", exc)
        return 0


def _delist_items(df: pd.DataFrame, label: str) -> list[tuple[str, str, str | None, str | None]]:
    if df.empty:
        return []
    columns = list(df.columns)
    code_col = next((c for c in columns if "代码" in str(c)), None)
    name_col = next((c for c in columns if "简称" in str(c) or "名称" in str(c)), None)
    listing_col = next((c for c in columns if "上市日期" in str(c)), None)
    delisting_col = next((c for c in columns if any(x in str(c) for x in ("退市日期", "终止上市日期", "暂停上市日期"))), None)
    if code_col is None:
        LOG.warning("%s has no code column: %s", label, columns)
        return []
    result = []
    for entry in df.to_dict("records"):
        code = normalize_code(entry.get(code_col))
        if is_a_share(code):
            result.append((code, str(entry.get(name_col) or code) if name_col else code,
                           date_text(entry.get(listing_col)) if listing_col else None,
                           date_text(entry.get(delisting_col)) if delisting_col else None))
    return result


def refresh_catalog() -> dict[str, Any]:
    """Each endpoint is independent; a failure never discards saved symbols."""
    report: dict[str, Any] = {"sources": {}, "errors": []}
    active_codes: set[str] = set()
    try:
        frame = ak.stock_zh_a_spot_em()
        items = []
        for entry in frame.to_dict("records"):
            code = normalize_code(entry.get("代码"))
            if is_a_share(code):
                active_codes.add(code)
                items.append((code, str(entry.get("名称") or code), None, None))
        report["sources"]["东方财富在市股票"] = upsert_symbols(items, "listed", "东方财富", active_codes)
    except Exception as exc:
        report["errors"].append(f"东方财富在市股票: {exc}")
        LOG.warning("Active catalog source failed: %s", exc)
        active_codes = {entry["code"] for entry in rows("SELECT code FROM symbols WHERE status='listed'")}

    sources: tuple[tuple[str, Callable[[], pd.DataFrame]], ...] = (
        ("上交所退市名单", lambda: ak.stock_info_sh_delist(symbol="全部")),
        ("深交所退市名单", lambda: ak.stock_info_sz_delist(symbol="终止上市公司")),
        ("东方财富退市名单", ak.stock_zh_a_stop_em),
    )
    for label, fetch in sources:
        try:
            items = _delist_items(fetch(), label)
            report["sources"][label] = upsert_symbols(items, "delisted", label, active_codes)
        except Exception as exc:
            report["errors"].append(f"{label}: {exc}")
            LOG.warning("%s failed: %s", label, exc)
    report["total"] = row("SELECT COUNT(*) AS count FROM symbols")["count"]
    return report


def search_symbols(query: str, limit: int = 30) -> list[dict[str, Any]]:
    query = query.strip()
    if not query:
        return rows("SELECT code,name,exchange,status,bar_count,data_source,raw_last FROM symbols ORDER BY code LIMIT ?", (limit,))
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    prefix = f"{escaped}%"
    return rows(
        """SELECT code,name,exchange,status,bar_count,data_source,raw_last FROM symbols
           WHERE code LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\'
           ORDER BY CASE WHEN code=? THEN 0 WHEN code LIKE ? ESCAPE '\\' THEN 1 ELSE 2 END,name LIMIT ?""",
        (pattern, pattern, query, prefix, limit),
    )
