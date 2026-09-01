from __future__ import annotations

from enum import StrEnum


class SignalType(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    CLOSE = "CLOSE"
    HOLD = "HOLD"


class PositionSide(StrEnum):
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"
    UNKNOWN = "UNKNOWN"


class OrderStatus(StrEnum):
    """Local order lifecycle. UNKNOWN is not a pre-send state.

    PENDING_SUBMISSION: intent persisted; place_order has not been attempted.
    SUBMITTING: place_order is in flight.
    ACK/OPEN/PARTIAL/FILLED/REJECTED/CANCELED: exchange (or mock) result confirmed.
    UNKNOWN: execution was attempted and the final result cannot be confirmed.
    """

    PENDING_SUBMISSION = "PENDING_SUBMISSION"
    SUBMITTING = "SUBMITTING"
    ACK = "ACK"
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELED = "CANCELED"
    UNKNOWN = "UNKNOWN"


# Crash/timeout/pre-ack: must not auto-resubmit. PENDING is pre-send but still blocks.
UNRESOLVED_ORDER_STATUSES = frozenset(
    {OrderStatus.PENDING_SUBMISSION, OrderStatus.SUBMITTING, OrderStatus.UNKNOWN}
)

# At most one inflight opening order per symbol (DB partial unique index).
INFLIGHT_OPEN_STATUSES = frozenset(
    {
        OrderStatus.PENDING_SUBMISSION,
        OrderStatus.SUBMITTING,
        OrderStatus.ACK,
        OrderStatus.OPEN,
        OrderStatus.PARTIAL,
        OrderStatus.UNKNOWN,
    }
)

CONFIRMED_LIVE_STATUSES = frozenset(
    {OrderStatus.ACK, OrderStatus.OPEN, OrderStatus.PARTIAL, OrderStatus.FILLED}
)


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class SystemState(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    CONNECTING = "CONNECTING"
    SYNCING = "SYNCING"
    RECONCILING = "RECONCILING"
    RECOVERY = "RECOVERY"
    READY = "READY"
    RUNNING = "RUNNING"
    ERROR = "ERROR"


# Local SQLite is never the source of truth for live positions.
EXCHANGE_STATE_OUTRANKS_LOCAL_DB = True
