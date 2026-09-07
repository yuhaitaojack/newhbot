from __future__ import annotations

import asyncio
import os
from collections import deque
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.exchange_models import InstrumentMeta
from app.mapping import map_market_event_kind
from app.readonly_guard import FORBIDDEN_CONNECTOR_METHODS, ReadOnlyGuard, ReadOnlyViolation

# Credential env / Docker secret names. Values must never be logged or committed.
_ADDRESS_ENV = "HYPERLIQUID_PERPETUAL_ADDRESS"
_SECRET_ENV = "HYPERLIQUID_PERPETUAL_SECRET_KEY"
_ADDRESS_FILE_ENV = "HYPERLIQUID_PERPETUAL_ADDRESS_FILE"
_SECRET_FILE_ENV = "HYPERLIQUID_PERPETUAL_SECRET_KEY_FILE"
_DOCKER_ADDRESS_SECRET = Path("/run/secrets/hyperliquid_perpetual_address")
_DOCKER_SECRET_SECRET = Path("/run/secrets/hyperliquid_perpetual_secret_key")
_CREDENTIAL_ENV_KEYS = frozenset(
    {_ADDRESS_ENV, _SECRET_ENV, _ADDRESS_FILE_ENV, _SECRET_FILE_ENV}
)

SYNC_WRITE_METHODS = frozenset(
    {"buy", "sell", "cancel", "place_order", "updateLeverage", "set_leverage"}
)
ASYNC_WRITE_METHODS = frozenset(
    {
        "_place_order",
        "_place_cancel",
        "_execute_order_cancel",
        "_execute_order_cancel_and_process_update",
        "_set_trading_pair_leverage",
    }
)

MARKET_EVENT_NAMES = (
    "OrderFilled",
    "OrderCancelled",
    "OrderFailure",
    "OrderUpdate",
    "TradeUpdate",
    "BuyOrderCompleted",
    "SellOrderCompleted",
)


def try_load_hummingbot_connector_class():
    """Import HyperliquidPerpetualDerivative from Hummingbot v2.16.0. None if absent."""
    try:
        from hummingbot.connector.derivative.hyperliquid_perpetual.hyperliquid_perpetual_derivative import (
            HyperliquidPerpetualDerivative,
        )

        return HyperliquidPerpetualDerivative
    except Exception:
        return None


def _read_secret_file(path: Path | str | None) -> str | None:
    if path is None:
        return None
    candidate = Path(path)
    if not candidate.is_file():
        return None
    text = candidate.read_text(encoding="utf-8").strip()
    return text or None


def _apply_untracked_env() -> None:
    """Load credential keys from a local untracked .env if present. Never logs values."""
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / ".env",
        here.parents[1] / ".env",
        Path("/app/.env"),
    ]
    for env_path in candidates:
        if not env_path.is_file():
            continue
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key not in _CREDENTIAL_ENV_KEYS or key in os.environ:
                continue
            value = value.strip().strip('"').strip("'")
            if value:
                os.environ[key] = value


def load_account_credentials() -> tuple[str, str] | None:
    """Return (secret_key, address) or None. Never log the values."""
    _apply_untracked_env()
    secret = (
        os.environ.get(_SECRET_ENV, "").strip()
        or _read_secret_file(os.environ.get(_SECRET_FILE_ENV))
        or _read_secret_file(_DOCKER_SECRET_SECRET)
    )
    address = (
        os.environ.get(_ADDRESS_ENV, "").strip()
        or _read_secret_file(os.environ.get(_ADDRESS_FILE_ENV))
        or _read_secret_file(_DOCKER_ADDRESS_SECRET)
    )
    if secret and address:
        return secret, address
    return None


def credentials_supplied() -> bool:
    return load_account_credentials() is not None


def instantiate_readonly(
    cls: type, trading_pairs: list[str], *, domain: str = "hyperliquid_perpetual_testnet"
) -> Any:
    """Instantiate with v2.16.0 trading_required=False. No secret key, no address.

    Source (v2.16.0 HyperliquidPerpetualDerivative): authenticator is None when
    _trading_required is False. start_network then skips user stream, status
    polling, and builder-fee init.
    """
    return cls(
        trading_required=False,
        trading_pairs=list(trading_pairs),
        hyperliquid_perpetual_secret_key=None,
        hyperliquid_perpetual_address=None,
        domain=domain,
    )


def instantiate_authenticated(
    cls: type,
    trading_pairs: list[str],
    *,
    secret_key: str,
    address: str,
    domain: str = "hyperliquid_perpetual_testnet",
) -> Any:
    """Instantiate with trading_required=True for account-level reads.

    Caller must disable lost-order auto-cancel before start_network. See
    disable_exchange_write_loops. Never log secret_key or address.
    """
    if not secret_key or not address:
        raise RuntimeError("authenticated instantiate requires credential")
    return cls(
        trading_required=True,
        trading_pairs=list(trading_pairs),
        hyperliquid_perpetual_secret_key=secret_key,
        hyperliquid_perpetual_address=address,
        domain=domain,
    )


def wrap_readonly(connector: Any) -> ReadOnlyGuard:
    return connector if isinstance(connector, ReadOnlyGuard) else ReadOnlyGuard(connector)


def _unglazed(connector: Any) -> Any:
    if isinstance(connector, ReadOnlyGuard):
        return object.__getattribute__(connector, "_inner")
    return connector


SAVED_PLACE_ORDER_ATTR = "_newhbot_original_place_order"
SAVED_PLACE_CANCEL_ATTR = "_newhbot_original_place_cancel"
SAVED_SET_LEVERAGE_ATTR = "_newhbot_original_set_leverage"


def disable_exchange_write_loops(connector: Any) -> Any:
    """Neutralize Hummingbot write entry points on the raw connector instance.

    v2.16.0 ExchangePyBase.start_network(trading_required=True) starts
    `_lost_orders_update_polling_loop`, which calls `_cancel_lost_orders` →
    `_execute_order_cancel` on `self` (the unwrapped instance). ReadOnlyGuard
    cannot see those internal calls. This patch is the required safety stop:
    lost-order auto-cancel becomes a no-op; buy/sell/cancel/leverage still raise.

    `_place_order` on the raw instance is also patched to raise so Hummingbot
    internals cannot place. The original coroutine is saved on
    `_newhbot_original_place_order` for the armed Bridge.place path only.
    """
    inner = _unglazed(connector)
    if getattr(inner, "_newhbot_write_loops_disabled", False):
        return inner

    original_place = getattr(inner, "_place_order", None)
    if callable(original_place) and getattr(inner, SAVED_PLACE_ORDER_ATTR, None) is None:
        setattr(inner, SAVED_PLACE_ORDER_ATTR, original_place)
    original_cancel = getattr(inner, "_place_cancel", None)
    if callable(original_cancel) and getattr(inner, SAVED_PLACE_CANCEL_ATTR, None) is None:
        setattr(inner, SAVED_PLACE_CANCEL_ATTR, original_cancel)
    original_leverage = getattr(inner, "_set_trading_pair_leverage", None)
    if callable(original_leverage) and getattr(inner, SAVED_SET_LEVERAGE_ATTR, None) is None:
        setattr(inner, SAVED_SET_LEVERAGE_ATTR, original_leverage)

    async def _noop_cancel_lost(*_args: Any, **_kwargs: Any) -> None:
        return None

    def _sync_block(name: str):
        def blocked(*_args: Any, **_kwargs: Any) -> None:
            raise ReadOnlyViolation(f"read-only forbids inner {name}")

        return blocked

    def _async_block(name: str):
        async def blocked(*_args: Any, **_kwargs: Any) -> None:
            raise ReadOnlyViolation(f"read-only forbids inner {name}")

        return blocked

    inner._cancel_lost_orders = _noop_cancel_lost
    for name in SYNC_WRITE_METHODS:
        setattr(inner, name, _sync_block(name))
    for name in ASYNC_WRITE_METHODS:
        setattr(inner, name, _async_block(name))
    for name in FORBIDDEN_CONNECTOR_METHODS:
        if name in ASYNC_WRITE_METHODS or name in SYNC_WRITE_METHODS:
            continue
        setattr(inner, name, _sync_block(name))
    inner._newhbot_write_loops_disabled = True
    return inner


def _account_from_connector(inner: Any) -> dict | None:
    """Map ConnectorBase _account_balances after official `_update_balances`.

    v2.16.0 HyperliquidPerpetualDerivative._update_balances writes
    CONSTANTS.CURRENCY ("USD") from clearinghouseState accountValue / withdrawable
    (or spot balances when abstraction mode requires it). Missing keys must not
    become a fake 0.
    """
    balances = getattr(inner, "_account_balances", None)
    available_map = getattr(inner, "_account_available_balances", None)
    if balances is None or available_map is None:
        return None
    quote = None
    try:
        for candidate in ("USD", "USDC"):
            if candidate in balances and candidate in available_map:
                quote = candidate
                break
    except TypeError:
        return None
    if quote is None:
        return None
    equity = Decimal(str(balances[quote]))
    available = Decimal(str(available_map[quote]))
    margin = equity - available
    if margin < 0:
        margin = Decimal("0")
    return {
        "equity": str(equity),
        "available": str(available),
        "margin_used": str(margin),
        "quote": quote,
    }


def _asset_from_hb_position(pos: Any) -> dict:
    side = str(getattr(pos, "position_side", "")).upper()
    amount = Decimal(str(getattr(pos, "amount", "0")))
    if "SHORT" in side:
        szi = -abs(amount)
    else:
        szi = abs(amount)
    pair = str(getattr(pos, "trading_pair", "") or "")
    coin = pair.replace("-USD", "") if pair else ""
    leverage = getattr(pos, "leverage", None)
    return {
        "type": "oneWay",
        "position": {
            "coin": coin,
            "szi": str(szi),
            "entryPx": str(getattr(pos, "entry_price", "0")),
            "unrealizedPnl": str(getattr(pos, "unrealized_pnl", "0")),
            "leverage": {"value": str(int(Decimal(str(leverage)))) if leverage is not None else "0"},
        },
    }


def _raw_from_inflight(order: Any) -> dict:
    state = "open"
    if getattr(order, "is_failure", False):
        state = "failed"
    elif getattr(order, "is_cancelled", False):
        state = "canceled"
    elif getattr(order, "is_filled", False):
        state = "filled"
    elif getattr(order, "is_open", False):
        state = "open"
    trade_type = str(getattr(order, "trade_type", "BUY")).upper()
    side = "BUY" if "BUY" in trade_type else "SELL"
    amount = Decimal(str(getattr(order, "amount", "0")))
    filled = Decimal(str(getattr(order, "executed_amount_base", "0") or "0"))
    remaining = amount - filled
    position = str(getattr(order, "position", ""))
    return {
        "status": state,
        "cloid": getattr(order, "client_order_id", ""),
        "oid": getattr(order, "exchange_order_id", None),
        "coin": getattr(order, "base_asset", None) or str(getattr(order, "trading_pair", "")).replace("-USD", ""),
        "symbol": getattr(order, "trading_pair", ""),
        "side": side,
        "sz": str(remaining if remaining > 0 else 0),
        "origSz": str(amount),
        "limitPx": str(getattr(order, "price", "0") or "0"),
        "reduceOnly": "CLOSE" in position.upper(),
    }


def _fill_from_hb(item: Any) -> dict:
    if isinstance(item, dict):
        return item
    fee_obj = getattr(item, "fee", None)
    fee = "0"
    if fee_obj is not None:
        flat = getattr(fee_obj, "flat_fees", None)
        if flat:
            fee = str(getattr(flat[0], "amount", "0"))
        elif getattr(fee_obj, "percent", None) is not None:
            fee = str(fee_obj.percent)
    pair = str(getattr(item, "trading_pair", "") or "")
    return {
        "tid": str(getattr(item, "trade_id", None) or getattr(item, "fill_id", "0")),
        "oid": getattr(item, "exchange_order_id", None),
        "cloid": getattr(item, "client_order_id", "") or "",
        "coin": pair.replace("-USD", ""),
        "symbol": pair,
        "side": str(getattr(item, "trade_type", getattr(item, "side", ""))),
        "px": str(getattr(item, "fill_price", getattr(item, "price", "0"))),
        "sz": str(getattr(item, "fill_base_amount", getattr(item, "amount", "0"))),
        "fee": fee,
        "hash": getattr(item, "exchange_trade_id", None),
    }


class _ArmedPlaceTarget:
    """Shim for place_with_injected_cloid: tracking + original _place_order only."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw
        original = getattr(raw, SAVED_PLACE_ORDER_ATTR, None)
        if not callable(original):
            raise ReadOnlyViolation("armed place requires saved original _place_order")
        self._place_order = original
        start_tracking = getattr(raw, "start_tracking_order", None)
        if callable(start_tracking):
            self.start_tracking_order = start_tracking
        self.in_flight_orders = getattr(raw, "in_flight_orders", {})

    def record_submission(self, cloid: str, exchange_order_id: str, timestamp: float | None) -> None:
        tracker = getattr(self._raw, "_order_tracker", None)
        if tracker is None or not callable(getattr(tracker, "process_order_update", None)):
            return
        from hummingbot.core.data_type.in_flight_order import OrderState, OrderUpdate

        order = self.in_flight_orders.get(cloid) if hasattr(self.in_flight_orders, "get") else None
        if order is None:
            raise ReadOnlyViolation("armed place lost its tracked order")
        update_timestamp = timestamp if timestamp is not None else self._raw.current_timestamp
        tracker.process_order_update(
            OrderUpdate(
                client_order_id=cloid,
                exchange_order_id=str(exchange_order_id),
                trading_pair=order.trading_pair,
                update_timestamp=update_timestamp,
                new_state=OrderState.OPEN,
            )
        )

    def record_failure(self, cloid: str, trading_pair: str, error: Exception) -> None:
        tracker = getattr(self._raw, "_order_tracker", None)
        if tracker is None or not callable(getattr(tracker, "process_order_update", None)):
            return
        from hummingbot.core.data_type.in_flight_order import OrderState, OrderUpdate

        tracker.process_order_update(
            OrderUpdate(
                client_order_id=cloid,
                trading_pair=trading_pair,
                update_timestamp=self._raw.current_timestamp,
                new_state=OrderState.FAILED,
                misc_updates={"error_message": str(error), "error_type": type(error).__name__},
            )
        )

    def buy(self, *args: Any, **kwargs: Any) -> None:
        raise ReadOnlyViolation("armed path forbids buy()")

    def sell(self, *args: Any, **kwargs: Any) -> None:
        raise ReadOnlyViolation("armed path forbids sell()")


class ReadOnlyHummingbotBridge:
    """Production Hyperliquid seam: real Connector + ReadOnlyGuard.

    Default: place/cancel/leverage never reach the inner connector.
    Armed (execution_enabled=True): Bridge.place and Bridge.cancel may call the
    saved original connector internals with the business cloid. buy()/sell(),
    public cancel(), leverage, and lost-order auto-cancel stay forbidden. Raw
    `_place_order`/`_place_cancel` stay patched.
    """

    read_only = True
    place_calls = 0

    def __init__(
        self,
        connector: Any,
        *,
        authenticated: bool = False,
        execution_enabled: bool = False,
    ) -> None:
        raw = _unglazed(connector)
        disable_exchange_write_loops(raw)
        self.connector = wrap_readonly(raw)
        self.authenticated = authenticated
        self.execution_enabled = bool(execution_enabled)
        self.has_user_stream = authenticated
        self.ws_connected = False
        self.account_read = "authenticated" if authenticated else "skipped_no_user_address"
        self._events: deque[dict] = deque(maxlen=64)
        self._subscribed = False
        self._forwarders: list[Any] = []
        self.write_loops_disabled = bool(getattr(raw, "_newhbot_write_loops_disabled", False))

    def _inner(self) -> Any:
        return _unglazed(self.connector)

    def _subscribe_events(self) -> None:
        if self._subscribed:
            return
        add_listener = getattr(self.connector, "add_listener", None)
        if not callable(add_listener):
            return
        try:
            from hummingbot.core.event.event_forwarder import EventForwarder
            from hummingbot.core.event.events import MarketEvent
        except Exception:
            return
        for name in MARKET_EVENT_NAMES:
            event = getattr(MarketEvent, name, None)
            if event is None:
                continue
            forwarder = EventForwarder(self._on_market_event)
            self._forwarders.append(forwarder)
            add_listener(event, forwarder)
        self._subscribed = True

    def _on_market_event(self, *args: Any) -> None:
        event = args[-1] if args else None
        name = type(event).__name__ if event is not None else "unknown"
        self._events.append(
            {
                "type": map_market_event_kind(name),
                "event_name": name,
                "hb_failure_is_not_safe_to_open": name in {"OrderFailure", "MarketOrderFailureEvent"}
                or "Failure" in name,
            }
        )

    async def start_network(self) -> None:
        inner = self._inner()
        if self.authenticated:
            disable_exchange_write_loops(inner)
        inner_start = getattr(self.connector, "start_network", None)
        timeout = 45 if self.authenticated else 30
        if callable(inner_start):
            await asyncio.wait_for(inner_start(), timeout=timeout)
        self.ws_connected = True
        self._subscribe_events()
        if self.authenticated:
            await self._refresh_account_reads()
        inner = self._inner()
        listener = getattr(inner, "_user_stream_event_listener_task", None)
        self.has_user_stream = bool(self.authenticated and listener is not None)

    async def _refresh_account_reads(self) -> None:
        inner = self._inner()
        update_positions = getattr(inner, "_update_positions", None)
        if not callable(update_positions):
            self.account_read = "position_query_unavailable"
            return
        try:
            await asyncio.wait_for(update_positions(), timeout=20)
        except Exception:
            self.account_read = "position_query_failed"
            return
        update_balances = getattr(inner, "_update_balances", None)
        if not callable(update_balances):
            self.account_read = "balance_query_unavailable"
            return
        try:
            await asyncio.wait_for(update_balances(), timeout=20)
        except Exception:
            self.account_read = "balance_query_failed"
            return
        if _account_from_connector(inner) is None:
            self.account_read = "balance_query_failed"
            return
        self.account_read = "authenticated"

    async def stop_network(self) -> None:
        inner_stop = getattr(self.connector, "stop_network", None)
        if callable(inner_stop):
            await asyncio.wait_for(inner_stop(), timeout=15)
        self.ws_connected = False

    def trading_rule(self, trading_pair: str) -> InstrumentMeta:
        rules = getattr(self.connector, "trading_rules", None) or {}
        rule = rules.get(trading_pair)
        if rule is None:
            raise LookupError(f"no connector trading_rules for {trading_pair}")
        step = Decimal(str(rule.min_base_amount_increment))
        exp = abs(step.as_tuple().exponent)
        return InstrumentMeta(
            symbol=trading_pair,
            sz_decimals=exp,
            step_size=step,
            tick_size=Decimal(str(rule.min_price_increment)),
            min_order_size=Decimal(str(rule.min_order_size)),
            min_notional=Decimal(str(rule.min_notional_size)),
        )

    def quantize_order_price(self, trading_pair: str, price: Decimal) -> Decimal:
        return self.connector.quantize_order_price(trading_pair, Decimal(str(price)))

    def quantize_order_amount(self, trading_pair: str, amount: Decimal) -> Decimal:
        return self.connector.quantize_order_amount(trading_pair, Decimal(str(amount)))

    async def rest_snapshot(self) -> dict:
        if self.authenticated:
            await self._refresh_account_reads()
        positions = getattr(self.connector, "account_positions", None) or {}
        if hasattr(positions, "values"):
            pos_rows = [_asset_from_hb_position(item) for item in positions.values()]
        else:
            pos_rows = [_asset_from_hb_position(item) for item in list(positions)]
        orders = getattr(self.connector, "in_flight_orders", None) or {}
        if hasattr(orders, "values"):
            order_rows = [_raw_from_inflight(item) for item in orders.values()]
        else:
            order_rows = []
        mid = "0"
        get_price = getattr(self.connector, "get_price", None)
        if callable(get_price):
            try:
                pair = next(iter(getattr(self.connector, "_trading_pairs", []) or ["BTC-USD"]))
                mid = str(get_price(pair, False))
            except Exception:
                mid = "0"
        fills = await self.get_fills()
        account = _account_from_connector(self._inner()) if self.account_read == "authenticated" else None
        return {
            "assetPositions": pos_rows,
            "openOrders": order_rows,
            "fills": fills,
            "account": account or {},
            "mid": mid,
            "account_read": self.account_read,
        }

    async def place(self, wire: dict) -> dict:
        self.place_calls += 1
        if not self.execution_enabled:
            raise ReadOnlyViolation("read-only forbids place")
        cloid = str((wire or {}).get("cloid") or "")
        if not cloid.startswith("0x"):
            raise ValueError("armed place requires business cloid")
        from app.hummingbot_place import place_with_injected_cloid

        return await place_with_injected_cloid(_ArmedPlaceTarget(self._inner()), wire)

    async def cancel(self, cloid: str) -> dict:
        if not self.execution_enabled or not self.authenticated:
            raise ReadOnlyViolation("read-only forbids cancel")
        business_cloid = str(cloid or "")
        if not business_cloid.startswith("0x"):
            raise ValueError("armed cancel requires business cloid")
        inner = self._inner()
        original_cancel = getattr(inner, SAVED_PLACE_CANCEL_ATTR, None)
        if not callable(original_cancel):
            raise ReadOnlyViolation("armed cancel requires saved original _place_cancel")
        orders = getattr(inner, "in_flight_orders", None) or {}
        tracked = orders.get(business_cloid) if hasattr(orders, "get") else None
        if tracked is None and hasattr(orders, "values"):
            tracked = next(
                (
                    item
                    for item in orders.values()
                    if str(getattr(item, "client_order_id", "")) == business_cloid
                ),
                None,
            )
        if tracked is None:
            return {"ok": False, "cloid": business_cloid}
        result = await original_cancel(business_cloid, tracked)
        return {"ok": bool(result), "cloid": business_cloid, "order": _raw_from_inflight(tracked)}

    async def get_order(self, cloid: str) -> dict | None:
        orders = getattr(self.connector, "in_flight_orders", None) or {}
        item = orders.get(cloid) if hasattr(orders, "get") else None
        if item is None:
            return None
        return _raw_from_inflight(item)

    async def get_fills(self) -> list[dict]:
        inner = self._inner()
        rows: list[dict] = []
        seen: set[tuple[str, str]] = set()

        def append_fill(item: Any) -> None:
            row = _fill_from_hb(item)
            key = (str(row.get("cloid") or ""), str(row.get("tid") or ""))
            if key in seen:
                return
            seen.add(key)
            rows.append(row)

        # Hyperliquid keeps fills for currently tracked orders on the order
        # object. _current_trade_fills is only the recovery set for orders no
        # longer tracked, so reading that set alone misses normal IOC fills.
        tracker = getattr(inner, "_order_tracker", None)
        tracked_orders = getattr(tracker, "all_fillable_orders", None) if tracker is not None else None
        if tracked_orders:
            iterable = tracked_orders.values() if hasattr(tracked_orders, "values") else tracked_orders
            for order in iterable:
                fills = getattr(order, "order_fills", None) or {}
                fill_iterable = fills.values() if hasattr(fills, "values") else fills
                for item in fill_iterable:
                    append_fill(item)

        recovery_fills = getattr(inner, "_current_trade_fills", None)
        if recovery_fills:
            iterable = recovery_fills.values() if hasattr(recovery_fills, "values") else recovery_fills
            for item in iterable:
                append_fill(item)
        return rows

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        if not self.execution_enabled or not self.authenticated:
            raise ReadOnlyViolation("read-only forbids set_leverage")
        if not symbol or int(leverage) <= 0:
            raise ValueError("armed leverage requires a positive value and symbol")
        original_leverage = getattr(self._inner(), SAVED_SET_LEVERAGE_ATTR, None)
        if not callable(original_leverage):
            raise ReadOnlyViolation("armed leverage requires saved original _set_trading_pair_leverage")
        success, message = await original_leverage(str(symbol), int(leverage))
        if not success:
            raise RuntimeError(message or "Hyperliquid leverage update failed")

    def recent_events(self) -> list[dict]:
        return list(self._events)
