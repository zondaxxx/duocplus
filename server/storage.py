"""Хранилище прогресса: PostgreSQL — источник истины, Redis — кэш."""
import asyncio
import json
import logging
import os

import asyncpg
import redis.asyncio as aioredis

log = logging.getLogger(__name__)

PG_DSN = os.environ.get('PG_DSN', 'postgresql://duo:duo@db:5432/duo')
REDIS_URL = os.environ.get('REDIS_URL', 'redis://redis:6379/0')
CACHE_TTL = 3600

_pool: asyncpg.Pool | None = None
_redis: aioredis.Redis | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id      BIGINT PRIMARY KEY,
    username   TEXT,
    first_name TEXT,
    progress   JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS users_xp_idx
    ON users (((progress->>'xp')::int) DESC NULLS LAST);
"""


async def init() -> None:
    global _pool, _redis
    for attempt in range(30):  # ждём, пока поднимется postgres
        try:
            _pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=10)
            break
        except (OSError, asyncpg.PostgresError) as e:
            log.info('waiting for postgres (%s): %s', attempt, e)
            await asyncio.sleep(1)
    if _pool is None:
        raise RuntimeError('postgres is not available')
    async with _pool.acquire() as con:
        await con.execute(_SCHEMA)
    _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        await _redis.ping()
    except Exception as e:  # Redis опционален — работаем и без кэша
        log.warning('redis unavailable, cache disabled: %s', e)
        _redis = None
    log.info('storage ready')


def _key(tg_id: int) -> str:
    return f'progress:{tg_id}'


async def load(tg_id: int) -> dict | None:
    if _redis is not None:
        try:
            cached = await _redis.get(_key(tg_id))
            if cached:
                return json.loads(cached)
        except Exception as e:
            log.warning('redis get failed: %s', e)
    row = await _pool.fetchrow('SELECT progress FROM users WHERE tg_id = $1', tg_id)
    if row is None:
        return None
    progress = json.loads(row['progress'])
    if _redis is not None:
        try:
            await _redis.set(_key(tg_id), json.dumps(progress), ex=CACHE_TTL)
        except Exception:
            pass
    return progress


async def save(user: dict, progress: dict) -> None:
    tg_id = int(user['id'])
    payload = json.dumps(progress)
    await _pool.execute(
        """
        INSERT INTO users (tg_id, username, first_name, progress, updated_at)
        VALUES ($1, $2, $3, $4::jsonb, now())
        ON CONFLICT (tg_id) DO UPDATE
            SET username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                progress = EXCLUDED.progress,
                updated_at = now()
        """,
        tg_id, user.get('username'), user.get('first_name'), payload,
    )
    if _redis is not None:
        try:
            await _redis.set(_key(tg_id), payload, ex=CACHE_TTL)
        except Exception:
            pass


async def kv_get(key: str) -> str | None:
    if _redis is None:
        return None
    try:
        return await _redis.get(key)
    except Exception:
        return None


async def kv_set(key: str, value: str, ttl: int) -> None:
    if _redis is None:
        return
    try:
        await _redis.set(key, value, ex=ttl)
    except Exception:
        pass


async def rate_ok(key: str, ttl: int) -> bool:
    """True если запрос разрешён. Ставит ключ с NX — следующий в окне ttl получит False."""
    if _redis is None:
        return True
    try:
        return bool(await _redis.set(key, '1', ex=ttl, nx=True))
    except Exception:
        return True


async def top(limit: int = 10) -> list[dict]:
    rows = await _pool.fetch(
        """
        SELECT tg_id, COALESCE(first_name, username, 'аноним') AS name,
               COALESCE((progress->>'xp')::int, 0) AS xp
        FROM users
        ORDER BY xp DESC
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]
