from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from .catalog import exchange_of
from .config import BARS_DIR
from .db import connection, execute, row, rows, utc_now

LOG = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
INDEXES = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    "sh000300": "沪深300",
    "sh000905": "中证500",
}
BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "turnover", "source"]
_EASTMONEY_LOCK = threading.Lock()
_EASTMONEY_BLOCKED_UNTIL = 0.0
_EASTMONEY_NEXT_REQUEST = 0.0
_SYMBOL_LOCKS: dict[str, threading.RLock] = {}
_SYMBOL_LOCKS_GUARD = threading.Lock()


def history_start() -> date:
    today = datetime.now(SHANGHAI).date()
    try:
        return today.replace(year=today.year - 20)
    except ValueError:
        return today.replace(year=today.year - 20, day=28)


def completed_bar_cutoff() -> date:
    now = datetime.now(SHANGHAI)
    if (now.hour, now.minute) < (15, 30):
        return now.date() - timedelta(days=1)
    return now.date()


def bar_path(code: str, adjustment: str, *, index: bool = False) -> Path:
    return BARS_DIR / ("index" if index else adjustment) / f"{code}.parquet"


def read_bars(code: str, adjustment: str = "qfq", *, index: bool = False) -> pd.DataFrame:
    path = bar_path(code, adjustment, index=index)
    return pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=BAR_COLUMNS)


def _write_bars(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        frame.to_parquet(temp, index=False, compression="zstd")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _merge(existing: pd.DataFrame, fetched: pd.DataFrame) -> pd.DataFrame:
    if existing.empty:
        combined = fetched.copy()
    elif fetched.empty:
        combined = existing.copy()
    else:
        combined = pd.concat([existing, fetched], ignore_index=True)
    if combined.empty:
        return pd.DataFrame(columns=BAR_COLUMNS)
    return combined.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)[BAR_COLUMNS]


def normalize_bars(frame: pd.DataFrame, source: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=BAR_COLUMNS)
    aliases = {"日期": "date", "开盘": "open", "最高": "high", "最低": "low", "收盘": "close",
               "成交量": "volume", "成交额": "amount", "换手率": "turnover", "turn": "turnover"}
    data = frame.rename(columns=aliases).copy()
    required = ("date", "open", "high", "low", "close")
    missing = [column for column in required if column not in data]
    if missing:
        raise ValueError(f"{source} 缺少字段: {', '.join(missing)}")
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for column in BAR_COLUMNS[1:-1]:
        if column not in data:
            data[column] = 0.0
        data[column] = pd.to_numeric(data[column], errors="coerce")
    if source == "东方财富":
        data["volume"] = data["volume"] * 100.0  # Eastmoney reports lots, engine uses shares.
    data["source"] = source
    data = data[BAR_COLUMNS].dropna(subset=required)
    data = data[(data["date"] <= completed_bar_cutoff().isoformat()) & (data["close"] > 0)]
    return data.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def _baostock_stock(code: str, start: date, end: date, adjustment: str) -> pd.DataFrame:
    import baostock as bs

    exchange = exchange_of(code)
    if exchange == "BJ":
        raise ValueError("BaoStock 不支持北交所股票")
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock login: {login.error_msg}")
    try:
        result = bs.query_history_k_data_plus(
            f"{exchange.lower()}.{code}", "date,open,high,low,close,volume,amount,turn",
            start_date=start.isoformat(), end_date=end.isoformat(), frequency="d",
            adjustflag="2" if adjustment == "qfq" else "3",
        )
        if result.error_code != "0":
            raise RuntimeError(result.error_msg)
        values = []
        while result.next():
            values.append(result.get_row_data())
        frame = pd.DataFrame(values, columns=["date", "open", "high", "low", "close", "volume", "amount", "turnover"])
        return normalize_bars(frame, "BaoStock")
    finally:
        bs.logout()


def _eastmoney_history(secid: str, start: date, end: date, adjustment: str) -> pd.DataFrame:
    """Use Eastmoney directly because the host's optional proxy breaks AKShare's session."""
    global _EASTMONEY_BLOCKED_UNTIL, _EASTMONEY_NEXT_REQUEST
    with _EASTMONEY_LOCK:
        now = time.monotonic()
        if now < _EASTMONEY_BLOCKED_UNTIL:
            raise RuntimeError("东方财富暂时不可用，等待重试窗口")
        if now < _EASTMONEY_NEXT_REQUEST:
            time.sleep(_EASTMONEY_NEXT_REQUEST - now)
        _EASTMONEY_NEXT_REQUEST = time.monotonic() + 0.25
    params = {
        "secid": secid, "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101", "fqt": "1" if adjustment == "qfq" else "0",
        "beg": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"), "lmt": "1000000",
    }
    errors = []
    session = requests.Session()
    session.trust_env = False
    try:
        for host in ("push2his.eastmoney.com", "7.push2his.eastmoney.com", "33.push2his.eastmoney.com"):
            try:
                response = session.get(f"https://{host}/api/qt/stock/kline/get", params=params,
                                       headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
                                       timeout=(5, 15))
                response.raise_for_status()
                payload = response.json()
                if payload.get("rc") != 0:
                    raise RuntimeError(f"Eastmoney rc={payload.get('rc')}")
                lines = (payload.get("data") or {}).get("klines") or []
                values = [line.split(",") for line in lines]
                if any(len(value) < 11 for value in values):
                    raise ValueError("Eastmoney returned an incomplete kline")
                frame = pd.DataFrame(values, columns=["date", "open", "close", "high", "low", "volume",
                                                      "amount", "amplitude", "pct_change", "change", "turnover"])
                with _EASTMONEY_LOCK:
                    _EASTMONEY_BLOCKED_UNTIL = 0.0
                return normalize_bars(frame, "东方财富")
            except (requests.RequestException, ValueError, RuntimeError) as exc:
                errors.append(f"{host}: {exc}")
    finally:
        session.close()
    with _EASTMONEY_LOCK:
        _EASTMONEY_BLOCKED_UNTIL = time.monotonic() + 300
    raise RuntimeError("; ".join(errors)[:1000])


def fetch_stock(code: str, start: date, end: date, adjustment: str) -> tuple[pd.DataFrame, str]:
    """Primary Eastmoney, then named public fallback. Empty initial fetch is an error."""
    errors: list[str] = []
    empty_primary = False
    try:
        secid = ("1" if exchange_of(code) == "SH" else "0") + "." + code
        normalized = _eastmoney_history(secid, start, end, adjustment)
        if not normalized.empty:
            return normalized, "东方财富"
        empty_primary = True
    except Exception as exc:
        errors.append(f"东方财富: {exc}")
    try:
        fallback = _baostock_stock(code, start, end, adjustment)
        if not fallback.empty:
            return fallback, "BaoStock"
        if empty_primary:
            return fallback, "东方财富"
    except Exception as exc:
        errors.append(f"BaoStock: {exc}")
    raise RuntimeError("; ".join(errors)[:1000])


def fetch_index(code: str, start: date, end: date) -> tuple[pd.DataFrame, str]:
    if code not in INDEXES:
        raise ValueError(f"不支持的指数: {code}")
    try:
        secid = ("1" if code.startswith("sh") else "0") + "." + code[2:]
        primary = _eastmoney_history(secid, start, end, "raw")
        if not primary.empty:
            return primary, "东方财富"
    except Exception as primary_error:
        LOG.warning("Eastmoney index %s failed: %s", code, primary_error)
    import baostock as bs

    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock: {login.error_msg}")
    try:
        symbol = f"{code[:2]}.{code[2:]}"
        result = bs.query_history_k_data_plus(symbol, "date,open,high,low,close,volume,amount",
                                              start_date=start.isoformat(), end_date=end.isoformat(), frequency="d")
        if result.error_code != "0":
            raise RuntimeError(result.error_msg)
        values = []
        while result.next():
            values.append(result.get_row_data())
        raw = pd.DataFrame(values, columns=["date", "open", "high", "low", "close", "volume", "amount"])
        return normalize_bars(raw, "BaoStock"), "BaoStock"
    finally:
        bs.logout()


def verified_intervals(code: str, adjustment: str) -> list[tuple[date, date]]:
    entries = rows("SELECT start_date,end_date FROM coverage WHERE code=? AND adjustment=? ORDER BY start_date",
                   (code, adjustment))
    return [(date.fromisoformat(x["start_date"]), date.fromisoformat(x["end_date"])) for x in entries]


def unchecked_ranges(code: str, adjustment: str, start: date, end: date) -> list[tuple[date, date]]:
    """Date interval complement. Market-closed days inside verified ranges remain verified."""
    if start > end:
        return []
    cursor = start
    missing = []
    for first, last in verified_intervals(code, adjustment):
        if last < cursor:
            continue
        if first > end:
            break
        if first > cursor:
            missing.append((cursor, min(end, first - timedelta(days=1))))
        cursor = max(cursor, last + timedelta(days=1))
        if cursor > end:
            break
    if cursor <= end:
        missing.append((cursor, end))
    return missing


def mark_verified(code: str, adjustment: str, start: date, end: date, source: str) -> None:
    execute("""INSERT INTO coverage(code,adjustment,start_date,end_date,source,checked_at)
               VALUES(?,?,?,?,?,?) ON CONFLICT(code,adjustment,start_date,end_date) DO UPDATE SET
               source=excluded.source, checked_at=excluded.checked_at""",
            (code, adjustment, start.isoformat(), end.isoformat(), source, utc_now()))


def _expected_sessions(first: date, last: date) -> set[date]:
    """Use cached Shanghai closes as the calendar, with a conservative tail."""
    path = bar_path("sh000001", "index", index=True)
    index_dates = _index_calendar(str(path), path.stat().st_mtime_ns) if path.exists() else ()
    if index_dates:
        known = {value for value in index_dates if first <= value <= last}
        first_known = index_dates[0]
        last_known = index_dates[-1]
        if first >= first_known:
            cursor = max(first, last_known + timedelta(days=1))
            while cursor <= last:
                if cursor.weekday() < 5:
                    known.add(cursor)
                cursor += timedelta(days=1)
            return known
    return {day.date() for day in pd.date_range(first, last, freq="B")}


@lru_cache(maxsize=8)
def _index_calendar(path: str, modified_ns: int) -> tuple[date, ...]:
    del modified_ns  # The modification time is part of the cache key.
    frame = pd.read_parquet(path, columns=["date"])
    return tuple(date.fromisoformat(str(value)) for value in frame["date"])


def _confirmed_intervals(first: date, last: date, observed: set[date],
                         absent_confirmed: set[date] | None = None,
                         expected_override: set[date] | None = None) -> list[tuple[date, date]]:
    """Only mark observed sessions or independently confirmed suspensions."""
    expected = expected_override if expected_override is not None else _expected_sessions(first, last)
    confirmed = observed | (absent_confirmed or set())
    result: list[tuple[date, date]] = []
    begin: date | None = None
    cursor = first
    while cursor <= last:
        covered = cursor not in expected or cursor in confirmed
        if covered and begin is None:
            begin = cursor
        elif not covered and begin is not None:
            result.append((begin, cursor - timedelta(days=1)))
            begin = None
        cursor += timedelta(days=1)
    if begin is not None:
        result.append((begin, last))
    return result


def _bar_dates(frame: pd.DataFrame) -> set[date]:
    return {date.fromisoformat(str(value)) for value in frame["date"]}


def _confirm_absences(code: str, adjustment: str, missing: set[date],
                      primary_source: str, cutoff: date) -> tuple[pd.DataFrame, set[date]]:
    """Check past missing trading dates against a second provider in batches.

    A missing current-day close is always left open for another Update click.
    """
    if primary_source != "东方财富" or exchange_of(code) == "BJ":
        return pd.DataFrame(columns=BAR_COLUMNS), set()
    candidates = sorted(day for day in missing if day < cutoff)
    if not candidates:
        return pd.DataFrame(columns=BAR_COLUMNS), set()
    try:
        other = _baostock_stock(code, candidates[0], candidates[-1], adjustment)
    except Exception as exc:
        LOG.warning("Could not confirm missing sessions for %s: %s", code, exc)
        return pd.DataFrame(columns=BAR_COLUMNS), set()
    observed = {date.fromisoformat(str(value)) for value in other["date"]}
    return other, set(candidates) - observed


def _record_symbol_metadata(code: str) -> dict[str, object]:
    raw = read_bars(code, "raw")
    adjusted = read_bars(code, "qfq")
    sources = sorted(set(raw["source"].dropna()) | set(adjusted["source"].dropna()))
    summary = ", ".join(sources)
    execute(
        """UPDATE symbols SET raw_first=?,raw_last=?,adjusted_first=?,adjusted_last=?,
           bar_count=?,data_source=?,sync_error=NULL,updated_at=? WHERE code=?""",
        (str(raw["date"].iloc[0]) if not raw.empty else None,
         str(raw["date"].iloc[-1]) if not raw.empty else None,
         str(adjusted["date"].iloc[0]) if not adjusted.empty else None,
         str(adjusted["date"].iloc[-1]) if not adjusted.empty else None,
         len(raw), summary or None, utc_now(), code),
    )
    return {"code": code, "bars": len(raw), "adjusted_bars": len(adjusted), "source": summary}


def symbol_lock(code: str) -> threading.RLock:
    """Serialize an individual symbol's two-file update with snapshot reads."""
    with _SYMBOL_LOCKS_GUARD:
        return _SYMBOL_LOCKS.setdefault(code, threading.RLock())


def sync_stock(code: str, *, target: date | None = None) -> dict[str, object]:
    with symbol_lock(code):
        return _sync_stock_locked(code, target=target)


def _sync_stock_locked(code: str, *, target: date | None = None) -> dict[str, object]:
    symbol = row("SELECT * FROM symbols WHERE code=?", (code,))
    if not symbol:
        raise ValueError(f"未知股票代码: {code}")
    cutoff = min(target or completed_bar_cutoff(), completed_bar_cutoff())
    if symbol["delisting_date"]:
        cutoff = min(cutoff, date.fromisoformat(symbol["delisting_date"]))
    start = max(history_start(), date.fromisoformat(symbol["listing_date"])) if symbol["listing_date"] else history_start()
    if start > cutoff:
        return {"code": code, "status": "skipped", "reason": "上市范围外"}

    missing = {adjustment: unchecked_ranges(code, adjustment, start, cutoff) for adjustment in ("raw", "qfq")}
    if not missing["raw"] and not missing["qfq"]:
        return {"code": code, "status": "skipped", "reason": "已验证到最新日期"}

    staged: dict[str, pd.DataFrame] = {}
    checked: list[tuple[str, date, date, str]] = []
    for adjustment in ("raw", "qfq"):
        staged[adjustment] = read_bars(code, adjustment)
        for first, last in missing[adjustment]:
            frame, source = fetch_stock(code, first, last, adjustment)
            expected = _expected_sessions(first, last)
            absent = expected - _bar_dates(frame)
            supplemental, confirmed_absent = _confirm_absences(code, adjustment, absent, source, cutoff)
            if not supplemental.empty:
                supplemental = supplemental[supplemental["date"].isin({day.isoformat() for day in absent})]
            if frame.empty and supplemental.empty and staged[adjustment].empty:
                raise RuntimeError(f"{source} 未返回 {adjustment} 历史行情")
            staged[adjustment] = _merge(staged[adjustment], frame)
            staged[adjustment] = _merge(staged[adjustment], supplemental)
            observed = _bar_dates(frame) | _bar_dates(supplemental)
            label = source + ("+BaoStock" if confirmed_absent else "")
            for covered_first, covered_last in _confirmed_intervals(first, last, observed, confirmed_absent, expected):
                checked.append((adjustment, covered_first, covered_last, label))

    # A corporate action can rebase every prior qfq price. Recheck the earliest
    # stored close and replace the adjusted series if its value has changed.
    rebased = False
    prior_adjusted = read_bars(code, "qfq")
    if not prior_adjusted.empty and missing["qfq"]:
        anchor = date.fromisoformat(str(prior_adjusted["date"].iloc[0]))
        probe, _ = fetch_stock(code, anchor, anchor, "qfq")
        if not probe.empty:
            old_close = float(prior_adjusted["close"].iloc[0])
            new_close = float(probe["close"].iloc[0])
            rebased = abs(new_close - old_close) > max(0.005, old_close * 0.0005)
    if rebased:
        replacement, source = fetch_stock(code, start, cutoff, "qfq")
        if replacement.empty:
            raise RuntimeError("复权价格变化后重拉失败")
        if not _bar_dates(prior_adjusted).issubset(_bar_dates(replacement)):
            raise RuntimeError("复权重拉只返回部分历史，保留旧数据等待重试")
        staged["qfq"] = replacement
        expected = _expected_sessions(start, cutoff)
        covered = _confirmed_intervals(start, cutoff, _bar_dates(replacement), expected_override=expected)
        checked = [item for item in checked if item[0] != "qfq"] + [
            ("qfq", first, last, source) for first, last in covered]

    for adjustment, frame in staged.items():
        if not frame.empty:
            _write_bars(bar_path(code, adjustment), frame)
    with connection() as db:
        if rebased:
            db.execute("DELETE FROM coverage WHERE code=? AND adjustment='qfq'", (code,))
        for adjustment, first, last, source in checked:
            db.execute("""INSERT INTO coverage(code,adjustment,start_date,end_date,source,checked_at)
                       VALUES(?,?,?,?,?,?) ON CONFLICT(code,adjustment,start_date,end_date) DO UPDATE SET
                       source=excluded.source,checked_at=excluded.checked_at""",
                       (code, adjustment, first.isoformat(), last.isoformat(), source, utc_now()))
    result = _record_symbol_metadata(code)
    result.update({"status": "updated", "rebased": rebased,
                   "checked_ranges": len(checked), "new_bars": len(staged["raw"]) - int(symbol["bar_count"] or 0)})
    return result


def sync_index(code: str, *, target: date | None = None) -> dict[str, object]:
    cutoff = min(target or completed_bar_cutoff(), completed_bar_cutoff())
    ranges = unchecked_ranges(code, "index", history_start(), cutoff)
    if not ranges:
        return {"code": code, "status": "skipped"}
    staged = read_bars(code, index=True)
    checked = []
    for first, last in ranges:
        frame, source = fetch_index(code, first, last)
        if frame.empty and staged.empty:
            raise RuntimeError("指数接口未返回历史行情")
        staged = _merge(staged, frame)
        observed = _bar_dates(frame)
        # The exchange index itself defines historical sessions. Only its
        # unreturned, recent weekday tail is left open for a later update.
        latest = max(observed) if observed else first - timedelta(days=1)
        expected = observed | {day.date() for day in pd.date_range(max(first, latest + timedelta(days=1)), last, freq="B")}
        checked.extend((covered_first, covered_last, source) for covered_first, covered_last
                       in _confirmed_intervals(first, last, observed, expected_override=expected))
    _write_bars(bar_path(code, "index", index=True), staged)
    for first, last, source in checked:
        mark_verified(code, "index", first, last, source)
    execute(
        """INSERT INTO indexes(code,name,first_date,last_date,bar_count,sync_error,updated_at)
           VALUES(?,?,?,?,?,NULL,?) ON CONFLICT(code) DO UPDATE SET first_date=excluded.first_date,
           last_date=excluded.last_date,bar_count=excluded.bar_count,sync_error=NULL,updated_at=excluded.updated_at""",
        (code, INDEXES[code], str(staged["date"].iloc[0]), str(staged["date"].iloc[-1]), len(staged), utc_now()),
    )
    return {"code": code, "status": "updated", "bars": len(staged), "source": sorted(set(staged["source"]))}


def index_cards() -> list[dict[str, object]]:
    result = []
    for code, name in INDEXES.items():
        frame = read_bars(code, index=True)
        latest = frame.iloc[-1] if not frame.empty else None
        prior = frame.iloc[-2] if len(frame) > 1 else None
        result.append({
            "code": code, "name": name,
            "date": str(latest["date"]) if latest is not None else None,
            "close": float(latest["close"]) if latest is not None else None,
            "change_pct": round((float(latest["close"]) / float(prior["close"]) - 1) * 100, 2) if prior is not None and prior["close"] else None,
            "source": str(latest["source"]) if latest is not None else None,
        })
    return result
