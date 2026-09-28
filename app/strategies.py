"""Registered, pure daily-close signal modules.

`target` means the desired position after the *next* session's execution. A
signal on date D only uses bars through D; the engine handles order timing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd


@dataclass(frozen=True)
class Parameter:
    label: str
    default: int | float
    minimum: int | float
    maximum: int | float
    kind: str = "integer"

    def describe(self, key: str) -> dict[str, Any]:
        return {"key": key, "label": self.label, "default": self.default,
                "min": self.minimum, "max": self.maximum, "type": self.kind}


@dataclass(frozen=True)
class StrategyModule:
    key: str
    name: str
    description: str
    parameters: dict[str, Parameter]
    minimum_bars: Callable[[dict[str, int | float]], int]
    calculate: Callable[[pd.DataFrame, dict[str, int | float]], pd.Series]

    def schema(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "description": self.description,
                "parameters": [definition.describe(key) for key, definition in self.parameters.items()]}


def _buy_hold(bars: pd.DataFrame, _: dict[str, int | float]) -> pd.Series:
    return pd.Series(True, index=bars.index, dtype=bool)


def _moving_average(bars: pd.DataFrame, params: dict[str, int | float]) -> pd.Series:
    fast = bars["close"].rolling(int(params["fast"]), min_periods=int(params["fast"])).mean()
    slow = bars["close"].rolling(int(params["slow"]), min_periods=int(params["slow"])).mean()
    return (fast > slow).fillna(False)


def _turtle(bars: pd.DataFrame, params: dict[str, int | float]) -> pd.Series:
    entry = bars["high"].shift(1).rolling(int(params["entry"]), min_periods=int(params["entry"])).max()
    exit_level = bars["low"].shift(1).rolling(int(params["exit"]), min_periods=int(params["exit"])).min()
    held = False
    positions = []
    for close, upper, lower in zip(bars["close"], entry, exit_level):
        if held and pd.notna(lower) and close < lower:
            held = False
        elif not held and pd.notna(upper) and close > upper:
            held = True
        positions.append(held)
    return pd.Series(positions, index=bars.index, dtype=bool)


def _rsi(bars: pd.DataFrame, params: dict[str, int | float]) -> pd.Series:
    period = int(params["period"])
    delta = bars["close"].diff()
    gain = delta.clip(lower=0).rolling(period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).rolling(period, min_periods=period).mean()
    indicator = 100 - 100 / (1 + gain / loss.replace(0, float("nan")))
    indicator = indicator.mask((loss == 0) & (gain > 0), 100)
    indicator = indicator.mask((loss == 0) & (gain == 0), 50)
    held = False
    positions = []
    for value in indicator:
        if pd.notna(value):
            if held and value >= params["overbought"]:
                held = False
            elif not held and value <= params["oversold"]:
                held = True
        positions.append(held)
    return pd.Series(positions, index=bars.index, dtype=bool)


def _bollinger(bars: pd.DataFrame, params: dict[str, int | float]) -> pd.Series:
    close = bars["close"]
    window = int(params["window"])
    average = close.rolling(window, min_periods=window).mean()
    deviation = close.rolling(window, min_periods=window).std(ddof=0)
    lower = average - float(params["width"]) * deviation
    upper = average + float(params["width"]) * deviation
    held = False
    positions = []
    for price, low, high in zip(close, lower, upper):
        if held and pd.notna(high) and price >= high:
            held = False
        elif not held and pd.notna(low) and price <= low:
            held = True
        positions.append(held)
    return pd.Series(positions, index=bars.index, dtype=bool)


MODULES = {
    "buy_hold": StrategyModule("buy_hold", "买入持有", "首个收盘信号后买入并持有。", {}, lambda _: 2, _buy_hold),
    "ma_cross": StrategyModule("ma_cross", "均线交叉", "短期均线高于长期均线时持有。",
        {"fast": Parameter("短均线（日）", 20, 2, 250), "slow": Parameter("长均线（日）", 60, 3, 500)},
        lambda p: int(p["slow"]) + 1, _moving_average),
    "turtle": StrategyModule("turtle", "海龟突破", "收盘突破此前高点入场，跌破此前低点离场。",
        {"entry": Parameter("入场突破（日）", 20, 2, 250), "exit": Parameter("离场突破（日）", 10, 2, 250)},
        lambda p: int(p["entry"]) + 2, _turtle),
    "rsi": StrategyModule("rsi", "RSI 反转", "RSI 低于超卖阈值入场，高于超买阈值离场。",
        {"period": Parameter("RSI 周期（日）", 14, 2, 250),
         "oversold": Parameter("超卖阈值", 30, 1, 49),
         "overbought": Parameter("超买阈值", 70, 51, 99)},
        lambda p: int(p["period"]) + 2, _rsi),
    "bollinger": StrategyModule("bollinger", "布林带", "收盘低于下轨入场，高于上轨离场。",
        {"window": Parameter("均线周期（日）", 20, 2, 250),
         "width": Parameter("标准差倍数", 2.0, 0.5, 5.0, "number")},
        lambda p: int(p["window"]) + 1, _bollinger),
}


def module_schemas() -> list[dict[str, Any]]:
    return [module.schema() for module in MODULES.values()]


def validate_params(key: str, supplied: dict[str, Any] | None = None) -> tuple[StrategyModule, dict[str, int | float]]:
    if key not in MODULES:
        raise ValueError(f"未知策略模块: {key}")
    module = MODULES[key]
    supplied = supplied or {}
    unknown = set(supplied) - set(module.parameters)
    if unknown:
        raise ValueError(f"未知参数: {', '.join(sorted(unknown))}")
    result: dict[str, int | float] = {}
    for name, definition in module.parameters.items():
        raw = supplied.get(name, definition.default)
        try:
            value = int(raw) if definition.kind == "integer" else float(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{definition.label} 必须为数字") from exc
        if definition.kind == "integer" and (isinstance(raw, float) and raw != value or isinstance(raw, str) and str(value) != raw.strip()):
            raise ValueError(f"{definition.label} 必须为整数")
        if not definition.minimum <= value <= definition.maximum:
            raise ValueError(f"{definition.label} 范围为 {definition.minimum} 到 {definition.maximum}")
        result[name] = value
    if key == "ma_cross" and result["fast"] >= result["slow"]:
        raise ValueError("短均线必须小于长均线")
    if key == "turtle" and result["exit"] >= result["entry"]:
        raise ValueError("离场周期必须小于入场周期")
    return module, result


def signals(key: str, bars: pd.DataFrame, supplied: dict[str, Any] | None = None) -> tuple[pd.DataFrame, dict[str, int | float]]:
    module, params = validate_params(key, supplied)
    required = {"date", "open", "high", "low", "close"}
    if not required.issubset(bars.columns):
        raise ValueError(f"行情缺少字段: {', '.join(sorted(required - set(bars.columns)))}")
    if len(bars) < module.minimum_bars(params):
        raise ValueError(f"{module.name} 至少需要 {module.minimum_bars(params)} 根日线，当前只有 {len(bars)} 根")
    clean = bars.sort_values("date").reset_index(drop=True)
    target = module.calculate(clean, params)
    return pd.DataFrame({"date": clean["date"].astype(str), "target": target.astype(bool)}), params
