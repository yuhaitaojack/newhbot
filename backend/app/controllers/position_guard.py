from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import PositionSide, SignalType, SystemState

OPENING_SIGNALS = {SignalType.LONG, SignalType.SHORT}


@dataclass(frozen=True)
class GuardInput:
    local_side: PositionSide
    exchange_side: PositionSide
    has_unknown_orders: bool
    system_state: SystemState
    configured_pair: str
    target_pair: str
    exchange_connected: bool
    has_foreign_positions: bool = False


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str


class PositionGuard:
    """Single-position lock. Exchange snapshot must be supplied by the caller (Controller)."""

    def can_open_position(self, inp: GuardInput) -> GuardResult:
        if inp.target_pair != inp.configured_pair:
            return GuardResult(False, "target pair is not the configured trading pair")
        if not inp.exchange_connected:
            return GuardResult(False, "exchange connection unavailable")
        if inp.has_foreign_positions:
            return GuardResult(False, "account has a position on a non-configured pair")
        if inp.has_unknown_orders:
            return GuardResult(False, "unknown order exists; new opens are forbidden")
        if inp.system_state == SystemState.RECOVERY:
            return GuardResult(False, "recovery forbids new opens")
        if inp.system_state != SystemState.RUNNING:
            return GuardResult(False, f"system is {inp.system_state.value}, not RUNNING")
        if inp.local_side != PositionSide.FLAT:
            return GuardResult(False, f"local position is {inp.local_side.value}, not FLAT")
        if inp.exchange_side != PositionSide.FLAT:
            return GuardResult(False, f"exchange position is {inp.exchange_side.value}, not FLAT")
        if inp.exchange_side == PositionSide.UNKNOWN or inp.local_side == PositionSide.UNKNOWN:
            return GuardResult(False, "position side is UNKNOWN")
        return GuardResult(True, "ok")

    def reverse_is_forbidden(self, local: PositionSide, signal: SignalType) -> bool:
        if local == PositionSide.LONG and signal == SignalType.SHORT:
            return True
        if local == PositionSide.SHORT and signal == SignalType.LONG:
            return True
        return False
