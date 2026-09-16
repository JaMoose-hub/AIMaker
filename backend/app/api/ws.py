"""WS /ws/detections - latest-state fan-out of detection messages.

- On connect the client first receives a hello message.
- Each client has an asyncio.Queue(maxsize=1); the broadcaster drops the old
  message before putting the new one, so slow clients simply skip intermediate
  states and always get the newest (never a backlog).
- The vision worker thread publishes via publish_threadsafe(), which hops onto
  the server event loop with asyncio.run_coroutine_threadsafe.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)

router = APIRouter()


class DetectionBroadcaster:
    def __init__(self) -> None:
        self._clients: set[asyncio.Queue[str]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called at app startup with the server's running event loop."""
        self._loop = loop

    def unbind_loop(self) -> None:
        self._loop = None

    def register(self) -> asyncio.Queue:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        self._clients.add(q)
        return q

    def unregister(self, q: asyncio.Queue) -> None:
        self._clients.discard(q)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def publish_json(self, text: str) -> None:
        """Fan out one serialized message; latest-only per client."""
        for q in list(self._clients):
            if q.full():
                try:
                    q.get_nowait()  # drop the stale message
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(text)
            except asyncio.QueueFull:  # raced with a consumer; skip this round
                pass

    def publish_threadsafe(self, message: dict) -> None:
        """Called from the vision worker thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        text = json.dumps(message, ensure_ascii=False)
        try:
            asyncio.run_coroutine_threadsafe(self.publish_json(text), loop)
        except RuntimeError:
            # loop shut down between the check and the call - fine during teardown
            pass


@router.websocket("/ws/detections")
async def ws_detections(ws: WebSocket) -> None:
    app = ws.app
    cfg = app.state.config
    runtime = app.state.runtime_manager.snapshot()
    broadcaster: DetectionBroadcaster = app.state.broadcaster

    await ws.accept()
    # Prefer the ACTUAL frame size seen by the vision worker (device cameras
    # may deliver a different resolution than configured); fall back to the
    # configured size before the first frame has arrived.
    detection_state = getattr(app.state, "detection_state", None)
    video_size = detection_state.get_video_size() if detection_state is not None else None
    if video_size is None:
        video_size = (cfg.camera.width, cfg.camera.height)
    await ws.send_json(
        {
            "type": "hello",
            "board_id": runtime.board_id,
            "runtime_revision": runtime.runtime_revision,
            "video_size": [video_size[0], video_size[1]],
        }
    )

    queue = broadcaster.register()
    recv_task: asyncio.Task | None = None
    get_task: asyncio.Task | None = None
    try:
        recv_task = asyncio.create_task(ws.receive())
        while True:
            get_task = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait(
                {get_task, recv_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if recv_task in done:
                try:
                    msg = recv_task.result()
                except (WebSocketDisconnect, RuntimeError):
                    break
                if msg.get("type") == "websocket.disconnect":
                    break
                # Inbound client messages are ignored; keep listening.
                recv_task = asyncio.create_task(ws.receive())
            if get_task in done:
                await ws.send_text(get_task.result())
            else:
                get_task.cancel()
                get_task = None
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        log.exception("ws/detections client loop failed")
    finally:
        broadcaster.unregister(queue)
        for task in (recv_task, get_task):
            if task is not None and not task.done():
                task.cancel()
