from __future__ import annotations

from decimal import Decimal

import pytest

from app.hummingbot_place import place_with_injected_cloid


class RecordingConnector:
    def __init__(self) -> None:
        self.place_calls = 0
        self.buy_calls = 0
        self.sell_calls = 0
        self.last: dict | None = None

    def buy(self, *args, **kwargs):
        self.buy_calls += 1
        raise AssertionError("buy() must not be used; it mints a new MD5 cloid")

    def sell(self, *args, **kwargs):
        self.sell_calls += 1
        raise AssertionError("sell() must not be used; it mints a new MD5 cloid")

    async def _place_order(
        self,
        order_id: str,
        trading_pair: str,
        amount: Decimal,
        trade_type,
        order_type,
        price: Decimal,
        position_action=None,
        **kwargs,
    ):
        self.place_calls += 1
        if self.place_calls > 1:
            raise AssertionError("second _place_order is forbidden")
        self.last = {
            "order_id": order_id,
            "trading_pair": trading_pair,
            "amount": amount,
            "trade_type": trade_type,
            "order_type": order_type,
            "price": price,
            "position_action": position_action,
            "kwargs": kwargs,
        }
        return ("99", 0.0)


@pytest.mark.asyncio
async def test_injected_cloid_is_passed_verbatim_and_buy_sell_unused() -> None:
    connector = RecordingConnector()
    cloid = "0x" + "ab" * 16
    wire = {
        "cloid": cloid,
        "symbol": "BTC-USD",
        "is_buy": True,
        "sz": "0.2",
        "limit_px": "105.0",
        "reduce_only": False,
        "tif": "Ioc",
    }
    result = await place_with_injected_cloid(connector, wire)
    assert connector.buy_calls == 0
    assert connector.sell_calls == 0
    assert connector.place_calls == 1
    assert connector.last is not None
    assert connector.last["order_id"] == cloid
    assert result["order"]["cloid"] == cloid
    assert result["order"]["oid"] == "99"


@pytest.mark.asyncio
async def test_injected_cloid_registers_hummingbot_tracking_before_submit() -> None:
    class TrackingConnector(RecordingConnector):
        def __init__(self) -> None:
            super().__init__()
            self.in_flight_orders = {}
            self.tracking: dict = {}

        def start_tracking_order(self, **kwargs) -> None:
            self.tracking = kwargs

    connector = TrackingConnector()
    cloid = "0x" + "ef" * 16
    await place_with_injected_cloid(
        connector,
        {
            "cloid": cloid,
            "symbol": "BTC-USD",
            "is_buy": True,
            "sz": "0.2",
            "limit_px": "105.0",
            "reduce_only": False,
            "tif": "Ioc",
        },
    )
    assert connector.tracking["order_id"] == cloid
    assert connector.tracking["trading_pair"] == "BTC-USD"
    assert str(connector.tracking["amount"]) == "0.2"


@pytest.mark.asyncio
async def test_injected_cloid_records_exchange_id_after_submit() -> None:
    class SubmissionConnector(RecordingConnector):
        def __init__(self) -> None:
            super().__init__()
            self.submission: tuple[str, str, float | None] | None = None

        def record_submission(self, cloid: str, exchange_order_id: str, timestamp: float | None) -> None:
            self.submission = (cloid, exchange_order_id, timestamp)

    connector = SubmissionConnector()
    cloid = "0x" + "12" * 16
    await place_with_injected_cloid(
        connector,
        {
            "cloid": cloid,
            "symbol": "BTC-USD",
            "is_buy": True,
            "sz": "0.2",
            "limit_px": "105.0",
            "reduce_only": False,
            "tif": "Ioc",
        },
    )
    assert connector.submission == (cloid, "99", 0.0)


@pytest.mark.asyncio
async def test_injected_cloid_does_not_retry_on_failure() -> None:
    class OnceThenBoom(RecordingConnector):
        async def _place_order(self, *args, **kwargs):
            self.place_calls += 1
            raise TimeoutError("exchange hung after accept")

    connector = OnceThenBoom()
    wire = {
        "cloid": "0x" + "cd" * 16,
        "symbol": "BTC-USD",
        "is_buy": False,
        "sz": "0.1",
        "limit_px": "95.0",
        "reduce_only": True,
        "tif": "Ioc",
    }
    with pytest.raises(TimeoutError):
        await place_with_injected_cloid(connector, wire)
    assert connector.place_calls == 1
    with pytest.raises(TimeoutError):
        await place_with_injected_cloid(connector, wire)
    assert connector.place_calls == 2
    # Helper itself does not retry; a second call is a new invocation.
    # Worker Adapter must refuse that second invocation via _submitted_cloids.


@pytest.mark.asyncio
async def test_injected_cloid_records_failure_when_submit_raises() -> None:
    class FailureConnector(RecordingConnector):
        def __init__(self) -> None:
            super().__init__()
            self.failure: tuple[str, str, Exception] | None = None

        def record_failure(self, cloid: str, trading_pair: str, error: Exception) -> None:
            self.failure = (cloid, trading_pair, error)

        async def _place_order(self, *args, **kwargs):
            raise TimeoutError("exchange response unknown")

    connector = FailureConnector()
    cloid = "0x" + "34" * 16
    with pytest.raises(TimeoutError):
        await place_with_injected_cloid(
            connector,
            {
                "cloid": cloid,
                "symbol": "BTC-USD",
                "is_buy": True,
                "sz": "0.2",
                "limit_px": "105.0",
                "reduce_only": False,
                "tif": "Ioc",
            },
        )
    assert connector.failure is not None
    assert connector.failure[:2] == (cloid, "BTC-USD")


@pytest.mark.asyncio
async def test_injected_cloid_rejects_readonly_guard() -> None:
    from app.readonly_guard import ReadOnlyGuard, ReadOnlyViolation

    connector = RecordingConnector()
    guarded = ReadOnlyGuard(connector)
    wire = {
        "cloid": "0x" + "ab" * 16,
        "symbol": "BTC-USD",
        "is_buy": True,
        "sz": "0.2",
        "limit_px": "105.0",
        "reduce_only": False,
        "tif": "Ioc",
    }
    with pytest.raises(ReadOnlyViolation, match="ReadOnlyGuard"):
        await place_with_injected_cloid(guarded, wire)
    assert connector.place_calls == 0
