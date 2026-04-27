from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import random
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import Base, SessionLocal, engine, get_db
from app.game_session import GameSession
from app.local_redis import LocalRedis
from app.models import DictionaryWord, Match, Rating, User
from app.repositories.core import AppealRepository, MatchRepository, UserRepository
from app.services.bot import BOTS, BotService
from app.services.dictionary_loader import load_basic_words
from app.services.matchmaking import MatchmakingService
from app.services.rating import RatingService, RatingSnapshot
from app.services.scoring import calculate_score, calculate_score_details
from app.validator import WordValidator
from app.ws.session_manager import SessionManager

app = FastAPI(title=settings.app_name)
app.mount('/static', StaticFiles(directory='static'), name='static')
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

def _build_redis_client() -> Redis | LocalRedis:
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    return client


redis_client: Redis | LocalRedis = _build_redis_client()
manager = SessionManager()
user_repo = UserRepository()
match_repo = MatchRepository()
appeal_repo = AppealRepository()
rating_service = RatingService()
matchmaking = MatchmakingService(redis_client)

packs_path = Path('app/data/packs.json')
raw_packs = json.loads(packs_path.read_text())
PACKS: dict[str, set[str]] = {
    'basic': load_basic_words(limit=3000),
    'slang': {w.lower().strip().replace('ё', 'е') for w in raw_packs.get('slang', [])},
}
BASIC_WORDS_BY_LETTER: dict[str, list[str]] = {}
for _word in PACKS['basic']:
    BASIC_WORDS_BY_LETTER.setdefault(_word[0], []).append(_word)
SUPPORTED_BOT_LETTERS = tuple(sorted([letter for letter, words in BASIC_WORDS_BY_LETTER.items() if len(words) >= 5]))
if not SUPPORTED_BOT_LETTERS:
    SUPPORTED_BOT_LETTERS = tuple(sorted(BASIC_WORDS_BY_LETTER.keys()))
validator = WordValidator(dictionary_packs=PACKS)
bot_service = BotService(words=sorted(set().union(*PACKS.values())))
templates = Jinja2Templates(directory='templates')
TURN_SECONDS = 17
QUEUE_BOT_FALLBACK_SECONDS = 30
STARTING_COINS = 100
DAILY_REWARD_COINS = 100
FIXED_PVP_STAKES = {50, 100, 150}
SUPPORTED_BOT_LEVELS = ('easy', 'medium', 'hard')
BOT_RESPONSE_DELAY_MIN_SECONDS = 3
BOT_RESPONSE_DELAY_MAX_SECONDS = 5
RUSSIAN_START_LETTERS = SUPPORTED_BOT_LETTERS
ADMIN_LOGIN = 'andru'
SHOP_ITEMS: dict[str, dict[str, Any]] = {
    'dict_science_basic': {
        'title': 'Расширение словаря: Наука I',
        'cost': 40,
        'topic': 'science',
        'grant_words': 5,
    },
    'dict_science_pro': {
        'title': 'Расширение словаря: Наука II',
        'cost': 80,
        'topic': 'science',
        'grant_words': 10,
    },
    'dict_zoology_basic': {
        'title': 'Расширение словаря: Зоология I',
        'cost': 50,
        'topic': 'zoology',
        'grant_words': 10,
    },
}
SHOP_TOPIC_POOLS: dict[str, set[str]] = {
    'science': {
        'квант', 'атом', 'реактор', 'нейтрон', 'протон', 'электрон', 'коллайдер', 'гипотеза', 'теорема',
        'интеграл', 'диффузия', 'молекула', 'лаборатория', 'спектрометр', 'гравитация', 'термодинамика',
    },
    'zoology': {
        'дельфин', 'ламантин', 'барсук', 'анаконда', 'пингвин', 'медоед', 'трилобит', 'тукан', 'кондор',
        'ящерица', 'выдра', 'медуза', 'каракатица', 'орнитолог', 'зоолог', 'герпетолог',
    },
}


def _csv_to_set(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item for item in (part.strip().lower() for part in value.split(',')) if item}


def _set_to_csv(values: set[str]) -> str:
    return ','.join(sorted(values))


def _csv_to_counter(value: str | None) -> dict[str, int]:
    result: dict[str, int] = {}
    if not value:
        return result
    for chunk in value.split(','):
        if ':' not in chunk:
            continue
        key, raw = chunk.split(':', 1)
        key = key.strip()
        if not key:
            continue
        try:
            result[key] = int(raw)
        except ValueError:
            continue
    return result


def _counter_to_csv(values: dict[str, int]) -> str:
    parts = [f'{k}:{v}' for k, v in sorted(values.items()) if v > 0]
    return ','.join(parts)


class StartRequest(BaseModel):
    username: str | None = None
    user_id: int | None = None
    dictionary_pack: str = 'basic'
    mode: str = 'bot'
    bot_level: str = 'medium'
    stake_tokens: int = 0


class WordSubmit(BaseModel):
    word: str
    response_seconds: float


class AppealRequest(BaseModel):
    match_id: int
    player_ref: str
    word: str
    reason: str


class AuthRequest(BaseModel):
    login: str
    password: str
    nickname: str | None = None


class ProfileUpdateRequest(BaseModel):
    login: str | None = None
    nickname: str | None = None
    current_password: str | None = None
    password: str | None = None


class AdminAdjustRequest(BaseModel):
    admin_user_id: int
    target_user_id: int
    add_tokens: int = 0
    add_points: int = 0


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 120_000)
    return f'pbkdf2_sha256${salt}${digest.hex()}'


def _verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        algorithm, salt, expected = stored_hash.split('$', 2)
    except ValueError:
        return False
    if algorithm != 'pbkdf2_sha256':
        return False
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 120_000)
    return hmac.compare_digest(digest.hex(), expected)


def _is_admin_user(user: User | None) -> bool:
    if user is None:
        return False
    return (user.login or user.username).strip().lower() == ADMIN_LOGIN


def _achievement_payload(user: User) -> list[dict[str, Any]]:
    fast_progress = None
    if user.fastest_word_seconds is not None:
        fast_progress = round(float(user.fastest_word_seconds), 2)
    achievements = [
        {
            'id': 'fast_hands',
            'title': 'Быстрые руки',
            'description': 'Набрать слово за одну секунду.',
            'unlocked': user.fastest_word_seconds is not None and user.fastest_word_seconds <= 1,
            'progress': fast_progress,
            'target': 1,
        },
        {
            'id': 'money',
            'title': 'При деньгах',
            'description': 'Набрать 1000 монет.',
            'unlocked': int(user.coins or 0) >= 1000,
            'progress': int(user.coins or 0),
            'target': 1000,
        },
        {
            'id': 'tryharder',
            'title': 'Трайхардер',
            'description': 'Победить сложного бота.',
            'unlocked': int(user.hard_bot_wins or 0) > 0,
            'progress': int(user.hard_bot_wins or 0),
            'target': 1,
        },
        {
            'id': 'not_given',
            'title': 'И не такое выдавали',
            'description': 'Победить среднего бота.',
            'unlocked': int(user.medium_bot_wins or 0) > 0,
            'progress': int(user.medium_bot_wins or 0),
            'target': 1,
        },
        {
            'id': 'easy_mode',
            'title': 'Легкотня',
            'description': 'Победить начального бота.',
            'unlocked': int(user.easy_bot_wins or 0) > 0,
            'progress': int(user.easy_bot_wins or 0),
            'target': 1,
        },
    ]
    return achievements


def _profile_payload(user: User, total_score: int = 0, arena: str = 'Arena I (0+)') -> dict[str, Any]:
    now = datetime.utcnow()
    next_claim_at = (
        user.last_daily_claim_at + timedelta(days=1)
        if user.last_daily_claim_at is not None
        else now
    )
    daily_available = user.last_daily_claim_at is None or now >= next_claim_at
    custom_words = _csv_to_set(user.custom_words)
    unlocked_topics = _csv_to_set(user.unlocked_topics)
    purchase_stats = _csv_to_counter(user.purchase_stats)
    purchases = [
        {'item_id': item_id, 'title': SHOP_ITEMS[item_id]['title'], 'count': count}
        for item_id, count in purchase_stats.items()
        if item_id in SHOP_ITEMS and count > 0
    ]
    return {
        'id': user.id,
        'public_id': user.public_id,
        'login': user.login or user.username,
        'nickname': user.nickname or user.username,
        'username': user.username,
        'is_admin': (user.login or user.username).strip().lower() == ADMIN_LOGIN,
        'total_score': max(0, int(total_score)),
        'arena': arena,
        'coins': int(user.coins or 0),
        'daily_reward': {
            'amount': DAILY_REWARD_COINS,
            'available': daily_available,
            'next_claim_at': next_claim_at.isoformat(),
        },
        'custom_word_count': len(custom_words),
        'custom_words_preview': sorted(custom_words)[:60],
        'unlocked_topics': sorted(unlocked_topics),
        'purchases': purchases,
        'fastest_word_seconds': user.fastest_word_seconds,
        'bot_wins': {
            'easy': int(user.easy_bot_wins or 0),
            'medium': int(user.medium_bot_wins or 0),
            'hard': int(user.hard_bot_wins or 0),
        },
        'achievements': _achievement_payload(user),
}


def _user_id_from_ref(player_ref: str) -> int | None:
    if not player_ref.startswith('user_'):
        return None
    raw_id = player_ref.replace('user_', '', 1)
    return int(raw_id) if raw_id.isdigit() else None


async def _record_word_stats(db: AsyncSession, player_ref: str, score: int, response_seconds: float) -> None:
    user_id = _user_id_from_ref(player_ref)
    if user_id is None:
        return
    await user_repo.add_word_stats(db, user_id, score, response_seconds)


async def _rating_value(db: AsyncSession, user_id: int) -> int:
    rating = (await db.execute(select(Rating).where(Rating.user_id == user_id))).scalar_one_or_none()
    if rating is None:
        rating = Rating(user_id=user_id, value=0)
        db.add(rating)
        await db.commit()
        await db.refresh(rating)
    return rating.value


async def _profile_payload_for_user(db: AsyncSession, user: User) -> dict[str, Any]:
    total_score = await match_repo.user_total_score(db, user.id)
    arena = match_repo.arena_for_score(total_score)
    return _profile_payload(user, total_score=total_score, arena=arena)


def _finish_reason_text(reason: str, loser_name: str = '') -> str:
    mapping = {
        'surrender': f'{loser_name or "Соперник"} сдался. Матч завершён.',
        'timeout': f'{loser_name or "Соперник"} не уложился в таймер.',
        'bot_failed_random': 'Бот не смог продолжить игру.',
        'bot_failed_word': 'Бот не нашёл подходящее слово.',
    }
    return mapping.get(reason, reason)


async def _start_match(payload: StartRequest, db: AsyncSession) -> dict[str, Any]:
    user = await user_repo.get_by_id(db, payload.user_id) if payload.user_id else None
    if user is None:
        username = (payload.username or '').strip()
        if not username:
            raise HTTPException(status_code=400, detail='username_or_user_id_required')
        user = await user_repo.get_or_create(db, username)
    bot_level = payload.bot_level if payload.bot_level in SUPPORTED_BOT_LEVELS else 'medium'
    player_ref = f'user_{user.id}'
    bot_ref = f'bot_{bot_level}'
    session_id = f'm_{int(time.time() * 1000)}'

    session = GameSession(redis_client, session_id)
    state = await session.bootstrap(
        player_id=player_ref,
        player_name=user.nickname or user.username,
        dictionary_pack=payload.dictionary_pack,
        mode=payload.mode,
        bot_id=bot_ref,
        bot_name=BOTS[bot_level].name,
        initial_letter=random.choice(RUSSIAN_START_LETTERS),
    )
    state['turn_deadline'] = state['turn_started_at'] + TURN_SECONDS
    state['bot_word_pool'] = _build_bot_word_pool(bot_level)
    state['bot_success_count'] = 0
    state['bot_processing'] = False
    state['bot_last_word'] = None
    state['extra_words'] = {player_ref: sorted(_csv_to_set(user.custom_words))}
    await session.save(state)

    match = await match_repo.create(db, payload.mode, payload.dictionary_pack)
    await match_repo.add_participant(db, match.id, player_ref, user.username, 'human', user_id=user.id)
    await match_repo.add_participant(db, match.id, state['participants'][1]['id'], state['participants'][1]['name'], 'bot')
    await redis_client.set(f'session:match:{session_id}', str(match.id))

    return {
        'session_id': session_id,
        'player_ref': player_ref,
        'match_id': match.id,
        'events': [
            {'type': 'match_found', 'payload': {'opponent_type': 'bot'}},
            {'type': 'match_started', 'payload': state},
        ],
    }


async def _start_human_match(
    db: AsyncSession,
    first_ref: str,
    first_name: str,
    second_ref: str,
    second_name: str,
    first_user_id: int | None = None,
    second_user_id: int | None = None,
    dictionary_pack: str = 'basic',
    first_stake: int = 0,
    second_stake: int = 0,
) -> dict[str, Any]:
    median_multiplier = 1.0
    if first_stake != second_stake:
        raise HTTPException(status_code=400, detail='stake_mismatch')

    if first_user_id is not None and second_user_id is not None and (first_stake > 0 or second_stake > 0):
        first_user = await user_repo.get_by_id(db, first_user_id)
        second_user = await user_repo.get_by_id(db, second_user_id)
        if not first_user or not second_user:
            raise HTTPException(status_code=404, detail='profile_not_found')
        if int(first_user.coins or 0) < first_stake or int(second_user.coins or 0) < second_stake:
            raise HTTPException(status_code=400, detail='insufficient_coins')
        first_user.coins = int(first_user.coins or 0) - first_stake
        second_user.coins = int(second_user.coins or 0) - second_stake
        await db.commit()

    session_id = f'm_{int(time.time() * 1000)}'
    session = GameSession(redis_client, session_id)
    state = await session.bootstrap_humans(
        first_id=first_ref,
        first_name=first_name,
        second_id=second_ref,
        second_name=second_name,
        dictionary_pack=dictionary_pack,
        initial_letter=random.choice(RUSSIAN_START_LETTERS),
    )
    state['turn_deadline'] = state['turn_started_at'] + TURN_SECONDS
    state['extra_words'] = {}
    if first_user_id is not None:
        first_user = await user_repo.get_by_id(db, first_user_id)
        if first_user is not None:
            state['extra_words'][first_ref] = sorted(_csv_to_set(first_user.custom_words))
    if second_user_id is not None:
        second_user = await user_repo.get_by_id(db, second_user_id)
        if second_user is not None:
            state['extra_words'][second_ref] = sorted(_csv_to_set(second_user.custom_words))
    await session.save(state)

    match = await match_repo.create(
        db,
        'pvp',
        dictionary_pack,
        first_stake=first_stake,
        second_stake=second_stake,
        first_multiplier=1.0,
        second_multiplier=1.0,
        median_multiplier=median_multiplier,
    )
    await match_repo.add_participant(db, match.id, first_ref, first_name, 'human', user_id=first_user_id)
    await match_repo.add_participant(db, match.id, second_ref, second_name, 'human', user_id=second_user_id)
    await redis_client.set(f'session:match:{session_id}', str(match.id))
    await redis_client.set(f'mm:player_session:{first_ref}', session_id)
    await redis_client.set(f'mm:player_session:{second_ref}', session_id)
    await _redis_delete(
        f'mm:queued_at:{first_ref}',
        f'mm:queued_at:{second_ref}',
        f'mm:queued_pack:{first_ref}',
        f'mm:queued_pack:{second_ref}',
        f'mm:queued_stake:{first_ref}',
        f'mm:queued_stake:{second_ref}',
    )
    return {'session_id': session_id, 'match_id': match.id, 'median_multiplier': median_multiplier}


async def _redis_delete(*keys: str) -> None:
    if not keys:
        return
    try:
        await redis_client.delete(*keys)
    except Exception:
        # local fallback may have reduced API surface in older runs
        for key in keys:
            try:
                await redis_client.set(key, '')
            except Exception:
                pass


@app.on_event('startup')
async def startup() -> None:
    global redis_client, matchmaking

    try:
        await redis_client.ping()
    except RedisError:
        redis_client = LocalRedis()
        matchmaking = MatchmakingService(redis_client)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_sqlite_compat_migrations(conn)


@app.get('/health')
async def health() -> dict[str, str]:
    return {'status': 'ok'}


@app.get('/auth/login', response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        'auth.html',
        {
            'title': 'Вход в аккаунт',
            'action': '/auth/login',
            'is_register': False,
            'button_text': 'Войти',
            'error': error,
        },
    )


@app.post('/auth/login')
async def login_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    content_type = request.headers.get('content-type', '')
    is_json = 'application/json' in content_type

    if is_json:
        payload = AuthRequest(**(await request.json()))
        user = await user_repo.get_by_login(db, payload.login)
        if user is None or not _verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail='invalid_login_or_password')
        return await _profile_payload_for_user(db, user)

    form = await request.form()
    payload = AuthRequest(login=str(form.get('login', '')), password=str(form.get('password', '')))
    try:
        user = await user_repo.get_by_login(db, payload.login)
        if user is None or not _verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail='invalid_login_or_password')
        return RedirectResponse(url=f'/home?user_id={user.id}', status_code=303)
    except HTTPException as e:
        return RedirectResponse(url=f'/?error={e.detail}', status_code=303)


@app.get('/auth/register', response_class=HTMLResponse)
async def register_page(request: Request, error: str | None = None) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        'auth.html',
        {
            'title': 'Регистрация',
            'action': '/auth/register',
            'is_register': True,
            'button_text': 'Зарегистрироваться',
            'error': error,
        },
    )


@app.post('/auth/register')
async def register_submit(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    content_type = request.headers.get('content-type', '')
    is_json = 'application/json' in content_type

    raw_payload: dict[str, Any]
    if is_json:
        raw_payload = await request.json()
    else:
        form = await request.form()
        raw_payload = {'login': form.get('login', ''), 'password': form.get('password', ''), 'nickname': form.get('nickname', '')}

    payload = AuthRequest(**raw_payload)
    clean_login = payload.login.strip().lower()
    clean_password = payload.password.strip()
    clean_nickname = (payload.nickname or '').strip()
    if len(clean_login) < 3:
        if is_json:
            raise HTTPException(status_code=400, detail='login_too_short')
        return RedirectResponse(url='/?error=login_too_short', status_code=303)
    if len(clean_password) < 4:
        if is_json:
            raise HTTPException(status_code=400, detail='password_too_short')
        return RedirectResponse(url='/?error=password_too_short', status_code=303)
    if len(clean_nickname) < 2:
        if is_json:
            raise HTTPException(status_code=400, detail='nickname_too_short')
        return RedirectResponse(url='/?error=nickname_too_short', status_code=303)
    if await user_repo.get_by_login(db, clean_login):
        if is_json:
            raise HTTPException(status_code=409, detail='login_taken')
        return RedirectResponse(url='/?error=login_taken', status_code=303)

    user = await user_repo.create_account(db, clean_login, _hash_password(clean_password), clean_nickname)
    if is_json:
        return await _profile_payload_for_user(db, user)
    return RedirectResponse(url=f'/home?user_id={user.id}', status_code=303)


@app.get('/admin', response_class=HTMLResponse)
async def admin_page(
    request: Request,
    user_id: int | None = None,
    error: str | None = None,
    success: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    if user_id is None:
        return RedirectResponse(url='/?error=admin_auth_required', status_code=303)
    admin_user = await user_repo.get_by_id(db, user_id)
    if not _is_admin_user(admin_user):
        return RedirectResponse(url=f'/home?user_id={user_id}&error=admin_forbidden', status_code=303)
    users = (await db.execute(select(User).order_by(User.login.asc()))).scalars().all()
    return templates.TemplateResponse(
        request,
        'admin.html',
        {'error': error, 'success': success, 'admin_user': admin_user, 'users': users},
    )


@app.post('/admin')
async def admin_adjust(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    form = await request.form()
    action = str(form.get('action', 'apply'))
    payload = AdminAdjustRequest(
        admin_user_id=int(form.get('admin_user_id', 0) or 0),
        target_user_id=int(form.get('target_user_id', 0) or 0),
        add_tokens=int(form.get('add_tokens', 0) or 0),
        add_points=int(form.get('add_points', 0) or 0),
    )
    admin_user = await user_repo.get_by_id(db, payload.admin_user_id)
    if not _is_admin_user(admin_user):
        return RedirectResponse(url='/?error=admin_forbidden', status_code=303)
    user = await user_repo.get_by_id(db, payload.target_user_id)
    if user is None:
        return RedirectResponse(url=f'/admin?user_id={payload.admin_user_id}&error=target_user_not_found', status_code=303)
    if action == 'delete':
        if user.id == payload.admin_user_id:
            return RedirectResponse(url=f'/admin?user_id={payload.admin_user_id}&error=cannot_delete_self', status_code=303)
        if str(form.get('confirm_delete', '')).lower() != 'yes':
            return RedirectResponse(url=f'/admin?user_id={payload.admin_user_id}&error=delete_not_confirmed', status_code=303)
        await db.execute(update(Match).where(Match.winner_id == user.id).values(winner_id=None))
        await db.execute(delete(Rating).where(Rating.user_id == user.id))
        await db.execute(text('DELETE FROM match_participants WHERE user_id = :uid'), {'uid': user.id})
        await db.delete(user)
        await db.commit()
        return RedirectResponse(url=f'/admin?user_id={payload.admin_user_id}&success=deleted', status_code=303)

    if payload.add_tokens:
        user.coins = int(user.coins or 0) + int(payload.add_tokens)
    if payload.add_points > 0:
        admin_match = await match_repo.create(db, mode='bot', dictionary_pack='basic')
        await match_repo.add_participant(
            db,
            admin_match.id,
            participant_ref=f'user_{user.id}',
            participant_name=user.nickname or user.login or user.username,
            participant_type='human',
            user_id=user.id,
            score=int(payload.add_points),
        )
        await match_repo.add_participant(
            db,
            admin_match.id,
            participant_ref='bot_admin',
            participant_name='AdminBot',
            participant_type='bot',
            score=0,
        )
        await match_repo.set_scores_and_winner(
            db,
            admin_match.id,
            scores={f'user_{user.id}': int(payload.add_points), 'bot_admin': 0},
            winner_ref=f'user_{user.id}',
            winner_name=user.nickname or user.login or user.username,
        )

    await db.commit()
    return RedirectResponse(url=f'/admin?user_id={payload.admin_user_id}&success=updated', status_code=303)


@app.get('/profile/id/{user_id}')
async def get_profile_by_id(user_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    user = await user_repo.get_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail='profile_not_found')
    return await _profile_payload_for_user(db, user)


@app.put('/profile/id/{user_id}')
async def update_profile(
    user_id: int,
    payload: ProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user = await user_repo.get_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail='profile_not_found')

    next_login = payload.login.strip().lower() if payload.login is not None else None
    next_nickname = payload.nickname.strip() if payload.nickname is not None else None
    next_hash = None

    if next_login is not None:
        if len(next_login) < 3:
            raise HTTPException(status_code=400, detail='login_too_short')
        existing = await user_repo.get_by_login(db, next_login)
        if existing is not None and existing.id != user.id:
            raise HTTPException(status_code=409, detail='login_taken')

    if next_nickname is not None and len(next_nickname) < 2:
        raise HTTPException(status_code=400, detail='nickname_too_short')

    if payload.password is not None:
        if len(payload.password.strip()) < 4:
            raise HTTPException(status_code=400, detail='password_too_short')
        if not _verify_password(payload.current_password or '', user.password_hash):
            raise HTTPException(status_code=401, detail='current_password_invalid')
        next_hash = _hash_password(payload.password.strip())

    updated = await user_repo.update_account(db, user, next_login, next_nickname, next_hash)
    return await _profile_payload_for_user(db, updated)


@app.get('/', response_class=HTMLResponse)
async def home_page(request: Request, error: str | None = None, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        'auth.html',
        {
            'title': 'Вход в аккаунт',
            'action': '/auth/login',
            'is_register': False,
            'button_text': 'Войти',
            'error': error,
        },
    )


@app.get('/home', response_class=HTMLResponse)
async def matchmaking_page(
    request: Request,
    user_id: int | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    if user_id is None:
        return RedirectResponse(url='/', status_code=303)

    user = await user_repo.get_by_id(db, user_id)
    if user is None:
        return RedirectResponse(url='/?error=profile_not_found', status_code=303)

    pvp_leaders = await match_repo.leaderboard_by_match_mode(db, mode='pvp', limit=20)
    bot_leaders = await match_repo.leaderboard_by_match_mode(db, mode='bot', limit=20)
    profile_data = await _profile_payload_for_user(db, user)
    return templates.TemplateResponse(
        request,
        'index.html',
        {
            'packs': sorted(PACKS.keys()),
            'bot_levels': list(SUPPORTED_BOT_LEVELS),
            'pvp_leaders': pvp_leaders,
            'bot_leaders': bot_leaders,
            'profile': profile_data,
            'error': error,
        },
    )


@app.get('/profile/{user_id}', response_class=HTMLResponse)
async def profile_page(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = await user_repo.get_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail='profile_not_found')
    profile_data = await _profile_payload_for_user(db, user)
    return templates.TemplateResponse(
        request,
        'profile.html',
        {
            'profile': profile_data,
            'home_link': f'/home?user_id={user.id}',
            'request': request,
        },
    )


@app.get('/profile/{user_id}/vocabulary', response_class=HTMLResponse)
async def vocabulary_page(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = await user_repo.get_by_id(db, user_id)
    if user is None:
        return RedirectResponse(url='/?error=profile_not_found', status_code=303)
    profile_data = await _profile_payload_for_user(db, user)
    words = sorted(_csv_to_set(user.custom_words))
    return templates.TemplateResponse(
        request,
        'vocabulary.html',
        {
            'profile': profile_data,
            'words': words,
            'home_link': f'/home?user_id={user.id}',
        },
    )


@app.get('/shop', response_class=HTMLResponse)
async def shop_page(
    request: Request,
    user_id: int | None = None,
    error: str | None = None,
    success: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    if user_id is None:
        return RedirectResponse(url='/', status_code=303)
    user = await user_repo.get_by_id(db, user_id)
    if user is None:
        return RedirectResponse(url='/?error=profile_not_found', status_code=303)
    profile_data = await _profile_payload_for_user(db, user)
    return templates.TemplateResponse(
        request,
        'shop.html',
        {
            'request': request,
            'profile': profile_data,
            'items': SHOP_ITEMS,
            'error': error,
            'success': success,
            'home_link': f'/home?user_id={user.id}',
        },
    )


@app.post('/shop/buy')
async def shop_buy_item(
    user_id: int = Form(...),
    item_id: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    user = await user_repo.get_by_id(db, user_id)
    if user is None:
        return RedirectResponse(url='/?error=profile_not_found', status_code=303)
    item = SHOP_ITEMS.get(item_id)
    if item is None:
        return RedirectResponse(url=f'/shop?user_id={user_id}&error=item_not_found', status_code=303)
    cost = int(item['cost'])
    if int(user.coins or 0) < cost:
        return RedirectResponse(url=f'/shop?user_id={user_id}&error=insufficient_coins', status_code=303)

    topic = str(item['topic'])
    pool = sorted(SHOP_TOPIC_POOLS.get(topic, set()))
    grant_words = max(1, int(item.get('grant_words', 10)))
    if not pool:
        return RedirectResponse(url=f'/shop?user_id={user_id}&error=topic_pool_empty', status_code=303)

    user.coins = int(user.coins or 0) - cost
    user_words = _csv_to_set(user.custom_words)
    user_topics = _csv_to_set(user.unlocked_topics)
    available = [w for w in pool if w not in user_words]
    if len(available) >= grant_words:
        granted = set(random.sample(available, k=grant_words))
    else:
        granted = set(available)
        while len(granted) < grant_words:
            granted.add(random.choice(pool))
    user_words.update(granted)
    user_topics.add(topic)
    stats = _csv_to_counter(user.purchase_stats)
    stats[item_id] = int(stats.get(item_id, 0)) + 1
    user.custom_words = _set_to_csv(user_words)
    user.unlocked_topics = _set_to_csv(user_topics)
    user.purchase_stats = _counter_to_csv(stats)
    await db.commit()
    return RedirectResponse(url=f'/shop?user_id={user_id}&success=item_bought', status_code=303)


@app.get('/profile/{user_id}/achievements', response_class=HTMLResponse)
async def achievements_page(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    user = await user_repo.get_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail='profile_not_found')
    profile_data = await _profile_payload_for_user(db, user)
    return templates.TemplateResponse(
        request,
        'achievements.html',
        {
            'profile': profile_data,
            'request': request,
        },
    )


@app.post('/profile/{user_id}')
async def update_profile_page(
    request: Request,
    user_id: int,
    login: str | None = Form(None),
    nickname: str | None = Form(None),
    current_password: str | None = Form(None),
    password: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    try:
        payload = ProfileUpdateRequest(
            login=login,
            nickname=nickname,
            current_password=current_password,
            password=password,
        )
        await update_profile(user_id, payload, db)
        return RedirectResponse(url=f'/profile/{user_id}?success=1', status_code=303)
    except HTTPException as e:
        error_msg = e.detail
        return RedirectResponse(url=f'/profile/{user_id}?error={error_msg}', status_code=303)


@app.post('/profile/{user_id}/daily-reward')
async def claim_daily_reward_page(user_id: int, db: AsyncSession = Depends(get_db)) -> RedirectResponse:
    claimed, _user = await user_repo.claim_daily_reward(db, user_id, amount=DAILY_REWARD_COINS)
    if claimed:
        return RedirectResponse(url=f'/profile/{user_id}?success=daily_reward', status_code=303)
    return RedirectResponse(url=f'/profile/{user_id}?error=daily_reward_not_ready', status_code=303)


@app.post('/play-profile')
async def play_with_profile(
    user_id: int = Form(...),
    dictionary_pack: str = Form('basic'),
    game_mode: str = Form('bot'),
    bot_level: str = Form('medium'),
    stake_tokens: int = Form(0),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    user = await user_repo.get_by_id(db, user_id)
    if user is None:
        return RedirectResponse(url='/?error=profile_not_found', status_code=303)

    player_name = user.nickname or user.login or user.username
    player_ref = f'user_{user.id}'
    stake_tokens = max(0, int(stake_tokens or 0))

    if game_mode == 'bot':
        stake_tokens = 0
        payload = StartRequest(user_id=user.id, username=player_name, dictionary_pack=dictionary_pack, mode='bot', bot_level=bot_level)
        started = await _start_match(payload, db)
        return RedirectResponse(url=f"/match/{started['session_id']}/{started['player_ref']}", status_code=303)

    if stake_tokens not in FIXED_PVP_STAKES:
        return RedirectResponse(url=f'/home?user_id={user.id}&error=invalid_stake', status_code=303)
    if stake_tokens > int(user.coins or 0):
        return RedirectResponse(url=f'/home?user_id={user.id}&error=insufficient_coins', status_code=303)

    assignment = await matchmaking.find_or_create(player_ref, player_name, desired_stake=stake_tokens)
    if assignment.opponent_type == 'waiting':
        await redis_client.set(f'mm:queued_at:{player_ref}', str(int(time.time())))
        await redis_client.set(f'mm:queued_pack:{player_ref}', dictionary_pack)
        await redis_client.set(f'mm:queued_stake:{player_ref}', str(stake_tokens))
        return RedirectResponse(url=f'/waiting/{player_ref}', status_code=303)

    first_ref = assignment.opponent_id or ''
    first_user_id = _user_id_from_ref(first_ref)
    first_stake_raw = await redis_client.get(f'mm:queued_stake:{first_ref}') if first_ref else None
    first_stake = int(first_stake_raw) if str(first_stake_raw).isdigit() else 0

    started = await _start_human_match(
        db=db,
        first_ref=first_ref,
        first_name=assignment.opponent_name or (assignment.opponent_id or 'Player 1'),
        second_ref=player_ref,
        second_name=player_name,
        first_user_id=first_user_id,
        second_user_id=user.id,
        dictionary_pack=dictionary_pack,
        first_stake=first_stake,
        second_stake=stake_tokens,
    )
    return RedirectResponse(url=f"/match/{started['session_id']}/{player_ref}", status_code=303)


@app.post('/play')
async def play(
    username: str = Form(...),
    dictionary_pack: str = Form('basic'),
    game_mode: str = Form('pvp'),
    bot_level: str = Form('medium'),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    clean_name = username.strip()
    if game_mode == 'bot':
        payload = StartRequest(username=clean_name, dictionary_pack=dictionary_pack, mode='bot', bot_level=bot_level)
        started = await _start_match(payload, db)
        return RedirectResponse(url=f"/match/{started['session_id']}/{started['player_ref']}", status_code=303)

    user = await user_repo.get_or_create(db, clean_name)
    player_ref = f'user_{user.id}'
    assignment = await matchmaking.find_or_create(player_ref, clean_name)

    if assignment.opponent_type == 'waiting':
        await redis_client.set(f'mm:queued_at:{player_ref}', str(int(time.time())))
        await redis_client.set(f'mm:queued_pack:{player_ref}', dictionary_pack)
        return RedirectResponse(url=f'/waiting/{player_ref}', status_code=303)

    started = await _start_human_match(
        db=db,
        first_ref=assignment.opponent_id or '',
        first_name=assignment.opponent_name or (assignment.opponent_id or 'Player 1'),
        second_ref=player_ref,
        second_name=clean_name,
        dictionary_pack=dictionary_pack,
    )
    return RedirectResponse(url=f"/match/{started['session_id']}/{player_ref}", status_code=303)


@app.get('/waiting/{player_ref}', response_class=HTMLResponse)
async def waiting_page(request: Request, player_ref: str) -> HTMLResponse:
    raw_stake = await redis_client.get(f'mm:queued_stake:{player_ref}')
    queued_stake = int(raw_stake) if str(raw_stake).isdigit() else 0
    return templates.TemplateResponse(request, 'waiting.html', {'player_ref': player_ref, 'queued_stake': queued_stake})


async def _try_match_waiting_player(player_ref: str, db: AsyncSession) -> str | None:
    current_session = await redis_client.get(f'mm:player_session:{player_ref}')
    if current_session:
        return str(current_session)
    own_stake_raw = await redis_client.get(f'mm:queued_stake:{player_ref}')
    own_stake = int(own_stake_raw) if str(own_stake_raw).isdigit() else 0
    if own_stake <= 0:
        return None
    own_pack = str(await redis_client.get(f'mm:queued_pack:{player_ref}') or 'basic')

    queue_rows = await redis_client.lrange('mm:queue', 0, -1)
    candidate_ref = None
    candidate_name = None
    own_row = None
    candidate_row = None
    for row in queue_rows:
        queued_ref, queued_name = MatchmakingService._decode(row)
        if queued_ref == player_ref and own_row is None:
            own_row = row
        if not queued_ref or queued_ref == player_ref:
            continue
        queued_at = await redis_client.get(f'mm:queued_at:{queued_ref}')
        if not queued_at:
            continue
        queued_stake_raw = await redis_client.get(f'mm:queued_stake:{queued_ref}')
        queued_stake = int(queued_stake_raw) if str(queued_stake_raw).isdigit() else 0
        if queued_stake != own_stake:
            continue
        candidate_ref = queued_ref
        candidate_name = queued_name
        candidate_row = row
        break
    if candidate_ref is None:
        return None

    own_user_id = _user_id_from_ref(player_ref)
    opponent_user_id = _user_id_from_ref(candidate_ref)
    own_user = await user_repo.get_by_id(db, own_user_id) if own_user_id is not None else None
    opponent_user = await user_repo.get_by_id(db, opponent_user_id) if opponent_user_id is not None else None
    if own_user is None or opponent_user is None:
        return None

    own_name = own_user.nickname or own_user.login or own_user.username
    opponent_name = candidate_name or opponent_user.nickname or opponent_user.login or opponent_user.username
    started = await _start_human_match(
        db=db,
        first_ref=candidate_ref,
        first_name=opponent_name,
        second_ref=player_ref,
        second_name=own_name,
        first_user_id=opponent_user.id,
        second_user_id=own_user.id,
        dictionary_pack=own_pack,
        first_stake=own_stake,
        second_stake=own_stake,
    )
    if own_row:
        await redis_client.lrem('mm:queue', 0, own_row)
    if candidate_row:
        await redis_client.lrem('mm:queue', 0, candidate_row)
    return str(started['session_id'])


@app.get('/matchmaking/status/{player_ref}')
async def matchmaking_status(player_ref: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    session_id = await redis_client.get(f'mm:player_session:{player_ref}')
    if not session_id:
        session_id = await _try_match_waiting_player(player_ref, db)
    if session_id:
        await _redis_delete(
            f'mm:queued_at:{player_ref}',
            f'mm:queued_pack:{player_ref}',
            f'mm:queued_stake:{player_ref}',
        )
        return {'status': 'matched', 'session_id': str(session_id), 'player_ref': player_ref}
    if not session_id:
        queued_at = await redis_client.get(f'mm:queued_at:{player_ref}')
        queued_stake_raw = await redis_client.get(f'mm:queued_stake:{player_ref}')
        queued_stake = int(queued_stake_raw) if str(queued_stake_raw).isdigit() else 0
        queue_rows = await redis_client.lrange('mm:queue', 0, -1)
        has_other_waiting = False
        offer_candidate_ref: str | None = None
        offer_candidate_stake = 0
        for row in queue_rows:
            queued_ref, _ = MatchmakingService._decode(row)
            if not queued_ref or queued_ref == player_ref:
                continue
            queued_other_at = await redis_client.get(f'mm:queued_at:{queued_ref}')
            if not queued_other_at:
                continue
            has_other_waiting = True
            row_stake = await redis_client.get(f'mm:queued_stake:{queued_ref}')
            row_stake_value = int(row_stake) if str(row_stake).isdigit() else 0
            if offer_candidate_ref is None:
                offer_candidate_ref = queued_ref
                offer_candidate_stake = row_stake_value
        now = int(time.time())
        waiting_seconds = max(0, now - int(queued_at)) if queued_at and str(queued_at).isdigit() else 0
        suggestion_ready = 10 <= waiting_seconds < QUEUE_BOT_FALLBACK_SECONDS and has_other_waiting
        fallback_ready = waiting_seconds >= QUEUE_BOT_FALLBACK_SECONDS
        suggested_stake = None
        stake_offer = None
        if suggestion_ready and offer_candidate_ref is not None:
            if queued_stake != offer_candidate_stake and queued_stake > 0 and offer_candidate_stake > 0:
                suggested_stake = min(queued_stake, offer_candidate_stake)
                stake_offer = {
                    'proposed_stake': suggested_stake,
                    'opponent_ref': offer_candidate_ref,
                    'window_ends_in': max(0, QUEUE_BOT_FALLBACK_SECONDS - waiting_seconds),
                    'message': f'В очереди найден игрок с другой ставкой. Предлагаем обоим играть на ставку {suggested_stake}.',
                }
        return {
            'status': 'waiting',
            'waiting_seconds': waiting_seconds,
            'fallback_allowed': fallback_ready,
            'queued_stake': queued_stake,
            'suggested_stake': suggested_stake,
            'has_other_waiting': has_other_waiting,
            'stake_offer': stake_offer,
        }
    return {'status': 'matched', 'session_id': str(session_id), 'player_ref': player_ref}


@app.post('/matchmaking/adjust-stake/{player_ref}')
async def matchmaking_adjust_stake(
    player_ref: str,
    stake: int = Form(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stake_value = int(stake or 0)
    if stake_value not in FIXED_PVP_STAKES:
        return {'status': 'invalid_stake'}
    queued_at = await redis_client.get(f'mm:queued_at:{player_ref}')
    if not queued_at:
        return {'status': 'not_in_queue'}
    await redis_client.set(f'mm:queued_stake:{player_ref}', str(stake_value))
    session_id = await _try_match_waiting_player(player_ref, db)
    if session_id:
        return {'status': 'matched', 'stake': stake_value, 'session_id': session_id, 'player_ref': player_ref}
    return {'status': 'ok', 'stake': stake_value}


@app.post('/matchmaking/fallback-bot/{player_ref}')
async def matchmaking_fallback_to_bot(player_ref: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    user_id_raw = player_ref.replace('user_', '', 1)
    if not user_id_raw.isdigit():
        return {'status': 'invalid_player_ref'}
    user = await db.get(User, int(user_id_raw))
    if user is None:
        return {'status': 'user_not_found'}

    session_id = await redis_client.get(f'mm:player_session:{player_ref}')
    if session_id:
        return {'status': 'already_matched', 'session_id': session_id}

    queued_at = await redis_client.get(f'mm:queued_at:{player_ref}')
    now = int(time.time())
    waiting_seconds = max(0, now - int(queued_at)) if queued_at and str(queued_at).isdigit() else 0
    if waiting_seconds < QUEUE_BOT_FALLBACK_SECONDS:
        return {'status': 'not_ready', 'waiting_seconds': waiting_seconds}

    queued_pack = await redis_client.get(f'mm:queued_pack:{player_ref}') or 'basic'
    await _redis_delete(
        f'mm:queued_at:{player_ref}',
        f'mm:queued_pack:{player_ref}',
        f'mm:queued_stake:{player_ref}',
    )
    started = await _start_match(
        StartRequest(username=user.username, dictionary_pack=str(queued_pack), mode='bot', bot_level='medium'),
        db,
    )
    return {'status': 'started', 'session_id': started['session_id'], 'player_ref': started['player_ref']}


@app.get('/match/{session_id}/{player_ref}', response_class=HTMLResponse)
async def match_page(
    request: Request,
    session_id: str,
    player_ref: str,
    error: str | None = None,
    fx: str | None = None,
    points: int | None = None,
) -> HTMLResponse:
    session = GameSession(redis_client, session_id)
    state = await session.load()
    if state is None:
        return templates.TemplateResponse(
            request,
            'index.html',
            {
                'packs': sorted(PACKS.keys()),
                'bot_levels': list(SUPPORTED_BOT_LEVELS),
                'pvp_leaders': [],
                'bot_leaders': [],
                'error': 'Сессия не найдена',
            },
            status_code=404,
        )

    state = await _resolve_timeout(session_id, session, state)
    home_link = '/home'
    owner_user_id = _user_id_from_ref(player_ref)
    if owner_user_id is not None:
        home_link = f'/home?user_id={owner_user_id}'
    if state.get('status') == 'finished':
        winner_name = ''
        loser_name = ''
        names = {p['id']: p.get('name', p['id']) for p in state['participants']}
        finish_reason = state.get('finish_reason', 'finished')
        if state.get('winner_ref'):
            winner_name = names.get(state['winner_ref'], state['winner_ref'])
            loser_ref = next((pid for pid in state['turn_order'] if pid != state['winner_ref']), '')
            loser_name = names.get(loser_ref, loser_ref)
            finish_reason = _finish_reason_text(finish_reason, loser_name)
        return templates.TemplateResponse(
            request,
            'match.html',
            {
                'session_id': session_id,
                'player_ref': player_ref,
                'state': state,
                'turn_ref': '',
                'turn_name': 'Матч завершен',
                'names': names,
                'turn_seconds': TURN_SECONDS,
                'seconds_left': 0,
                'error': f"Матч завершен: победитель {winner_name or '—'}, проиграл {loser_name or '—'} ({finish_reason})",
                'fx': fx,
                'points': points,
                'home_link': home_link,
            },
        )
    turn_ref = state['turn_order'][state['turn_index']]
    names = {p['id']: p.get('name', p['id']) for p in state['participants']}
    seconds_left = max(0, state['turn_deadline'] - int(time.time()))
    return templates.TemplateResponse(
        request,
        'match.html',
        {
            'session_id': session_id,
            'player_ref': player_ref,
            'state': state,
            'turn_ref': turn_ref,
            'turn_name': names.get(turn_ref, turn_ref),
            'names': names,
            'turn_seconds': TURN_SECONDS,
            'seconds_left': seconds_left,
            'error': error,
            'fx': fx,
            'points': points,
            'home_link': home_link,
        },
    )


@app.post('/match/{session_id}/{player_ref}/submit')
async def match_submit_word(
    session_id: str,
    player_ref: str,
    word: str = Form(...),
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    session = GameSession(redis_client, session_id)
    state = await session.load()
    if state is None:
        return RedirectResponse(url='/?error=session_not_found', status_code=303)
    if state.get('status') == 'finished':
        return RedirectResponse(url=f'/match/{session_id}/{player_ref}', status_code=303)
    if state['turn_order'][state['turn_index']] != player_ref:
        current_ref = state['turn_order'][state['turn_index']]
        participant = next((p for p in state['participants'] if p['id'] == current_ref), None)
        if participant and participant.get('type') == 'bot':
            await _maybe_bot_turn(session_id, session)
        return RedirectResponse(url=f'/match/{session_id}/{player_ref}?error=not_your_turn', status_code=303)

    res = validator.validate(
        word,
        state['current_letter'],
        set(state['used_words']) | set(state.get('used_lemmas', [])),
        dictionary_pack=state['dictionary_pack'],
        extra_words=set(state.get('extra_words', {}).get(player_ref, [])),
    )
    if not res.ok:
        if res.reason in {'word_not_in_dictionary', 'not_in_dictionary'}:
            penalized = await session.apply_penalty(player_ref, penalty=2)
            has_bot_penalty = any(p.get('type') == 'bot' for p in penalized.get('participants', []))
            if has_bot_penalty:
                if background_tasks is not None:
                    background_tasks.add_task(_maybe_bot_turn, session_id, session)
                else:
                    asyncio.create_task(_maybe_bot_turn(session_id, session))
            return RedirectResponse(
                url=f'/match/{session_id}/{player_ref}?error=word_not_in_dictionary_penalty_minus_2',
                status_code=303,
            )
        return RedirectResponse(
            url=f'/match/{session_id}/{player_ref}?error={res.reason}',
            status_code=303,
        )

    normalized = res.normalized_word or word
    has_bot = any(p.get('type') == 'bot' for p in state.get('participants', []))
    next_letter = GameSession._next_letter(normalized)
    spent = max(0.2, min(float(TURN_SECONDS), time.time() - float(state['turn_started_at'])))
    score_info = calculate_score_details(normalized, spent)
    score = score_info.score
    updated = await session.apply_word(player_ref, normalized, score, lemma=validator.normalize(normalized))
    await _record_word_stats(db, player_ref, score, spent)
    if has_bot and next_letter not in SUPPORTED_BOT_LETTERS:
        bot_ref = next((p['id'] for p in updated.get('participants', []) if p.get('type') == 'bot'), '')
        if bot_ref:
            await _finish_session(session, loser_ref=bot_ref, reason=f'bot_no_words_for_letter_{next_letter}')
        return RedirectResponse(
            url=f'/match/{session_id}/{player_ref}?error=bot_no_words_for_letter_{next_letter}',
            status_code=303,
        )
    if has_bot:
        if background_tasks is not None:
            background_tasks.add_task(_maybe_bot_turn, session_id, session)
        else:
            asyncio.create_task(_maybe_bot_turn(session_id, session))
    redirect_url = f'/match/{session_id}/{player_ref}'
    if score_info.rarity_tier in {'rare', 'epic', 'ultra_rare', 'legendary'}:
        redirect_url += f'?fx={score_info.rarity_tier}&points={score}'
    return RedirectResponse(url=redirect_url, status_code=303)


@app.post('/match/{session_id}/{player_ref}/timeout')
async def match_timeout(session_id: str, player_ref: str) -> RedirectResponse:
    session = GameSession(redis_client, session_id)
    state = await session.load()
    if state is not None:
        await _resolve_timeout(session_id, session, state)
    return RedirectResponse(url=f'/match/{session_id}/{player_ref}', status_code=303)


@app.post('/match/{session_id}/{player_ref}/surrender')
async def match_surrender(session_id: str, player_ref: str) -> RedirectResponse:
    session = GameSession(redis_client, session_id)
    state = await session.load()
    if state is not None and state.get('status') != 'finished':
        await _finish_session(session, loser_ref=player_ref, reason='surrender')
        finished = await session.load()
        if finished:
            await manager.broadcast(session_id, {'type': 'match_finished', 'payload': finished})
    user_id = _user_id_from_ref(player_ref)
    if user_id is not None:
        return RedirectResponse(url=f'/home?user_id={user_id}&error=match_surrendered', status_code=303)
    return RedirectResponse(url='/home?error=match_surrendered', status_code=303)


@app.get('/history', response_class=HTMLResponse)
async def history_page(
    request: Request,
    user_id: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    matches = await match_repo.history(db, limit=50)
    back_href = f'/home?user_id={user_id}' if user_id else '/home'
    return templates.TemplateResponse(request, 'history.html', {'matches': matches, 'back_href': back_href})


@app.get('/leaderboard', response_class=HTMLResponse)
async def leaderboard_page(
    request: Request,
    user_id: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    pvp_leaders = await match_repo.leaderboard_by_match_mode(db, mode='pvp', limit=50)
    bot_leaders = await match_repo.leaderboard_by_match_mode(db, mode='bot', limit=50)
    back_href = f'/home?user_id={user_id}' if user_id else '/'
    return templates.TemplateResponse(
        request,
        'leaderboard.html',
        {'pvp_leaders': pvp_leaders, 'bot_leaders': bot_leaders, 'back_href': back_href},
    )


@app.get('/rules', response_class=HTMLResponse)
async def rules_page(request: Request, user_id: int | None = None) -> HTMLResponse:
    back_href = f'/home?user_id={user_id}' if user_id else '/'
    return templates.TemplateResponse(request, 'rules.html', {'back_href': back_href})


@app.get('/dictionary-packs')
async def dictionary_packs() -> dict[str, list[str]]:
    return {k: sorted(v) for k, v in PACKS.items()}


@app.post('/profile/{username}')
async def create_or_get_profile(username: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    user = await user_repo.get_or_create(db, username)
    return await _profile_payload_for_user(db, user)


@app.post('/matchmaking/start')
async def matchmaking_start(payload: StartRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    started = await _start_match(payload, db)
    return {
        'session_id': started['session_id'],
        'player_ref': started['player_ref'],
        'match_id': started['match_id'],
        'events': started['events'],
    }


@app.get('/matches/history')
async def matches_history(limit: int = 20, db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    matches = await match_repo.history(db, limit)
    return [
        {
            'id': m.id,
            'mode': m.mode,
            'dictionary_pack': m.dictionary_pack,
            'winner_id': m.winner_id,
            'winner_name': m.winner_name,
            'created_at': m.created_at.isoformat(),
        }
        for m in matches
    ]


@app.post('/appeals')
async def create_appeal(payload: AppealRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    appeal = await appeal_repo.create(db, payload.match_id, payload.player_ref, payload.word, payload.reason)
    return {'id': appeal.id, 'status': 'queued'}


@app.websocket('/ws/match/{session_id}/{player_ref}')
async def game_ws(websocket: WebSocket, session_id: str, player_ref: str) -> None:
    await manager.connect(session_id, websocket)
    session = GameSession(redis_client, session_id)

    state = await session.load()
    if state is None:
        await websocket.send_json({'type': 'match_finished', 'payload': {'reason': 'session_not_found'}})
        await websocket.close()
        return

    await websocket.send_json({'type': 'match_update', 'payload': state})

    try:
        while True:
            event = await websocket.receive_json()
            event_type = event.get('type')

            if event_type == 'typing':
                await manager.broadcast(session_id, {'type': 'typing', 'payload': {'player': player_ref}})

            elif event_type == 'word_submit':
                payload = WordSubmit(**event.get('payload', {}))
                state = await session.load()
                if state is None:
                    continue
                if state['turn_order'][state['turn_index']] != player_ref:
                    await websocket.send_json({'type': 'word_rejected', 'payload': {'reason': 'not_your_turn', 'word': payload.word}})
                    continue

                res = validator.validate(
                    payload.word,
                    state['current_letter'],
                    set(state['used_words']) | set(state.get('used_lemmas', [])),
                    dictionary_pack=state['dictionary_pack'],
                    extra_words=set(state.get('extra_words', {}).get(player_ref, [])),
                )
                if not res.ok:
                    if res.reason in {'word_not_in_dictionary', 'not_in_dictionary'}:
                        penalized = await session.apply_penalty(player_ref, penalty=2)
                        await manager.broadcast(
                            session_id,
                            {'type': 'word_rejected', 'payload': {'reason': res.reason, 'word': payload.word, 'penalty': -2}},
                        )
                        await manager.broadcast(session_id, {'type': 'match_update', 'payload': penalized})
                        await manager.broadcast(
                            session_id,
                            {'type': 'turn_changed', 'payload': {'turn': penalized['turn_order'][penalized['turn_index']]}},
                        )
                        if any(p.get('type') == 'bot' for p in penalized.get('participants', [])):
                            await _maybe_bot_turn(session_id, session)
                        continue
                    await websocket.send_json({'type': 'word_rejected', 'payload': {'reason': res.reason, 'word': payload.word}})
                    continue

                normalized = res.normalized_word or payload.word
                score = calculate_score(normalized, payload.response_seconds)
                updated = await session.apply_word(player_ref, normalized, score, lemma=validator.normalize(normalized))
                async with SessionLocal() as db:
                    await _record_word_stats(db, player_ref, score, payload.response_seconds)
                await manager.broadcast(session_id, {'type': 'word_accepted', 'payload': {'word': normalized, 'score': score}})
                await manager.broadcast(session_id, {'type': 'turn_changed', 'payload': {'turn': updated['turn_order'][updated['turn_index']]}})
                await manager.broadcast(session_id, {'type': 'match_update', 'payload': updated})

                if any(p.get('type') == 'bot' for p in updated.get('participants', [])):
                    await _maybe_bot_turn(session_id, session)

            elif event_type == 'request_hot_swap':
                newcomer = event.get('payload', {}).get('new_player_ref', f'human_{int(time.time())}')
                swapped = await session.hot_swap_bot(newcomer, freeze_seconds=3)
                await manager.broadcast(session_id, {'type': 'player_joined', 'payload': {'player': newcomer}})
                await manager.broadcast(session_id, {'type': 'bot_replaced', 'payload': swapped})

    except WebSocketDisconnect:
        manager.disconnect(session_id, websocket)


async def _maybe_bot_turn(session_id: str, session: GameSession) -> None:
    state = await session.load()
    if not state:
        return
    current_ref = state['turn_order'][state['turn_index']]
    participant = next((p for p in state['participants'] if p['id'] == current_ref), None)
    if not participant or participant['type'] != 'bot':
        return
    if state.get('bot_processing'):
        return

    bot_key = current_ref.replace('bot_', '')
    profile = BOTS.get(bot_key, BOTS['medium'])
    used_words = set(state['used_words'])
    used_lemmas = set(state.get('used_lemmas', []))
    letter = state['current_letter']
    pool = state.get('bot_word_pool') or []
    has_pool_options = any(word.startswith(letter) and word not in used_words for word in pool)
    has_global_options = any(word.startswith(letter) and word not in used_words for word in bot_service.words)
    if not has_pool_options and not has_global_options:
        skipped = await session.apply_penalty(current_ref, penalty=0)
        await manager.broadcast(session_id, {'type': 'bot_skipped', 'payload': {'reason': 'no_words_for_letter', 'letter': letter}})
        await manager.broadcast(session_id, {'type': 'turn_changed', 'payload': {'turn': skipped['turn_order'][skipped['turn_index']]}})
        await manager.broadcast(session_id, {'type': 'match_update', 'payload': skipped})
        return

    state['bot_processing'] = True
    await session.save(state)
    bot_delay = random.uniform(BOT_RESPONSE_DELAY_MIN_SECONDS, BOT_RESPONSE_DELAY_MAX_SECONDS)
    await asyncio.sleep(bot_delay)
    state = await session.load() or state
    state['bot_processing'] = False
    success_count = int(state.get('bot_success_count', 0))
    fail_chance = _bot_fail_chance(bot_key, success_count)
    if random.random() < fail_chance:
        await _finish_session(session, loser_ref=current_ref, reason='bot_failed_random')
        finished = await session.load()
        await manager.broadcast(session_id, {'type': 'match_finished', 'payload': finished or {'reason': 'bot_failed_random'}})
        return

    picked = None
    avoid_word = state.get('bot_last_word')
    candidate_sources = [state.get('bot_word_pool'), bot_service.words]
    for source in candidate_sources:
        attempts = 0
        while attempts < 8 and picked is None:
            candidate = bot_service.pick_word(
                state['current_letter'],
                set(state['used_words']),
                profile,
                word_pool=source,
                avoid_word=avoid_word,
                used_lemmas=used_lemmas,
                normalize=validator.normalize,
            )
            if not candidate:
                break
            candidate_check = validator.validate(
                candidate,
                state['current_letter'],
                set(state['used_words']) | used_lemmas,
                dictionary_pack=state.get('dictionary_pack', 'basic'),
            )
            if candidate_check.ok:
                picked = candidate_check.normalized_word or candidate
                break
            avoid_word = candidate
            attempts += 1
        if picked is not None:
            break

    if not picked:
        skipped = await session.apply_penalty(current_ref, penalty=0)
        await manager.broadcast(session_id, {'type': 'bot_skipped', 'payload': {'reason': 'pick_failed', 'letter': letter}})
        await manager.broadcast(session_id, {'type': 'turn_changed', 'payload': {'turn': skipped['turn_order'][skipped['turn_index']]}})
        await manager.broadcast(session_id, {'type': 'match_update', 'payload': skipped})
        return

    score = 0
    updated = await session.apply_word(current_ref, picked, score, lemma=validator.normalize(picked))
    updated['bot_success_count'] = success_count + 1
    updated['bot_processing'] = False
    updated['bot_last_word'] = picked
    updated['turn_deadline'] = int(time.time()) + TURN_SECONDS
    await session.save(updated)
    await manager.broadcast(session_id, {'type': 'word_accepted', 'payload': {'word': picked, 'score': score, 'by': current_ref}})
    await manager.broadcast(session_id, {'type': 'match_update', 'payload': updated})


async def _resolve_timeout(session_id: str, session: GameSession, state: dict[str, Any]) -> dict[str, Any]:
    now = int(time.time())
    if state['turn_deadline'] > now:
        return state

    current_ref = state['turn_order'][state['turn_index']]
    participant = next((p for p in state['participants'] if p['id'] == current_ref), None)
    if participant and participant['type'] == 'human':
        await _finish_session(session, loser_ref=current_ref, reason='timeout')
        refreshed = await session.load()
        return refreshed or state

    refreshed = await session.load()
    return refreshed or state


async def _finish_session(session: GameSession, loser_ref: str, reason: str) -> None:
    state = await session.load()
    if not state:
        return
    if state.get('status') == 'finished':
        return
    winner_ref = next((pid for pid in state['turn_order'] if pid != loser_ref), None)
    state['scores'] = {pid: max(0, int(score)) for pid, score in state.get('scores', {}).items()}
    state['status'] = 'finished'
    state['finish_reason'] = reason
    state['winner_ref'] = winner_ref
    await session.save(state)

    match_id = await redis_client.get(f'session:match:{session.session_id}')
    if match_id and str(match_id).isdigit():
        names = {p['id']: p.get('name', p['id']) for p in state['participants']}
        async with SessionLocal() as db:
            await match_repo.set_scores_and_winner(
                db,
                int(match_id),
                scores={k: max(0, int(v)) for k, v in state.get('scores', {}).items()},
                winner_ref=winner_ref,
                winner_name=names.get(winner_ref, '') if winner_ref else None,
            )
            winner_user_id = _user_id_from_ref(winner_ref or '')
            loser_user_id = _user_id_from_ref(loser_ref)
            bot_ref = next((p['id'] for p in state.get('participants', []) if p.get('type') == 'bot'), None)
            if winner_user_id is not None and bot_ref:
                bot_level = bot_ref.replace('bot_', '', 1)
                await user_repo.add_bot_win(db, winner_user_id, bot_level)
            if winner_user_id is not None and loser_user_id is not None and bot_ref is None:
                match = await db.get(Match, int(match_id))
                winner_rating = (await db.execute(select(Rating).where(Rating.user_id == winner_user_id))).scalar_one_or_none()
                loser_rating = (await db.execute(select(Rating).where(Rating.user_id == loser_user_id))).scalar_one_or_none()
                if winner_rating is None:
                    winner_rating = Rating(user_id=winner_user_id, value=0)
                    db.add(winner_rating)
                    await db.flush()
                if loser_rating is None:
                    loser_rating = Rating(user_id=loser_user_id, value=0)
                    db.add(loser_rating)
                    await db.flush()
                new_winner, new_loser = rating_service.update_1v1(
                    RatingSnapshot(value=int(winner_rating.value or 0)),
                    RatingSnapshot(value=int(loser_rating.value or 0)),
                )
                winner_rating.value = max(0, int(new_winner.value))
                loser_rating.value = max(0, int(new_loser.value))
                if match is not None:
                    winner_stake = match.first_stake if winner_ref == state['turn_order'][0] else match.second_stake
                    loser_stake = match.second_stake if winner_ref == state['turn_order'][0] else match.first_stake
                    payout = int(winner_stake + (loser_stake * float(match.median_multiplier or 1.0)))
                    winner = await user_repo.get_by_id(db, winner_user_id)
                    if winner is not None and payout > 0:
                        winner.coins = int(winner.coins or 0) + payout
                        await db.commit()
                    await match_repo.set_winner_payout(db, int(match_id), payout)


def _bot_fail_chance(bot_key: str, success_count: int) -> float:
    if bot_key == 'easy':
        if success_count < 2:
            return 0.0
        return min(0.32, 0.06 + (success_count - 2) * 0.01)
    if bot_key == 'hard':
        if success_count < 10:
            return 0.0
        return min(0.06, 0.002 + (success_count - 10) * 0.0009)

    # medium by default
    if success_count < 6:
        return 0.0
    return min(0.12, 0.006 + (success_count - 6) * 0.0025)


def _bot_pool_size(bot_level: str, full_size: int) -> int:
    ranges = {
        'easy': (400, 500),
        'medium': (450, 750),
        'hard': (500, 900),
    }
    lo, hi = ranges.get(bot_level, (450, 700))
    if full_size <= lo:
        return full_size
    return min(full_size, random.randint(lo, hi))


def _build_bot_word_pool(bot_level: str) -> list[str]:
    all_words = list(PACKS['basic'])
    target_size = _bot_pool_size(bot_level, len(all_words))

    mandatory: set[str] = set()
    for letter in SUPPORTED_BOT_LETTERS:
        letter_words = BASIC_WORDS_BY_LETTER.get(letter, [])
        if not letter_words:
            continue
        take = min(5, len(letter_words))
        mandatory.update(random.sample(letter_words, k=take))

    remaining = [word for word in all_words if word not in mandatory]
    target_size = max(target_size, len(mandatory))
    extra_needed = max(0, target_size - len(mandatory))
    if extra_needed > 0 and remaining:
        mandatory.update(random.sample(remaining, k=min(extra_needed, len(remaining))))
    return list(mandatory)


async def _run_sqlite_compat_migrations(conn: Any) -> None:
    def _has_column(rows: list[Any], name: str) -> bool:
        return any(row[1] == name for row in rows)

    users_columns = (await conn.execute(text("PRAGMA table_info('users')"))).all()
    user_column_defs = {
        'login': 'VARCHAR(64)',
        'nickname': 'VARCHAR(64)',
        'password_hash': 'VARCHAR(256)',
        'public_id': 'VARCHAR(36)',
        'coins': f'INTEGER DEFAULT {STARTING_COINS}',
        'last_daily_claim_at': 'DATETIME',
        'custom_words': "TEXT DEFAULT ''",
        'unlocked_topics': "TEXT DEFAULT ''",
        'purchase_stats': "TEXT DEFAULT ''",
        'fastest_word_seconds': 'FLOAT',
        'easy_bot_wins': 'INTEGER DEFAULT 0',
        'medium_bot_wins': 'INTEGER DEFAULT 0',
        'hard_bot_wins': 'INTEGER DEFAULT 0',
    }
    for column_name, column_sql in user_column_defs.items():
        if not _has_column(users_columns, column_name):
            await conn.execute(text(f'ALTER TABLE users ADD COLUMN {column_name} {column_sql}'))

    users_columns = (await conn.execute(text("PRAGMA table_info('users')"))).all()
    if _has_column(users_columns, 'login'):
        rows = (await conn.execute(text('SELECT id, username, login, nickname, public_id FROM users'))).all()
        for row in rows:
            data = row._mapping
            public_id = data['public_id'] or user_repo.make_public_id()
            login = data['login'] or data['username']
            nickname = data['nickname'] or data['username']
            await conn.execute(
                text('UPDATE users SET login = :login, nickname = :nickname, public_id = :public_id WHERE id = :id'),
                {'login': str(login).strip().lower(), 'nickname': nickname, 'public_id': public_id, 'id': data['id']},
            )
        await conn.execute(text('UPDATE users SET coins = :coins WHERE coins IS NULL OR coins < :coins'), {'coins': STARTING_COINS})

    participants_columns = (await conn.execute(text("PRAGMA table_info('match_participants')"))).all()
    if not _has_column(participants_columns, 'participant_name'):
        await conn.execute(text("ALTER TABLE match_participants ADD COLUMN participant_name VARCHAR(64) DEFAULT ''"))

    matches_columns = (await conn.execute(text("PRAGMA table_info('matches')"))).all()
    if not _has_column(matches_columns, 'winner_ref'):
        await conn.execute(text("ALTER TABLE matches ADD COLUMN winner_ref VARCHAR(64)"))
    if not _has_column(matches_columns, 'winner_name'):
        await conn.execute(text("ALTER TABLE matches ADD COLUMN winner_name VARCHAR(64)"))
    if not _has_column(matches_columns, 'first_stake'):
        await conn.execute(text("ALTER TABLE matches ADD COLUMN first_stake INTEGER DEFAULT 0"))
    if not _has_column(matches_columns, 'second_stake'):
        await conn.execute(text("ALTER TABLE matches ADD COLUMN second_stake INTEGER DEFAULT 0"))
    if not _has_column(matches_columns, 'first_multiplier'):
        await conn.execute(text("ALTER TABLE matches ADD COLUMN first_multiplier FLOAT DEFAULT 1.0"))
    if not _has_column(matches_columns, 'second_multiplier'):
        await conn.execute(text("ALTER TABLE matches ADD COLUMN second_multiplier FLOAT DEFAULT 1.0"))
    if not _has_column(matches_columns, 'median_multiplier'):
        await conn.execute(text("ALTER TABLE matches ADD COLUMN median_multiplier FLOAT DEFAULT 1.0"))
    if not _has_column(matches_columns, 'winner_payout'):
        await conn.execute(text("ALTER TABLE matches ADD COLUMN winner_payout INTEGER DEFAULT 0"))

    await conn.execute(
        text(
            """
            UPDATE ratings
            SET value = 0
            WHERE value = 1500
              AND user_id NOT IN (
                SELECT DISTINCT user_id
                FROM match_participants
                WHERE user_id IS NOT NULL
              )
            """
        )
    )


@app.post('/match/{session_id}/finish/{winner_ref}')
async def finish_match(session_id: str, winner_ref: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    match_id = await redis_client.get(f'session:match:{session_id}')
    if not match_id:
        return {'status': 'not_found'}
    match = await db.get(Match, int(match_id))
    if not match:
        return {'status': 'not_found'}

    winner_user_id = int(winner_ref) if winner_ref.isdigit() else None
    match.winner_id = winner_user_id

    if winner_user_id:
        participants = (await db.execute(select(Rating).where(Rating.user_id.in_([winner_user_id])))).scalars().all()
        if participants:
            winner_rating = RatingSnapshot(value=participants[0].value)
            loser_rating = RatingSnapshot()
            winner_new, _ = rating_service.update_1v1(winner_rating, loser_rating)
            participants[0].value = winner_new.value

    await db.commit()
    return {'status': 'finished', 'match_id': match.id}
