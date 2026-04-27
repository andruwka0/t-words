from __future__ import annotations

from collections import defaultdict
from fastapi import WebSocket


class SessionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, session_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[session_id].add(ws)

    def disconnect(self, session_id: str, ws: WebSocket) -> None:
        self._connections[session_id].discard(ws)

    async def broadcast(self, session_id: str, payload: dict) -> None:
        dead = []
        for conn in self._connections.get(session_id, set()):
            try:
                await conn.send_json(payload)
            except RuntimeError:
                dead.append(conn)
        for ws in dead:
            self.disconnect(session_id, ws)
