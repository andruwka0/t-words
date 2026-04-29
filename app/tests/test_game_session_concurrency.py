from __future__ import annotations

import asyncio

from app.game_session import GameSession
from app.local_redis import LocalRedis


def test_apply_word_is_atomic_for_same_turn_player() -> None:
    async def scenario() -> None:
        redis = LocalRedis()
        session = GameSession(redis, 'test_atomic_turn')
        await session.bootstrap_humans('user_1', 'P1', 'user_2', 'P2', initial_letter='а')

        async def submit(word: str) -> str:
            try:
                await session.apply_word('user_1', word, score=3, lemma=word)
                return 'ok'
            except RuntimeError as exc:
                return str(exc)

        first, second = await asyncio.gather(submit('арбуз'), submit('ананас'))
        assert sorted([first, second]) == ['not_your_turn', 'ok']

        state = await session.load()
        assert state is not None
        assert len(state['used_words']) == 1
        assert state['turn_order'][state['turn_index']] == 'user_2'

    asyncio.run(scenario())


def test_apply_penalty_rejects_outdated_turn_actor() -> None:
    async def scenario() -> None:
        redis = LocalRedis()
        session = GameSession(redis, 'test_penalty_actor')
        await session.bootstrap_humans('user_1', 'P1', 'user_2', 'P2', initial_letter='а')

        await session.apply_word('user_1', 'арбуз', score=1, lemma='арбуз')
        try:
            await session.apply_penalty('user_1', penalty=2, switch_turn=True)
            assert False, 'expected RuntimeError(not_your_turn)'
        except RuntimeError as exc:
            assert str(exc) == 'not_your_turn'

    asyncio.run(scenario())
