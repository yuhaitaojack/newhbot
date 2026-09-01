from __future__ import annotations

import asyncio
import json
from decimal import Decimal

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.factory import build_runtime
from app.hyperliquid_adapter import ExecutionDisabled
from app.protocol import PlaceOrderRequest

runtime = build_runtime()
app = FastAPI(title="newhbot-execution-worker")


class LeverageBody(BaseModel):
    symbol: str
    leverage: int


class CancelBody(BaseModel):
    cloid: str
    request_id: str


class BehaviorBody(BaseModel):
    behavior: str


class QueryFailBody(BaseModel):
    enabled: bool


class ConfigureBody(BaseModel):
    trading_pair: str
    slippage: Decimal | None = None
    leverage: int | None = None


@app.get("/health")
async def health() -> dict:
    return runtime.health_payload()


@app.post("/rpc/connect")
async def rpc_connect() -> dict:
    await runtime.connect()
    return {"ok": True, **runtime.health_payload()}


@app.post("/rpc/disconnect")
async def rpc_disconnect() -> dict:
    await runtime.disconnect()
    return {"ok": True}


@app.post("/rpc/configure")
async def rpc_configure(body: ConfigureBody) -> dict:
    runtime.configure(trading_pair=body.trading_pair, slippage=body.slippage, leverage=body.leverage)
    return {"ok": True, "trading_pair": runtime.config.trading_pair}


@app.get("/rpc/balance")
async def rpc_balance() -> dict:
    try:
        return (await runtime.get_balance()).model_dump(mode="json")
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc


@app.get("/rpc/positions")
async def rpc_positions() -> list:
    try:
        return [item.model_dump(mode="json") for item in await runtime.get_positions()]
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc


@app.get("/rpc/position")
async def rpc_position(symbol: str) -> dict:
    try:
        return (await runtime.get_position(symbol)).model_dump(mode="json")
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc


@app.get("/rpc/open_orders")
async def rpc_open_orders(symbol: str | None = None) -> list:
    return [item.model_dump(mode="json") for item in await runtime.get_open_orders(symbol)]


@app.get("/rpc/order/{cloid}")
async def rpc_order(cloid: str) -> dict:
    try:
        order = await runtime.get_order(cloid)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order.model_dump(mode="json")


@app.get("/rpc/fills")
async def rpc_fills() -> list:
    try:
        return [item.model_dump(mode="json") for item in await runtime.get_fills()]
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc


@app.post("/rpc/set_leverage")
async def rpc_set_leverage(body: LeverageBody) -> dict:
    try:
        await runtime.set_leverage(body.symbol, body.leverage)
    except ExecutionDisabled as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/rpc/place_order")
async def rpc_place_order(body: PlaceOrderRequest) -> dict:
    try:
        result = await runtime.place_order(body)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except ExecutionDisabled as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@app.post("/rpc/cancel_order")
async def rpc_cancel_order(body: CancelBody) -> dict:
    try:
        order = await runtime.cancel_order(body.cloid, body.request_id)
    except ExecutionDisabled as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order.model_dump(mode="json")


@app.get("/rpc/available_balance")
async def rpc_available_balance() -> dict:
    value = await runtime.get_available_balance()
    return {"available": str(value)}


@app.get("/rpc/stream_events")
async def rpc_stream_events() -> StreamingResponse:
    async def gen():
        async for item in runtime.stream_events():
            yield f"data: {json.dumps(item, default=str)}\n\n"
        await asyncio.sleep(0)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/rpc/market_data")
async def rpc_market_data(symbol: str) -> dict:
    data = await runtime.get_market_data(symbol)
    return {key: str(value) for key, value in data.items()}


@app.post("/rpc/test/behavior")
async def rpc_test_behavior(body: BehaviorBody) -> dict:
    setter = getattr(runtime.inner, "set_behavior", None)
    if setter is None:
        raise HTTPException(status_code=400, detail="behavior hook is mock-only")
    setter(body.behavior)
    return {"ok": True, "behavior": body.behavior}


@app.post("/rpc/test/query_fail")
async def rpc_test_query_fail(body: QueryFailBody) -> dict:
    setter = getattr(runtime.inner, "set_query_fail", None)
    if setter is None:
        raise HTTPException(status_code=400, detail="query_fail hook is mock-only")
    setter(body.enabled)
    return {"ok": True, "query_fail": body.enabled}


@app.post("/rpc/test/ws_disconnect")
async def rpc_test_ws_disconnect() -> dict:
    runtime.mark_ws_down()
    return runtime.health_payload()


@app.post("/rpc/test/rest_resync")
async def rpc_test_rest_resync() -> dict:
    await runtime.rest_resync()
    return runtime.health_payload()
