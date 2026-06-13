"""Разовый пересчёт XP всем пользователям по детерминированной формуле достижений.

XP = Σ уроков(10 + 5 за идеал) + 15×решённых код-челленджей + бонус за лучший экзамен.
Та же формула, что в index.html (computeXp). Убирает XP, нафармленный переигровкой уроков.

Запуск внутри контейнера app:
    docker compose exec -T app python -m server.recompute_xp          # сухой прогон (только показать)
    docker compose exec -T app python -m server.recompute_xp --apply  # записать в БД
"""
import asyncio
import json
import os
import sys

import asyncpg

PG_DSN = os.environ.get('PG_DSN', 'postgresql://duo:duo@db:5432/duo')
LANG_IDS = ('cpp', 'c')


def exam_bonus(b: int) -> int:
    return 50 if b >= 90 else 30 if b >= 75 else 15 if b >= 50 else 5 if b > 0 else 0


def compute_bucket_xp(bucket: dict) -> int:
    if not isinstance(bucket, dict):
        return 0
    done = bucket.get('done') or {}
    perfect = bucket.get('perfect') or {}
    code = bucket.get('codeDone') or {}
    xp = 0
    for lid, v in done.items():
        if v:
            xp += 10 + (5 if perfect.get(lid) else 0)
    xp += 15 * sum(1 for v in code.values() if v)
    xp += exam_bonus(int(bucket.get('bestExam') or 0))
    return xp


def recompute(progress: dict) -> tuple[dict, int, int]:
    """Возвращает (новый_progress, старый_xp, новый_xp). Структуру сохраняем как есть."""
    old_total = int((progress or {}).get('xp') or 0)
    langs = progress.get('langs') if isinstance(progress, dict) else None
    if isinstance(langs, dict) and (langs.get('cpp') or langs.get('c')):
        # новый вложенный формат
        new_total = 0
        for k in LANG_IDS:
            b = langs.get(k)
            if isinstance(b, dict):
                b['xp'] = compute_bucket_xp(b)
                new_total += b['xp']
        progress['xp'] = new_total
        return progress, old_total, new_total
    if isinstance(progress, dict) and progress.get('done') is not None:
        # старый плоский формат (только C++)
        new_total = compute_bucket_xp(progress)
        progress['xp'] = new_total
        return progress, old_total, new_total
    # пусто — ничего не трогаем
    return progress, old_total, old_total


async def main() -> None:
    apply = '--apply' in sys.argv
    pool = await asyncpg.create_pool(PG_DSN)
    rows = await pool.fetch('SELECT tg_id, progress FROM users')
    total, lowered, raised, same = 0, 0, 0, 0
    sum_old, sum_new = 0, 0
    for r in rows:
        total += 1
        raw = r['progress']
        progress = json.loads(raw) if isinstance(raw, str) else dict(raw)
        new_progress, old_xp, new_xp = recompute(progress)
        sum_old += old_xp
        sum_new += new_xp
        if new_xp < old_xp:
            lowered += 1
            print(f'  tg ...{str(r["tg_id"])[-4:]}: {old_xp} -> {new_xp}  (срезано {old_xp - new_xp})')
        elif new_xp > old_xp:
            raised += 1
            print(f'  tg ...{str(r["tg_id"])[-4:]}: {old_xp} -> {new_xp}  (поднято {new_xp - old_xp})')
        else:
            same += 1
        if apply and new_xp != old_xp:
            await pool.execute(
                'UPDATE users SET progress = $2::jsonb WHERE tg_id = $1',
                r['tg_id'], json.dumps(new_progress, ensure_ascii=False),
            )
    await pool.close()
    mode = 'ЗАПИСАНО В БД' if apply else 'СУХОЙ ПРОГОН (без записи)'
    print('=' * 50)
    print(f'{mode}: пользователей {total} | снижено {lowered} | повышено {raised} | без изменений {same}')
    print(f'Сумма XP было {sum_old} -> стало {sum_new}')


if __name__ == '__main__':
    asyncio.run(main())
