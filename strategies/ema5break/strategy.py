"""ema5break — BTC perp signal strategy. Never places orders.

Outputs only LONG / SHORT / CLOSE / HOLD.

Rules (5m bars, one position):
- LONG: bullish engulfing and close > EMA5
- SHORT: bearish engulfing and close < EMA5
- Stop = 2 * ATR; take-profit = 1.5 * stop distance (3 * ATR from entry)
- Never reverse; CLOSE then wait for a later independent signal
- Leverage is a settings concern; this module never calls set_leverage
"""

from __future__ import annotations

ALLOWED = frozenset({"LONG", "SHORT", "CLOSE", "HOLD"})


def _params(snapshot: dict) -> dict:
    raw = snapshot.get("parameters") or {}
    return {
        "ema_period": int(raw.get("ema_period", 5)),
        "atr_period": int(raw.get("atr_period", 14)),
        "atr_stop_mult": float(raw.get("atr_stop_mult", 2.0)),
        "tp_rr": float(raw.get("tp_rr", 1.5)),
        "interval": str(raw.get("interval", snapshot.get("interval", "5m"))),
        "symbol": str(raw.get("symbol", snapshot.get("symbol", "BTC-USD"))),
    }


def _bars(snapshot: dict) -> list[dict]:
    rows = snapshot.get("bars") or snapshot.get("candles") or []
    out: list[dict] = []
    for item in rows:
        out.append(
            {
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
            }
        )
    return out


def _ema(closes: list[float], period: int) -> float | None:
    if period < 1 or len(closes) < period:
        return None
    k = 2.0 / (period + 1)
    value = sum(closes[:period]) / period
    for price in closes[period:]:
        value = price * k + value * (1.0 - k)
    return value


def _true_range(prev_close: float, bar: dict) -> float:
    return max(bar["high"] - bar["low"], abs(bar["high"] - prev_close), abs(bar["low"] - prev_close))


def _atr(bars: list[dict], period: int) -> float | None:
    if period < 1 or len(bars) < period + 1:
        return None
    trs = [_true_range(bars[i - 1]["close"], bars[i]) for i in range(1, len(bars))]
    window = trs[-period:]
    if len(window) < period:
        return None
    return sum(window) / period


def _body(bar: dict) -> tuple[float, float]:
    return (max(bar["open"], bar["close"]), min(bar["open"], bar["close"]))


def _is_bull(bar: dict) -> bool:
    return bar["close"] > bar["open"]


def _is_bear(bar: dict) -> bool:
    return bar["close"] < bar["open"]


def _bullish_engulfing(prev: dict, curr: dict) -> bool:
    if not (_is_bear(prev) and _is_bull(curr)):
        return False
    prev_hi, prev_lo = _body(prev)
    curr_hi, curr_lo = _body(curr)
    return curr_lo <= prev_lo and curr_hi >= prev_hi


def _bearish_engulfing(prev: dict, curr: dict) -> bool:
    if not (_is_bull(prev) and _is_bear(curr)):
        return False
    prev_hi, prev_lo = _body(prev)
    curr_hi, curr_lo = _body(curr)
    return curr_lo <= prev_lo and curr_hi >= prev_hi


def on_bar(snapshot: dict) -> str:
    """Pure signal. Never talks to exchange, Worker, or SQLite."""
    params = _params(snapshot)
    bars = _bars(snapshot)
    if len(bars) < 2:
        return "HOLD"
    ema = _ema([bar["close"] for bar in bars], params["ema_period"])
    atr = _atr(bars, params["atr_period"])
    if ema is None or atr is None or atr <= 0:
        return "HOLD"
    prev, curr = bars[-2], bars[-1]
    side = str(snapshot.get("position_side") or "FLAT").upper()
    entry = snapshot.get("entry_price")
    stop_dist = params["atr_stop_mult"] * atr
    tp_dist = params["tp_rr"] * stop_dist

    if side == "LONG":
        if entry is None:
            return "HOLD"
        entry_px = float(entry)
        if curr["close"] <= entry_px - stop_dist:
            return "CLOSE"
        if curr["close"] >= entry_px + tp_dist:
            return "CLOSE"
        return "HOLD"

    if side == "SHORT":
        if entry is None:
            return "HOLD"
        entry_px = float(entry)
        if curr["close"] >= entry_px + stop_dist:
            return "CLOSE"
        if curr["close"] <= entry_px - tp_dist:
            return "CLOSE"
        return "HOLD"

    # FLAT: at most one new open; never reverse from here.
    want_long = _bullish_engulfing(prev, curr) and curr["close"] > ema
    want_short = _bearish_engulfing(prev, curr) and curr["close"] < ema
    if want_long and not want_short:
        return "LONG"
    if want_short and not want_long:
        return "SHORT"
    return "HOLD"
