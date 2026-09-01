from __future__ import annotations

"""Strategy runtime stub. PHASE 2: interface only, no live plugin execution."""

from dataclasses import dataclass

from app.core.enums import SignalType


@dataclass(frozen=True)
class StrategySnapshot:
    symbol: str
    mid_price: str
    position_side: str


class StrategyRuntime:
    """Reserved sandbox boundary. Must never import execution or place orders."""

    def evaluate(self, snapshot: StrategySnapshot) -> SignalType:
        _ = snapshot
        return SignalType.HOLD
