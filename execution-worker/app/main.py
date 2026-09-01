from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.mock_adapter import MockExecutionAdapter
from app.protocol import PlaceOrderRequest

adapter = MockExecutionAdapter()
app = FastAPI(title="newhbot-execution-worker")


class LeverageBody(BaseModel):
    symbol: str
    leverage: int


class CancelBody(BaseModel):
    cloid: str
    request_id: str


class BehaviorBody(BaseModel):
    behavior: str


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "mode": "mock", "connected": adapter.connected}


@app.post("/rpc/connect")
async def rpc_connect() -> dict:
    await adapter.connect()
    return {"ok": True}


@app.post("/rpc/disconnect")
async def rpc_disconnect() -> dict:
    await adapter.disconnect()
    return {"ok": True}


@app.get("/rpc/balance")
async def rpc_balance() -> dict:
    return (await adapter.get_balance()).model_dump(mode="json")


@app.get("/rpc/positions")
async def rpc_positions() -> list:
    return [item.model_dump(mode="json") for item in await adapter.get_positions()]


@app.get("/rpc/position")
async def rpc_position(symbol: str) -> dict:
    return (await adapter.get_position(symbol)).model_dump(mode="json")


@app.get("/rpc/open_orders")
async def rpc_open_orders(symbol: str | None = None) -> list:
    return [item.model_dump(mode="json") for item in await adapter.get_open_orders(symbol)]


@app.get("/rpc/order/{cloid}")
async def rpc_order(cloid: str) -> dict:
    order = await adapter.get_order(cloid)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order.model_dump(mode="json")


@app.get("/rpc/fills")
async def rpc_fills() -> list:
    return [item.model_dump(mode="json") for item in await adapter.get_fills()]


@app.post("/rpc/set_leverage")
async def rpc_set_leverage(body: LeverageBody) -> dict:
    await adapter.set_leverage(body.symbol, body.leverage)
    return {"ok": True}


@app.post("/rpc/place_order")
async def rpc_place_order(body: PlaceOrderRequest) -> dict:
    try:
        result = await adapter.place_order(body)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@app.post("/rpc/cancel_order")
async def rpc_cancel_order(body: CancelBody) -> dict:
    order = await adapter.cancel_order(body.cloid, body.request_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order.model_dump(mode="json")


@app.get("/rpc/available_balance")
async def rpc_available_balance() -> dict:
    value = await adapter.get_available_balance()
    return {"available": str(value)}


@app.get("/rpc/stream_events")
async def rpc_stream_events() -> StreamingResponse:
    """Narrow event stream. Backend EventHub is the UI fan-out; this is worker-local."""

    async def gen():
        async for item in adapter.stream_events():
            yield f"data: {json.dumps(item, default=str)}\n\n"
        await asyncio.sleep(0)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/rpc/market_data")
async def rpc_market_data(symbol: str) -> dict:
    data = await adapter.get_market_data(symbol)
    return {key: str(value) for key, value in data.items()}


@app.post("/rpc/test/behavior")
async def rpc_test_behavior(body: BehaviorBody) -> dict:
    """Mock-only test hook. Not a trading path for production Hyperliquid."""
    adapter.set_behavior(body.behavior)
    return {"ok": True, "behavior": body.behavior}
