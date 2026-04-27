from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class MatchAssignment:
    session_id: str | None
    opponent_type: str
    opponent_id: str | None
    opponent_name: str | None = None


class MatchmakingService:
    def __init__(self, redis_client: Any) -> None:
        self.redis = redis_client

    async def find_or_create(self, player_id: str, player_name: str, desired_stake: int | None = None) -> MatchAssignment:
        waiting_entries = await self.redis.lrange('mm:queue', 0, -1)
        for raw in waiting_entries:
            waiting_id, waiting_name = self._decode(raw)
            if not waiting_id or waiting_id == player_id:
                continue
            queued_at = await self.redis.get(f'mm:queued_at:{waiting_id}')
            if not queued_at:
                continue
            if desired_stake is not None:
                waiting_stake_raw = await self.redis.get(f'mm:queued_stake:{waiting_id}')
                waiting_stake = int(waiting_stake_raw) if str(waiting_stake_raw).isdigit() else 0
                if waiting_stake != desired_stake:
                    continue
            removed = await self.redis.lrem('mm:queue', 1, raw)
            if removed <= 0:
                continue
            session_id = f'm_{int(time.time() * 1000)}'
            return MatchAssignment(
                session_id=session_id,
                opponent_type='human',
                opponent_id=waiting_id,
                opponent_name=waiting_name,
            )

        await self.redis.rpush('mm:queue', self._encode(player_id, player_name))
        return MatchAssignment(session_id=None, opponent_type='waiting', opponent_id=None)

    @staticmethod
    def _encode(player_id: str, player_name: str) -> str:
        return f'{player_id}|{player_name}'

    @staticmethod
    def _decode(raw: str) -> tuple[str | None, str | None]:
        if '|' not in raw:
            return raw, raw
        left, right = raw.split('|', 1)
        return left, right
