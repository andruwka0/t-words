from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    login: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    public_id: Mapped[str | None] = mapped_column(String(36), unique=True, index=True, nullable=True)
    coins: Mapped[int] = mapped_column(Integer, default=100)
    last_daily_claim_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    custom_words: Mapped[str] = mapped_column(Text, default='')
    unlocked_topics: Mapped[str] = mapped_column(Text, default='')
    purchase_stats: Mapped[str] = mapped_column(Text, default='')
    fastest_word_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    easy_bot_wins: Mapped[int] = mapped_column(Integer, default=0)
    medium_bot_wins: Mapped[int] = mapped_column(Integer, default=0)
    hard_bot_wins: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Rating(Base):
    __tablename__ = 'ratings'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), unique=True)
    value: Mapped[int] = mapped_column(Integer, default=0)
    deviation: Mapped[int] = mapped_column(Integer, default=350)
    volatility: Mapped[str] = mapped_column(String(16), default='0.06')


class Match(Base):
    __tablename__ = 'matches'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(32), default='duel')
    dictionary_pack: Mapped[str] = mapped_column(String(32), default='basic')
    winner_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    winner_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    winner_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_stake: Mapped[int] = mapped_column(Integer, default=0)
    second_stake: Mapped[int] = mapped_column(Integer, default=0)
    first_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    second_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    median_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    winner_payout: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    participants: Mapped[list['MatchParticipant']] = relationship(back_populates='match')


class MatchParticipant(Base):
    __tablename__ = 'match_participants'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey('matches.id'))
    user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    participant_ref: Mapped[str] = mapped_column(String(64))
    participant_name: Mapped[str] = mapped_column(String(64), default='')
    participant_type: Mapped[str] = mapped_column(String(16), default='human')
    score: Mapped[int] = mapped_column(Integer, default=0)

    match: Mapped[Match] = relationship(back_populates='participants')


class Appeal(Base):
    __tablename__ = 'appeals'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey('matches.id'))
    player_ref: Mapped[str] = mapped_column(String(64))
    word: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DictionaryWord(Base):
    __tablename__ = 'dictionary_words'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pack: Mapped[str] = mapped_column(String(32), index=True)
    word: Mapped[str] = mapped_column(String(64), index=True)
    tags: Mapped[str] = mapped_column(String(128), default='')
