from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
import json

import httpx

from app.core.enums import OrderSide, OrderStatus, OrderType, PositionSide
from app.execution.protocol import (
    BalanceView,
    FillView,
    OrderView,
    PlaceOrderRequest,
    PlaceOrderResponse,
    PositionView,
)


class HttpExecutionClient:
    """Talks to execution-worker over HTTP. Backend never imports Hummingbot objects."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _client(self, timeout: float | None = None) -> httpx.AsyncClient:
        # Internal worker RPC must not follow HTTP(S)_PROXY.
        return httpx.AsyncClient(timeout=self._timeout if timeout is None else timeout, trust_env=False)

    async def health(self) -> bool:
        try:
            async with self._client() as client:
                response = await client.get(f"{self._base_url}/health")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def connect(self) -> None:
        async with self._client() as client:
            response = await client.post(f"{self._base_url}/rpc/connect")
            response.raise_for_status()

    async def disconnect(self) -> None:
        async with self._client() as client:
            response = await client.post(f"{self._base_url}/rpc/disconnect")
            response.raise_for_status()

    async def get_balance(self) -> BalanceView:
        async with self._client() as client:
            response = await client.get(f"{self._base_url}/rpc/balance")
            response.raise_for_status()
        return BalanceView.model_validate(response.json())

    async def get_positions(self) -> list[PositionView]:
        async with self._client() as client:
            response = await client.get(f"{self._base_url}/rpc/positions")
            response.raise_for_status()
        return [PositionView.model_validate(item) for item in response.json()]

    async def get_position(self, symbol: str) -> PositionView:
        async with self._client() as client:
            response = await client.get(f"{self._base_url}/rpc/position", params={"symbol": symbol})
            response.raise_for_status()
        return PositionView.model_validate(response.json())

    async def get_open_orders(self, symbol: str | None = None) -> list[OrderView]:
        params = {"symbol": symbol} if symbol else None
        async with self._client() as client:
            response = await client.get(f"{self._base_url}/rpc/open_orders", params=params)
            response.raise_for_status()
        return [OrderView.model_validate(item) for item in response.json()]

    async def get_order(self, cloid: str) -> OrderView | None:
        async with self._client() as client:
            response = await client.get(f"{self._base_url}/rpc/order/{cloid}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
        return OrderView.model_validate(response.json())

    async def get_fills(self) -> list[FillView]:
        async with self._client() as client:
            response = await client.get(f"{self._base_url}/rpc/fills")
            response.raise_for_status()
        return [FillView.model_validate(item) for item in response.json()]

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        async with self._client() as client:
            response = await client.post(
                f"{self._base_url}/rpc/set_leverage",
                json={"symbol": symbol, "leverage": leverage},
            )
            response.raise_for_status()

    async def place_order(self, request: PlaceOrderRequest) -> PlaceOrderResponse:
        async with self._client() as client:
            response = await client.post(
                f"{self._base_url}/rpc/place_order",
                json=request.model_dump(mode="json"),
            )
            response.raise_for_status()
        return PlaceOrderResponse.model_validate(response.json())

    async def cancel_order(self, cloid: str, request_id: str) -> OrderView | None:
        async with self._client() as client:
            response = await client.post(
                f"{self._base_url}/rpc/cancel_order",
                json={"cloid": cloid, "request_id": request_id},
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
        return OrderView.model_validate(response.json())

    async def get_market_data(self, symbol: str) -> dict[str, Decimal]:
        async with self._client() as client:
            response = await client.get(f"{self._base_url}/rpc/market_data", params={"symbol": symbol})
            response.raise_for_status()
        data = response.json()
        return {key: Decimal(str(value)) for key, value in data.items()}

    async def stream_events(self) -> AsyncIterator[dict]:
        async with self._client(timeout=None) as client:
            async with client.stream("GET", f"{self._base_url}/rpc/stream_events") as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        yield json.loads(line[6:])


__all__ = [
    "HttpExecutionClient",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PositionSide",
]
