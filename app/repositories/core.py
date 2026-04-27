from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appeal, Match, MatchParticipant, Rating, User


class UserRepository:
    async def get_or_create(self, db: AsyncSession, username: str) -> User:
        q = await db.execute(select(User).where(User.username == username))
        user = q.scalar_one_or_none()
        if user:
            changed = False
            if not user.login:
                user.login = user.username
                changed = True
            if not user.nickname:
                user.nickname = user.username
                changed = True
            if not user.public_id:
                user.public_id = self.make_public_id()
                changed = True
            if changed:
                await db.commit()
                await db.refresh(user)
            return user
        user = User(username=username, login=username, nickname=username, public_id=self.make_public_id(), coins=100)
        db.add(user)
        await db.flush()
        db.add(Rating(user_id=user.id, value=0))
        await db.commit()
        await db.refresh(user)
        return user

    def make_public_id(self) -> str:
        return f'plr-{uuid4().hex[:12]}'

    async def get_by_id(self, db: AsyncSession, user_id: int) -> User | None:
        return await db.get(User, user_id)

    async def get_by_login(self, db: AsyncSession, login: str) -> User | None:
        normalized = login.strip().lower()
        q = await db.execute(select(User).where(User.login == normalized))
        return q.scalar_one_or_none()

    async def create_account(
        self,
        db: AsyncSession,
        login: str,
        password_hash: str,
        nickname: str | None = None,
    ) -> User:
        normalized = login.strip().lower()
        display_name = (nickname or login).strip()
        user = User(
            username=normalized,
            login=normalized,
            nickname=display_name,
            password_hash=password_hash,
            public_id=self.make_public_id(),
            coins=100,
        )
        db.add(user)
        await db.flush()
        db.add(Rating(user_id=user.id, value=0))
        await db.commit()
        await db.refresh(user)
        return user

    async def update_account(
        self,
        db: AsyncSession,
        user: User,
        login: str | None = None,
        nickname: str | None = None,
        password_hash: str | None = None,
    ) -> User:
        if login is not None:
            user.login = login.strip().lower()
            user.username = user.login
        if nickname is not None:
            clean_nickname = nickname.strip()
            user.nickname = clean_nickname
        if password_hash is not None:
            user.password_hash = password_hash
        await db.commit()
        await db.refresh(user)
        return user

    async def add_word_stats(self, db: AsyncSession, user_id: int, score: int, response_seconds: float) -> None:
        user = await db.get(User, user_id)
        if not user:
            return
        user.coins = int(user.coins or 0) + max(0, int(score))
        if response_seconds > 0 and (user.fastest_word_seconds is None or response_seconds < user.fastest_word_seconds):
            user.fastest_word_seconds = response_seconds
        await db.commit()

    async def add_bot_win(self, db: AsyncSession, user_id: int, bot_level: str) -> None:
        user = await db.get(User, user_id)
        if not user:
            return
        if bot_level == 'easy':
            user.easy_bot_wins = int(user.easy_bot_wins or 0) + 1
        elif bot_level == 'hard':
            user.hard_bot_wins = int(user.hard_bot_wins or 0) + 1
        else:
            user.medium_bot_wins = int(user.medium_bot_wins or 0) + 1
        await db.commit()

    async def claim_daily_reward(self, db: AsyncSession, user_id: int, amount: int = 100) -> tuple[bool, User | None]:
        user = await db.get(User, user_id)
        if not user:
            return False, None

        now = datetime.utcnow()
        if user.last_daily_claim_at and now < user.last_daily_claim_at + timedelta(days=1):
            return False, user

        user.coins = int(user.coins or 0) + int(amount)
        user.last_daily_claim_at = now
        await db.commit()
        await db.refresh(user)
        return True, user


class MatchRepository:
    @staticmethod
    def arena_for_score(total_score: int) -> str:
        return 'Arena I (0+)' if int(total_score) < 666 else 'Arena II (666+)'

    async def user_total_score(self, db: AsyncSession, user_id: int) -> int:
        q = select(MatchParticipant, Match).join(Match, Match.id == MatchParticipant.match_id).where(
            MatchParticipant.participant_type == 'human',
            MatchParticipant.user_id == user_id,
        )
        rows = (await db.execute(q)).all()
        total = 0
        for part, match in rows:
            points = int(part.score or 0)
            if match.winner_ref != part.participant_ref:
                points = int(points * 0.5)
            total += points
        return max(0, int(total))

    async def create(
        self,
        db: AsyncSession,
        mode: str,
        dictionary_pack: str,
        first_stake: int = 0,
        second_stake: int = 0,
        first_multiplier: float = 1.0,
        second_multiplier: float = 1.0,
        median_multiplier: float = 1.0,
    ) -> Match:
        match = Match(
            mode=mode,
            dictionary_pack=dictionary_pack,
            first_stake=first_stake,
            second_stake=second_stake,
            first_multiplier=first_multiplier,
            second_multiplier=second_multiplier,
            median_multiplier=median_multiplier,
        )
        db.add(match)
        await db.commit()
        await db.refresh(match)
        return match

    async def add_participant(
        self,
        db: AsyncSession,
        match_id: int,
        participant_ref: str,
        participant_name: str,
        participant_type: str,
        score: int = 0,
        user_id: int | None = None,
    ) -> MatchParticipant:
        part = MatchParticipant(
            match_id=match_id,
            participant_ref=participant_ref,
            participant_name=participant_name,
            participant_type=participant_type,
            user_id=user_id,
            score=score,
        )
        db.add(part)
        await db.commit()
        await db.refresh(part)
        return part

    async def history(self, db: AsyncSession, limit: int = 20) -> list[Match]:
        q = await db.execute(select(Match).order_by(Match.created_at.desc()).limit(limit))
        return list(q.scalars())

    async def set_scores_and_winner(
        self,
        db: AsyncSession,
        match_id: int,
        scores: dict[str, int],
        winner_ref: str | None,
        winner_name: str | None,
    ) -> None:
        q = await db.execute(select(MatchParticipant).where(MatchParticipant.match_id == match_id))
        participants = q.scalars().all()
        for participant in participants:
            participant.score = int(scores.get(participant.participant_ref, participant.score))

        match = await db.get(Match, match_id)
        if match:
            match.winner_ref = winner_ref
            match.winner_name = winner_name
            if winner_ref and winner_ref.startswith('user_'):
                raw_id = winner_ref.replace('user_', '', 1)
                if raw_id.isdigit():
                    match.winner_id = int(raw_id)
        await db.commit()

    async def set_winner_payout(self, db: AsyncSession, match_id: int, payout: int) -> None:
        match = await db.get(Match, match_id)
        if not match:
            return
        match.winner_payout = int(max(0, payout))
        await db.commit()

    async def leaderboard(self, db: AsyncSession, limit: int = 20) -> list[dict[str, int | str]]:
        return await self.leaderboard_by_match_mode(db, mode='', limit=limit)

    async def leaderboard_by_match_mode(self, db: AsyncSession, mode: str, limit: int = 20) -> list[dict[str, int | str]]:
        q = select(MatchParticipant, Match).join(Match, Match.id == MatchParticipant.match_id).where(
            MatchParticipant.participant_type == 'human'
        )
        if mode:
            q = q.where(Match.mode == mode)
        rows = (await db.execute(q)).all()
        totals: dict[str, int] = {}
        for part, match in rows:
            name = part.participant_name or part.participant_ref
            points = int(part.score or 0)
            if match.winner_ref != part.participant_ref:
                points = int(points * 0.5)
            totals[name] = totals.get(name, 0) + points

        sorted_items = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:limit]
        leaderboard: list[dict[str, int | str]] = []
        for name, total in sorted_items:
            arena = self.arena_for_score(total)
            leaderboard.append({'name': name, 'total_score': total, 'arena': arena})
        return leaderboard


class AppealRepository:
    async def create(self, db: AsyncSession, match_id: int, player_ref: str, word: str, reason: str) -> Appeal:
        appeal = Appeal(match_id=match_id, player_ref=player_ref, word=word, reason=reason)
        db.add(appeal)
        await db.commit()
        await db.refresh(appeal)
        return appeal
