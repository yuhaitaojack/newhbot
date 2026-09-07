"""TEST HELPER ONLY. Production Adapter does not compare a Worker REST list
against a second Hummingbot list. Connector account_positions is the only
execution-layer position source.
"""

from __future__ import annotations

from app.exchange_models import ExchangePosition
from app.protocol import PositionSide


def position_fingerprint(positions: list[ExchangePosition]) -> frozenset[tuple[str, str, str]]:
    return frozenset(
        (item.symbol, item.side.value, str(item.size))
        for item in positions
        if item.side != PositionSide.FLAT and item.size != 0
    )


def compare_rest_and_hummingbot(
    rest: list[ExchangePosition],
    hummingbot: list[ExchangePosition],
) -> str | None:
    """None means agreement. Otherwise a disagreement reason.

    Not used on the production Adapter path after STEP 2.
    """
    rest_fp = position_fingerprint(rest)
    hb_fp = position_fingerprint(hummingbot)
    if rest_fp != hb_fp:
        return f"REST snapshot and Hummingbot account_positions disagree rest={sorted(rest_fp)} hb={sorted(hb_fp)}"
    return None
