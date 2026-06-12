"""C++ Hero — Telegram Mini App: aiohttp-сервер (статика + API) + aiogram-бот."""
import asyncio
import json
import logging
import os
import pathlib

from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiohttp import web

from . import storage
from .auth import validate_init_data

log = logging.getLogger(__name__)

BOT_TOKEN = os.environ['BOT_TOKEN']
APP_URL = os.environ.get('APP_URL', 'https://tg.eu-cdn539.com')
ROOT = pathlib.Path(__file__).resolve().parent.parent
MAX_BODY = 256 * 1024

# ---------------- API ----------------

def _auth_from_request(request: web.Request, body: dict | None = None) -> dict | None:
    """initData берём из заголовка Authorization: tma <initData> или из тела (sendBeacon)."""
    auth = request.headers.get('Authorization', '')
    init_data = auth[4:] if auth.startswith('tma ') else None
    if not init_data and body and isinstance(body.get('initData'), str):
        init_data = body['initData']
    if not init_data:
        return None
    return validate_init_data(init_data, BOT_TOKEN)


async def api_health(_: web.Request) -> web.Response:
    return web.json_response({'ok': True})


async def api_get_progress(request: web.Request) -> web.Response:
    user = _auth_from_request(request)
    if not user:
        return web.json_response({'ok': False, 'error': 'unauthorized'}, status=401)
    progress = await storage.load(int(user['id']))
    return web.json_response({'ok': True, 'progress': progress})


async def api_save_progress(request: web.Request) -> web.Response:
    if request.content_length and request.content_length > MAX_BODY:
        return web.json_response({'ok': False, 'error': 'too large'}, status=413)
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({'ok': False, 'error': 'bad json'}, status=400)
    user = _auth_from_request(request, body)
    if not user:
        return web.json_response({'ok': False, 'error': 'unauthorized'}, status=401)
    progress = body.get('progress') if isinstance(body.get('progress'), dict) else body
    if not isinstance(progress, dict):
        return web.json_response({'ok': False, 'error': 'bad progress'}, status=400)
    progress.pop('initData', None)
    await storage.save(user, progress)
    return web.json_response({'ok': True})


async def page_index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(ROOT / 'index.html')


async def page_data(_: web.Request) -> web.FileResponse:
    return web.FileResponse(ROOT / 'data.js')


def build_web_app() -> web.Application:
    app = web.Application(client_max_size=MAX_BODY)
    # статика отдаётся только явными маршрутами — server/ и .env наружу не торчат
    app.router.add_get('/', page_index)
    app.router.add_get('/index.html', page_index)
    app.router.add_get('/data.js', page_data)
    app.router.add_get('/api/health', api_health)
    app.router.add_get('/api/progress', api_get_progress)
    app.router.add_post('/api/progress', api_save_progress)
    return app

# ---------------- бот ----------------

dp = Dispatcher()


def _app_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='🚀 Открыть тренажёр', web_app=WebAppInfo(url=APP_URL)),
    ]])


@dp.message(CommandStart())
async def cmd_start(message: types.Message) -> None:
    await message.answer(
        '<b>C++ Hero</b> — подготовка к экзамену по ООП/C++ за неделю в стиле Duolingo 🎮\n\n'
        '• 8 дней · 40 уроков · 310 заданий\n'
        '• сердечки, XP, стрик и пробный экзамен\n'
        '• прогресс привязан к твоему Telegram и общий на всех устройствах\n\n'
        'Команды: /stats — твой прогресс, /top — таблица лидеров',
        reply_markup=_app_button(),
    )


@dp.message(Command('stats'))
async def cmd_stats(message: types.Message) -> None:
    progress = await storage.load(message.from_user.id)
    if not progress:
        await message.answer('Ты ещё не начинал 🙃 Жми кнопку и вперёд!', reply_markup=_app_button())
        return
    done = len(progress.get('done') or {})
    await message.answer(
        f'📊 <b>Твой прогресс</b>\n\n'
        f'⚡ XP: <b>{progress.get("xp", 0)}</b>\n'
        f'🔥 Стрик: <b>{progress.get("streak", 0)}</b> дн.\n'
        f'📚 Уроков пройдено: <b>{done}/40</b>\n'
        f'🎓 Лучший пробный экзамен: <b>{progress.get("bestExam", 0)}%</b>',
        reply_markup=_app_button(),
    )


@dp.message(Command('top'))
async def cmd_top(message: types.Message) -> None:
    rows = await storage.top(10)
    if not rows:
        await message.answer('Пока пусто — стань первым в таблице лидеров! 🏆', reply_markup=_app_button())
        return
    medals = ['🥇', '🥈', '🥉']
    lines = [
        f'{medals[i] if i < 3 else f"{i + 1}."} {r["name"]} — {r["xp"]} XP'
        for i, r in enumerate(rows)
    ]
    await message.answer('🏆 <b>Таблица лидеров</b>\n\n' + '\n'.join(lines), reply_markup=_app_button())

# ---------------- запуск ----------------

async def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    await storage.init()

    app = build_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    log.info('web app on :8080, mini app url: %s', APP_URL)

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
