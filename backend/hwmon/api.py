"""HTTP + WebSocket API. Read-only: GET endpoints and a push-only WebSocket."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.get("/api/info")
def info(request: Request) -> dict:
    return request.app.state.static_info


@router.get("/api/snapshot")
def snapshot(request: Request) -> dict:
    snap = request.app.state.sampler.latest
    if snap is None:
        raise HTTPException(503, "No sample collected yet")
    return snap


@router.get("/api/history")
async def history(
    request: Request,
    keys: str = Query(..., description="Comma-separated metric keys"),
    start: float | None = None,
    end: float | None = None,
    max_points: int = Query(1000, ge=10, le=5000),
) -> dict:
    key_list = [k for k in keys.split(",") if k]
    if not key_list:
        raise HTTPException(400, "keys must name at least one metric")
    end = end if end is not None else time.time()
    start = start if start is not None else end - 3600
    if start >= end:
        raise HTTPException(400, "start must be before end")
    store = request.app.state.store
    return await asyncio.to_thread(store.history, key_list, start, end, max_points)


@router.websocket("/ws/live")
async def live(ws: WebSocket) -> None:
    await ws.accept()
    hub = ws.app.state.hub
    q = hub.subscribe()
    latest = ws.app.state.sampler.latest
    try:
        if latest is not None:
            await ws.send_json(latest)
        # Incoming messages are never read as commands; we only watch for disconnects.
        receiver = asyncio.create_task(_drain(ws))
        try:
            while not receiver.done():
                getter = asyncio.create_task(q.get())
                done, _ = await asyncio.wait({getter, receiver}, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    await ws.send_json(getter.result())
                else:
                    getter.cancel()
        finally:
            receiver.cancel()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe(q)


async def _drain(ws: WebSocket) -> None:
    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        return
