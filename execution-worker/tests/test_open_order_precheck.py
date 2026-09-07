from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.open_order_precheck import snapshot_open_orders


class _StubInner:
    def __init__(self, rows, *, address="0x" + "ab" * 20) -> None:
        self.hyperliquid_perpetual_address = address
        self.rows = rows
        self.calls: list[dict] = []

    async def _api_post(self, path_url, data=None, is_auth_required=False, **kwargs):
        self.calls.append(
            {"path_url": path_url, "data": data, "is_auth_required": is_auth_required}
        )
        return self.rows


@pytest.mark.asyncio
async def test_precheck_empty_is_not_blocking() -> None:
    inner = _StubInner([])
    out = await snapshot_open_orders(inner, configured_pair="BTC-USD")
    assert out["status"] == "VERIFIED"
    assert out["configured_open_count"] == 0
    assert out["other_open_count"] == 0
    assert out["blocking"] is False
    assert out["persisted"] is False
    assert inner.calls[0]["path_url"] == "/info"
    assert inner.calls[0]["data"]["type"] == "openOrders"
    assert inner.calls[0]["is_auth_required"] is False
    assert "user" in inner.calls[0]["data"]


@pytest.mark.asyncio
async def test_precheck_btc_resting_order_is_blocking() -> None:
    inner = _StubInner([{"coin": "BTC", "sz": "0.01", "oid": 1, "side": "B"}])
    out = await snapshot_open_orders(inner)
    assert out["configured_open_count"] == 1
    assert out["blocking"] is True
    assert out["persisted"] is False


@pytest.mark.asyncio
async def test_precheck_other_coin_does_not_count_as_btc() -> None:
    inner = _StubInner([{"coin": "ETH", "sz": "1", "oid": 2, "side": "A"}])
    out = await snapshot_open_orders(inner)
    assert out["configured_open_count"] == 0
    assert out["other_open_count"] == 1
    assert out["other_coins"] == ["ETH"]
    assert out["blocking"] is False


@pytest.mark.asyncio
async def test_precheck_missing_api_is_not_available() -> None:
    inner = SimpleNamespace(hyperliquid_perpetual_address="0x" + "cd" * 20)
    out = await snapshot_open_orders(inner)
    assert out["status"] == "NOT_AVAILABLE"
    assert out["blocking"] is True


@pytest.mark.asyncio
async def test_precheck_does_not_treat_non_list_as_empty() -> None:
    inner = _StubInner({"error": "nope"})
    out = await snapshot_open_orders(inner)
    assert out["status"] == "FAILED"
    assert out["configured_open_count"] is None
    assert out["blocking"] is True
