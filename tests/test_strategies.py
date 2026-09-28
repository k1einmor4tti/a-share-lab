from __future__ import annotations

import pandas as pd
import pytest

from app.strategies import MODULES, module_schemas, signals, validate_params


def sample_bars(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=len(closes)).strftime("%Y-%m-%d"),
        "open": closes, "high": [x + .1 for x in closes],
        "low": [x - .1 for x in closes], "close": closes,
    })


def test_five_modules_are_selectable_and_do_not_look_ahead():
    bars = sample_bars([10, 9, 8, 7, 6, 7, 8, 9, 10, 11, 10, 9, 8, 7, 6, 5, 6, 7, 8, 9])
    choices = {
        "buy_hold": {}, "ma_cross": {"fast": 2, "slow": 4},
        "turtle": {"entry": 4, "exit": 2},
        "rsi": {"period": 3, "oversold": 30, "overbought": 70},
        "bollinger": {"window": 3, "width": 1},
    }
    assert {item["key"] for item in module_schemas()} == set(choices)
    for key, params in choices.items():
        full, resolved = signals(key, bars, params)
        changed = bars.copy()
        changed.loc[15:, "close"] = 1000
        before_future, _ = signals(key, changed.iloc[:15], params)
        assert full["target"].iloc[:15].tolist() == before_future["target"].tolist()
        assert len(full) == len(bars)
        assert set(resolved) == set(MODULES[key].parameters)


def test_turtle_breakout_uses_prior_session_levels():
    bars = sample_bars([10, 10, 10, 12, 13, 9, 8])
    target, _ = signals("turtle", bars, {"entry": 3, "exit": 2})
    assert target["target"].tolist() == [False, False, False, True, True, False, False]


def test_parameter_bounds_and_history_are_explicit():
    with pytest.raises(ValueError, match="短均线必须小于长均线"):
        validate_params("ma_cross", {"fast": 80, "slow": 20})
    with pytest.raises(ValueError, match="至少需要 61 根日线"):
        signals("ma_cross", sample_bars([10.0] * 10))
    with pytest.raises(ValueError, match="必须为整数"):
        validate_params("rsi", {"period": 3.5})
