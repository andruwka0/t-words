from __future__ import annotations

import asyncio
from collections import defaultdict
from fastapi import WebSocket


class SessionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, session_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections[session_id].add(ws)

    def disconnect(self, session_id: str, ws: WebSocket) -> None:
        bucket = self._connections.get(session_id)
        if not bucket:
            return
        bucket.discard(ws)
        if not bucket:
            self._connections.pop(session_id, None)

    async def broadcast(self, session_id: str, payload: dict) -> None:
        async with self._lock:
            targets = list(self._connections.get(session_id, set()))
        if not targets:
            return

        dead: list[WebSocket] = []

        async def _send(conn: WebSocket) -> None:
            try:
                await conn.send_json(payload)
            except RuntimeError:
                dead.append(conn)

        await asyncio.gather(*[_send(conn) for conn in targets], return_exceptions=True)
        for ws in dead:
            self.disconnect(session_id, ws)
