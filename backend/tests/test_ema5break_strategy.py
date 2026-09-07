from __future__ import annotations

import importlib.util
from pathlib import Path

STRATEGY = Path(__file__).resolve().parents[2] / "strategies" / "ema5break" / "strategy.py"


def _load():
    spec = importlib.util.spec_from_file_location("ema5break", STRATEGY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _bar(o, h, l, c) -> dict:
    return {"open": o, "high": h, "low": l, "close": c}


def test_ema5break_hold_without_enough_bars() -> None:
    mod = _load()
    assert mod.on_bar({"bars": [_bar(1, 2, 0.5, 1.5)], "position_side": "FLAT"}) == "HOLD"


def test_ema5break_long_on_bullish_engulfing_above_ema() -> None:
    mod = _load()
    # Warmup closes around 100 so EMA5 is near 100; last two bars engulf up and close above EMA.
    bars = [_bar(100, 101, 99, 100) for _ in range(16)]
    bars[-2] = _bar(100.5, 100.6, 98.0, 98.2)
    bars[-1] = _bar(98.0, 103.0, 97.8, 102.5)
    assert mod.on_bar({"bars": bars, "position_side": "FLAT"}) == "LONG"


def test_ema5break_short_on_bearish_engulfing_below_ema() -> None:
    mod = _load()
    bars = [_bar(100, 101, 99, 100) for _ in range(16)]
    bars[-2] = _bar(99.5, 102.0, 99.4, 101.8)
    bars[-1] = _bar(102.0, 102.2, 97.0, 97.5)
    assert mod.on_bar({"bars": bars, "position_side": "FLAT"}) == "SHORT"


def test_ema5break_does_not_reverse_from_long() -> None:
    mod = _load()
    bars = [_bar(100, 101, 99, 100) for _ in range(16)]
    bars[-2] = _bar(99.5, 102.0, 99.4, 101.8)
    bars[-1] = _bar(102.0, 102.2, 97.0, 97.5)
    assert mod.on_bar({"bars": bars, "position_side": "LONG", "entry_price": 100}) == "HOLD"


def test_ema5break_close_on_atr_stop() -> None:
    mod = _load()
    bars = [_bar(100, 101, 99, 100) for _ in range(16)]
    bars[-1] = _bar(90, 91, 80, 81)
    out = mod.on_bar({"bars": bars, "position_side": "LONG", "entry_price": 100})
    assert out == "CLOSE"
