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
    PENDING_SUBMISSION = "PENDING_SUBMISSION"
    UNKNOWN = "UNKNOWN"
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELED = "CANCELED"


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
