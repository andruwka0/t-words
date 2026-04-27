from __future__ import annotations

import json
import time
from typing import Any


class GameSession:
    def __init__(self, redis_client: Any, session_id: str) -> None:
        self.redis = redis_client
        self.session_id = session_id
        self.key = f'game:session:{session_id}'

    async def bootstrap(
        self,
        player_id: str,
        player_name: str,
        dictionary_pack: str = 'basic',
        mode: str = 'duel',
        bot_id: str = 'bot_arbitrator',
        bot_name: str = 'Bot',
        initial_letter: str = 'а',
    ) -> dict[str, Any]:
        now = int(time.time())
        state = {
            'session_id': self.session_id,
            'mode': mode,
            'dictionary_pack': dictionary_pack,
            'current_letter': initial_letter,
            'used_words': [],
            'used_lemmas': [],
            'participants': [
                {'id': player_id, 'name': player_name, 'type': 'human'},
                {'id': bot_id, 'name': bot_name, 'type': 'bot'},
            ],
            'turn_order': [player_id, bot_id],
            'turn_index': 0,
            'turn_started_at': now,
            'turn_deadline': now + 15,
            'scores': {player_id: 0, bot_id: 0},
            'status': 'started',
            'protected_turn_until': None,
            'created_at': now,
            'updated_at': now,
        }
        await self.save(state)
        return state

    async def bootstrap_humans(
        self,
        first_id: str,
        first_name: str,
        second_id: str,
        second_name: str,
        dictionary_pack: str = 'basic',
        mode: str = 'duel',
        initial_letter: str = 'а',
    ) -> dict[str, Any]:
        now = int(time.time())
        state = {
            'session_id': self.session_id,
            'mode': mode,
            'dictionary_pack': dictionary_pack,
            'current_letter': initial_letter,
            'used_words': [],
            'used_lemmas': [],
            'participants': [
                {'id': first_id, 'name': first_name, 'type': 'human'},
                {'id': second_id, 'name': second_name, 'type': 'human'},
            ],
            'turn_order': [first_id, second_id],
            'turn_index': 0,
            'turn_started_at': now,
            'turn_deadline': now + 15,
            'scores': {first_id: 0, second_id: 0},
            'status': 'started',
            'protected_turn_until': None,
            'created_at': now,
            'updated_at': now,
        }
        await self.save(state)
        return state

    async def load(self) -> dict[str, Any] | None:
        raw = await self.redis.get(self.key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode('utf-8')
        return json.loads(raw)

    async def save(self, state: dict[str, Any]) -> None:
        state['updated_at'] = int(time.time())
        await self.redis.set(self.key, json.dumps(state, ensure_ascii=False))

    async def apply_word(self, player_id: str, word: str, score: int, lemma: str | None = None) -> dict[str, Any]:
        state = await self.load()
        if state is None:
            raise RuntimeError('session_not_found')
        state['used_words'].append(word)
        if lemma:
            state.setdefault('used_lemmas', []).append(lemma)
        state['current_letter'] = self._next_letter(word)
        state['scores'][player_id] = state['scores'].get(player_id, 0) + score
        state['turn_index'] = (state['turn_index'] + 1) % len(state['turn_order'])
        now = int(time.time())
        state['turn_started_at'] = now
        state['turn_deadline'] = now + 15
        await self.save(state)
        return state

    async def apply_penalty(self, player_id: str, penalty: int, switch_turn: bool = True) -> dict[str, Any]:
        state = await self.load()
        if state is None:
            raise RuntimeError('session_not_found')
        state['scores'][player_id] = state['scores'].get(player_id, 0) - abs(int(penalty))
        if switch_turn:
            state['turn_index'] = (state['turn_index'] + 1) % len(state['turn_order'])
        now = int(time.time())
        state['turn_started_at'] = now
        state['turn_deadline'] = now + 15
        await self.save(state)
        return state

    async def hot_swap_bot(self, new_player_id: str, freeze_seconds: int = 3) -> dict[str, Any]:
        state = await self.load()
        if state is None:
            raise RuntimeError('session_not_found')

        bot_id = None
        for p in state['participants']:
            if p['type'] == 'bot':
                bot_id = p['id']
                p['id'] = new_player_id
                p['name'] = new_player_id
                p['type'] = 'human'
                break

        if not bot_id:
            state['participants'].append({'id': new_player_id, 'name': new_player_id, 'type': 'human'})
            state['turn_order'].append(new_player_id)
        else:
            state['turn_order'] = [new_player_id if pid == bot_id else pid for pid in state['turn_order']]
            state['scores'][new_player_id] = state['scores'].pop(bot_id, 0)

        state['protected_turn_until'] = int(time.time()) + freeze_seconds
        await self.save(state)
        return state

    @staticmethod
    def _next_letter(word: str) -> str:
        for ch in reversed(word.lower()):
            if ch not in {'ь', 'ъ', 'ы'}:
                return ch
        return word[-1].lower()
