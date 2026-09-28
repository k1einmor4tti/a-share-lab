"""AKQuant execution and immutable, reopenable backtest reports."""

from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import io
import json
import math
import os
import platform
import shutil
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import akquant
import pandas as pd

from . import db, market, strategies
from .config import RESULTS_DIR


@dataclass(frozen=True)
class ExecutionOptions:
    initial_cash: float = 100_000.0
    allocation: float = 0.70
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    min_commission: float = 5.0
    slippage_rate: float = 0.0002

    @classmethod
    def parse(cls, supplied: dict[str, Any] | None = None) -> "ExecutionOptions":
        supplied = supplied or {}
        defaults = asdict(cls())
        unknown = set(supplied) - set(defaults)
        if unknown:
            raise ValueError(f"未知交易参数: {', '.join(sorted(unknown))}")
        values: dict[str, float] = {}
        for key, default in defaults.items():
            try:
                value = float(supplied.get(key, default))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"交易参数 {key} 必须为数字") from exc
            if not math.isfinite(value):
                raise ValueError(f"交易参数 {key} 必须为有限数字")
            values[key] = value
        if not 1_000 <= values["initial_cash"] <= 1_000_000_000:
            raise ValueError("初始资金范围为 1,000 到 1,000,000,000 元")
        if not 0.1 <= values["allocation"] <= 0.95:
            raise ValueError("目标资金比例范围为 0.1 到 0.95")
        for key in ("commission_rate", "stamp_tax_rate", "transfer_fee_rate", "slippage_rate"):
            if not 0 <= values[key] <= 0.05:
                raise ValueError(f"{key} 范围为 0 到 0.05")
        if not 0 <= values["min_commission"] <= 100:
            raise ValueError("最低佣金范围为 0 到 100 元")
        return cls(**values)


def _date(value: str | date | None, default: str) -> str:
    if value is None:
        return default
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValueError("日期必须使用 YYYY-MM-DD") from exc


def _strategy_class(code: str, desired: dict[str, bool], allocation: float) -> type[akquant.Strategy]:
    class DailySignalStrategy(akquant.Strategy):
        def on_bar(self, bar: akquant.Bar) -> None:
            day = pd.Timestamp(bar.timestamp, unit="ns", tz="UTC").tz_convert("Asia/Shanghai").date().isoformat()
            target = desired.get(day, False)
            position = float(self.get_position(code))
            if target and position <= 0:
                # A 30% next-open gap remains affordable at the default 70%
                # allocation. The engine independently enforces 100-share lots.
                quantity = math.floor(float(self.cash) * allocation / float(bar.close) / 100) * 100
                if quantity > 0:
                    self.buy(code, quantity=quantity)
            elif not target and position > 0:
                self.sell(code, quantity=position)

    return DailySignalStrategy


def _safe(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    if hasattr(value, "total_seconds"):
        return value.total_seconds()
    if hasattr(value, "item"):
        return _safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_backtest(code: str, strategy: str, params: dict[str, Any] | None = None,
                 *, start: str | date | None = None, end: str | date | None = None,
                 execution: dict[str, Any] | None = None) -> dict[str, Any]:
    symbol = db.row("SELECT code,name FROM symbols WHERE code=?", (code,))
    if symbol is None:
        raise ValueError(f"未知股票代码: {code}")
    options = ExecutionOptions.parse(execution)
    module, resolved = strategies.validate_params(strategy, params)
    cutoff = market.completed_bar_cutoff().isoformat()
    with market.symbol_lock(code):
        all_raw = market.read_bars(code, "raw")
        all_qfq = market.read_bars(code, "qfq")
    all_raw = all_raw[all_raw["date"] <= cutoff].reset_index(drop=True)
    all_qfq = all_qfq[all_qfq["date"] <= cutoff].reset_index(drop=True)
    if all_raw.empty or all_qfq.empty:
        raise ValueError(f"{code} 尚无完整的原始及前复权日线，请先更新该股票")
    first = _date(start, str(all_raw["date"].iloc[0]))
    last = _date(end, str(all_raw["date"].iloc[-1]))
    if first > last:
        raise ValueError("开始日期不能晚于结束日期")
    raw = all_raw[(all_raw["date"] >= first) & (all_raw["date"] <= last)].reset_index(drop=True)
    adjusted = all_qfq[all_qfq["date"] <= last].reset_index(drop=True)
    adjusted_window = adjusted[adjusted["date"] >= first]
    if raw.empty:
        raise ValueError("所选日期范围没有可用日线")
    if set(raw["date"]) != set(adjusted_window["date"]):
        raise ValueError("原始行情与前复权行情日期不一致，请更新后重试")
    requested_first, requested_last = date.fromisoformat(first), date.fromisoformat(last)
    for adjustment in ("raw", "qfq"):
        if market.unchecked_ranges(code, adjustment, requested_first, requested_last):
            raise ValueError(f"{code} 的 {adjustment} 日线仍有未验证日期，请更新后回测")
    if len(adjusted) < module.minimum_bars(resolved):
        raise ValueError(f"{module.name} 至少需要 {module.minimum_bars(resolved)} 根日线，当前只有 {len(adjusted)} 根")
    signal_frame, resolved = strategies.signals(strategy, adjusted, resolved)
    desired = dict(zip(signal_frame["date"], signal_frame["target"]))

    benchmark = market.read_bars("sh000300", index=True)
    benchmark = benchmark[(benchmark["date"] >= first) & (benchmark["date"] <= last)].reset_index(drop=True)
    if benchmark.empty:
        raise ValueError("沪深300基准日线尚未下载，请先更新大盘指数")
    if market.unchecked_ranges("sh000300", "index", requested_first, requested_last):
        raise ValueError("沪深300基准日线仍有未验证日期，请先更新指数")

    run_id = uuid.uuid4().hex
    directory = RESULTS_DIR / run_id
    directory.mkdir(parents=True, exist_ok=False)
    try:
        # Signal and execution histories are both part of the immutable input.
        snapshot = adjusted.rename(columns={column: f"qfq_{column}" for column in adjusted if column != "date"})
        raw_snapshot = raw.rename(columns={column: f"raw_{column}" for column in raw if column != "date"})
        snapshot = snapshot.merge(raw_snapshot, on="date", how="outer", validate="one_to_one").sort_values("date")
        snapshot_path = directory / "stock-input.parquet"
        benchmark_path = directory / "benchmark-input.parquet"
        snapshot.to_parquet(snapshot_path, index=False, compression="zstd")
        benchmark.to_parquet(benchmark_path, index=False, compression="zstd")
        hashes = {snapshot_path.name: _digest(snapshot_path), benchmark_path.name: _digest(benchmark_path)}

        # Forward-adjusted prices include the value effect of splits/dividends.
        # Raw fills without explicit corporate actions create false large losses.
        engine_frame = adjusted_window[["date", "open", "high", "low", "close", "volume"]].copy()
        engine_frame = engine_frame[engine_frame["volume"] > 0].reset_index(drop=True)
        if len(engine_frame) < 2:
            raise ValueError("可交易日线不足两根，无法执行回测")
        engine_frame["date"] = pd.to_datetime(engine_frame["date"]) + pd.Timedelta(hours=15)
        engine_result = akquant.run_backtest(
            data=engine_frame, strategy=_strategy_class(code, desired, options.allocation), symbols=code,
            initial_cash=options.initial_cash, t_plus_one=True, lot_size=100,
            commission_rate=options.commission_rate, stamp_tax_rate=options.stamp_tax_rate,
            transfer_fee_rate=options.transfer_fee_rate, min_commission=options.min_commission,
            slippage={"type": "percent", "value": options.slippage_rate},
            fill_policy=akquant.NextOpen(),
            timezone="Asia/Shanghai", show_progress=False,
        )
        equity = [{"date": timestamp.date().isoformat(), "value": float(value)}
                  for timestamp, value in engine_result.equity_curve.items()]
        benchmark_close = {str(row["date"]): float(row["close"]) for _, row in benchmark.iterrows()}
        missing_benchmark = [item["date"] for item in equity if item["date"] not in benchmark_close]
        if missing_benchmark:
            raise ValueError(f"沪深300基准缺少 {missing_benchmark[0]} 等交易日，请先更新指数")
        first_close = benchmark_close[equity[0]["date"]]
        benchmark_curve = [{"date": item["date"], "value": options.initial_cash * benchmark_close[item["date"]] / first_close}
                           for item in equity]
        metrics = {str(key): _safe(value) for key, value in engine_result.metrics_df["value"].items()}
        metrics["benchmark_return_pct"] = ((benchmark_curve[-1]["value"] / options.initial_cash - 1) * 100
                                            if benchmark_curve else None)
        report = {
            "id": run_id, "code": code, "name": symbol["name"], "strategy": strategy,
            "strategy_name": module.name, "params": resolved, "execution": asdict(options),
            "start": first, "end": last, "actual_start": str(raw["date"].iloc[0]),
            "actual_end": str(raw["date"].iloc[-1]),
            "adjustment": "前复权信号 + 前复权成交代理",
            "benchmark": "沪深300", "created_at": db.utc_now(),
            "versions": {"akquant": akquant.__version__, "akquant_rules": akquant.__engine_rule_version__,
                         "pandas": pd.__version__, "python": platform.python_version(),
                         "platform_code_sha256": hashlib.sha256((inspect.getsource(module.calculate)
                            + inspect.getsource(strategies.signals) + inspect.getsource(_strategy_class)
                            + inspect.getsource(run_backtest)).encode()).hexdigest(),
                         **{name: importlib.metadata.version(name) for name in ("akshare", "baostock", "pyarrow")}},
            "input_sha256": hashes, "metrics": metrics, "equity": equity,
            "benchmark_equity": benchmark_curve, "orders": _records(engine_result.orders_df),
            "trades": _records(engine_result.trades_df),
            "assumptions": ["收盘后生成信号，下一交易日开盘成交；T+1；100股整手",
                            "成交使用前复权价格代理公司行动后的持仓价值；绝对成交价、股数和最低佣金与真实历史交易有差异",
                            "停牌以缺失或零成交量日线近似处理；未启用成交量参与率限制，流动性与涨跌停无法成交未逐日精确建模",
                            "费率在整个回测区间固定，不自动切换历史税率"],
            "data_sources": sorted(set(raw["source"].dropna()) | set(adjusted["source"].dropna())),
            "benchmark_coverage": {"first": str(benchmark["date"].iloc[0]),
                                   "last": str(benchmark["date"].iloc[-1]),
                                   "source": sorted(set(benchmark["source"].dropna()))},
        }
        path = directory / "result.json"
        temp = directory / ".result.tmp"
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temp, path)
        db.execute("INSERT INTO backtests(id,code,strategy,created_at,params_json,result_path) VALUES(?,?,?,?,?,?)",
                   (run_id, code, strategy, report["created_at"],
                    json.dumps({"params": resolved, "execution": asdict(options)}, ensure_ascii=False), str(path)))
        return report
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def saved_backtest(run_id: str) -> dict[str, Any] | None:
    record = db.row("SELECT result_path FROM backtests WHERE id=?", (run_id,))
    if record is None:
        return None
    return json.loads(Path(record["result_path"]).read_text(encoding="utf-8"))


def list_backtests(limit: int = 50) -> list[dict[str, Any]]:
    return db.rows("SELECT id,code,strategy,created_at FROM backtests ORDER BY created_at DESC LIMIT ?", (limit,))


def export_backtest(run_id: str) -> bytes:
    """Return a ZIP with report, immutable inputs and table-friendly CSVs."""
    record = db.row("SELECT result_path FROM backtests WHERE id=?", (run_id,))
    if record is None:
        raise ValueError(f"未知回测记录: {run_id}")
    result_path = Path(record["result_path"])
    report = json.loads(result_path.read_text(encoding="utf-8"))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("result.json", "stock-input.parquet", "benchmark-input.parquet"):
            archive.write(result_path.parent / name, arcname=name)
        for key in ("equity", "benchmark_equity", "orders", "trades"):
            archive.writestr(f"{key}.csv", pd.DataFrame(report[key]).to_csv(index=False))
    return output.getvalue()
