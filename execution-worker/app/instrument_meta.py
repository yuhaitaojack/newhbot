from __future__ import annotations

import json
import urllib.error
import urllib.request
from decimal import Decimal

from app.config import MIN_NOTIONAL_SIZE
from app.exchange_models import InstrumentMeta

PUBLIC_INFO_URL = "https://api.hyperliquid.xyz/info"


def tick_from_mark_px(mark_px: str) -> Decimal:
    """Match v2.16.0 `_format_trading_rules`: 10 ** -len(markPx.split('.')[1])."""
    if "." not in mark_px:
        raise ValueError("markPx has no decimal point; Hummingbot v2.16.0 would also fail here")
    return Decimal(str(10 ** -len(mark_px.split(".")[1])))


def step_from_sz_decimals(sz_decimals: int) -> Decimal:
    """Match v2.16.0: step_size = 10 ** -szDecimals; min_order_size = step_size."""
    return Decimal(str(10 ** -int(sz_decimals)))


def parse_instrument_meta(universe_entry: dict, price_info: dict, *, quote: str = "USD") -> InstrumentMeta:
    name = str(universe_entry["name"])
    sz_decimals = int(universe_entry["szDecimals"])
    step = step_from_sz_decimals(sz_decimals)
    mark = str(price_info.get("markPx"))
    tick = tick_from_mark_px(mark)
    return InstrumentMeta(
        symbol=f"{name}-{quote}",
        sz_decimals=sz_decimals,
        step_size=step,
        tick_size=tick,
        min_order_size=step,
        min_notional=MIN_NOTIONAL_SIZE,
    )


def extract_coin_meta(exchange_info: list, coin: str, *, quote: str = "USD") -> InstrumentMeta:
    universe = exchange_info[0]["universe"]
    ctxs = exchange_info[1]
    for entry, ctx in zip(universe, ctxs):
        if entry.get("name") == coin:
            return parse_instrument_meta(entry, ctx, quote=quote)
    raise KeyError(f"{coin} not in metaAndAssetCtxs universe")


def fetch_public_meta_and_asset_ctxs(*, timeout: float = 20.0) -> list:
    req = urllib.request.Request(
        PUBLIC_INFO_URL,
        data=json.dumps({"type": "metaAndAssetCtxs"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"public metaAndAssetCtxs failed: {exc}") from exc


def fetch_public_instrument(trading_pair: str, *, timeout: float = 20.0) -> InstrumentMeta:
    coin, _, quote = trading_pair.partition("-")
    info = fetch_public_meta_and_asset_ctxs(timeout=timeout)
    return extract_coin_meta(info, coin, quote=quote or "USD")


def default_btc_instrument_meta() -> InstrumentMeta:
    """BTC defaults after PHASE 4 public snapshot (szDecimals=5, tick from markPx).

    Tick is not a Hyperliquid constant; it is derived from current markPx decimals.
    This snapshot matched Hummingbot v2.16.0 TradingRule for BTC-USD on 2026-09-01.
    """
    return InstrumentMeta(
        symbol="BTC-USD",
        sz_decimals=5,
        step_size=Decimal("0.00001"),
        tick_size=Decimal("0.1"),
        min_order_size=Decimal("0.00001"),
        min_notional=MIN_NOTIONAL_SIZE,
        max_leverage=50,
    )
