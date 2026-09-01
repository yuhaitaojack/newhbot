from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    from app.main import get_app_container

    container = get_app_container()
    await websocket.accept()
    queue = container.hub.subscribe()
    try:
        await websocket.send_json({"type": "hello", "payload": {"hint": "call GET /api/status for snapshot"}})
        while True:
            message = await queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        container.hub.unsubscribe(queue)
