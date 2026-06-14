"""C++ Hero — Telegram Mini App: aiohttp (статика + API + webhook) + aiogram-бот."""
import hashlib
import json
import logging
import os
import pathlib
import re

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from . import storage
from .auth import validate_init_data
from .recompute_xp import recompute as recompute_progress

log = logging.getLogger(__name__)

BOT_TOKEN = os.environ['BOT_TOKEN']
APP_URL = os.environ.get('APP_URL', 'https://tg.eu-cdn539.com').rstrip('/')
ROOT = pathlib.Path(__file__).resolve().parent.parent
MAX_BODY = 256 * 1024
MAX_CODE = 20_000

WEBHOOK_SECRET = hashlib.sha256(('whsec:' + BOT_TOKEN).encode()).hexdigest()[:40]
WEBHOOK_PATH = '/tg/webhook'

# Персональная пасхалка (id и текст задаются в .env, чтобы не попадать в публичный репозиторий)
EGG_UID = os.environ.get('EASTER_USER_ID', '').strip()
EGG_MSG = os.environ.get('EASTER_MSG', 'Илья-сан, не накручивай 😏').strip()

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
dp = Dispatcher()

_http: aiohttp.ClientSession | None = None
_compiler_cpp = 'gcc-head'      # свежий gcc для C++
_compiler_c = 'gcc-head-c'      # свежий gcc для C — подберём на старте

# ---------------- запуск кода через Wandbox ----------------

async def _pick_compilers() -> None:
    global _compiler_cpp, _compiler_c
    try:
        async with _http.get('https://wandbox.org/api/list.json',
                             timeout=aiohttp.ClientTimeout(total=15)) as r:
            data = json.loads(await r.text())  # Wandbox отдаёт нестандартный mimetype

        def newest(language: str):
            best, best_ver = None, ()
            for c in data:
                name = c.get('name', '')
                if c.get('language') == language and name.startswith('gcc-') and 'head' not in name:
                    ver = tuple(int(x) for x in re.findall(r'\d+', name))
                    if ver > best_ver:
                        best, best_ver = name, ver
            return best

        cpp, cc = newest('C++'), newest('C')
        if cpp:
            _compiler_cpp = cpp
        if cc:
            _compiler_c = cc
    except Exception as e:
        log.warning('compiler list failed: %s', e)
    log.info('compilers: cpp=%s c=%s', _compiler_cpp, _compiler_c)


def _compiler_for(lang: str) -> tuple[str, str]:
    if lang == 'c':
        return _compiler_c, '-std=c11'
    return _compiler_cpp, '-std=c++17'


async def _wandbox(code: str, lang: str, stdin: str = '') -> dict:
    compiler, std = _compiler_for(lang)
    payload = {
        'code': code,
        'compiler': compiler,
        'options': '',
        'compiler-option-raw': std,
        'stdin': stdin,
        'save': False,
    }
    headers = {'User-Agent': 'cpp-hero/1.0', 'Accept': 'application/json'}
    async with _http.post('https://wandbox.org/api/compile.json', json=payload, headers=headers,
                          timeout=aiohttp.ClientTimeout(total=25)) as r:
        if r.status != 200:
            raise RuntimeError(f'wandbox http {r.status}')
        return json.loads(await r.text())  # mimetype может быть не application/json

# ---------------- API ----------------

def _auth_from_request(request: web.Request, body: dict | None = None) -> dict | None:
    """initData из заголовка Authorization: tma <initData> или из тела (sendBeacon)."""
    auth = request.headers.get('Authorization', '')
    init_data = auth[4:] if auth.startswith('tma ') else None
    if not init_data and body and isinstance(body.get('initData'), str):
        init_data = body['initData']
    if not init_data:
        return None
    return validate_init_data(init_data, BOT_TOKEN)


def _client_ip(request: web.Request) -> str:
    fwd = request.headers.get('X-Forwarded-For', '')
    return (fwd.split(',')[0].strip() or request.remote or '?')


async def api_health(_: web.Request) -> web.Response:
    return web.json_response({'ok': True})


async def api_get_progress(request: web.Request) -> web.Response:
    user = _auth_from_request(request)
    if not user:
        return web.json_response({'ok': False, 'error': 'unauthorized'}, status=401)
    progress = await storage.load(int(user['id']))
    resp = {'ok': True, 'progress': progress}
    # пасхалка для конкретного пользователя (id и текст — в .env, не в публичном репозитории)
    if EGG_UID and str(user['id']) == EGG_UID:
        resp['egg'] = EGG_MSG
    return web.json_response(resp)


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
    # анти-чит: XP всегда пересчитывается из достижений на сервере — клиент не может его накрутить
    progress, _, _ = recompute_progress(progress)
    await storage.save(user, progress)
    return web.json_response({'ok': True})


async def api_run(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({'ok': False, 'error': 'bad json'}, status=400)
    code = body.get('code')
    if not isinstance(code, str) or not code.strip():
        return web.json_response({'ok': False, 'error': 'нет кода'}, status=400)
    if len(code) > MAX_CODE:
        return web.json_response({'ok': False, 'error': 'код слишком большой'}, status=400)

    lang = 'c' if body.get('lang') == 'c' else 'cpp'
    stdin = str(body.get('stdin') or '')[:2000]
    user = _auth_from_request(request, body)
    ident = str(user['id']) if user else 'ip:' + _client_ip(request)
    if not await storage.rate_ok(f'run:{ident}', 3):
        return web.json_response({'ok': False, 'error': 'слишком часто, подожди пару секунд'}, status=429)

    compiler, _ = _compiler_for(lang)
    cache_key = 'runcache:' + hashlib.sha256((compiler + '|' + stdin + '|' + code).encode()).hexdigest()
    cached = await storage.kv_get(cache_key)
    if cached:
        return web.json_response(json.loads(cached))

    try:
        data = await _wandbox(code, lang, stdin)
    except Exception as e:
        log.warning('wandbox error: %s', e)
        return web.json_response({'ok': False, 'error': 'компилятор недоступен, попробуй ещё раз'}, status=502)

    result = {
        'ok': True,
        'compile_error': (data.get('compiler_error') or '').strip(),
        'output': data.get('program_output') or '',
        'stderr': (data.get('program_error') or '').strip(),
        'status': data.get('status'),
    }
    await storage.kv_set(cache_key, json.dumps(result), 86400)
    return web.json_response(result)


async def page_index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(ROOT / 'index.html')


async def page_ide(_: web.Request) -> web.FileResponse:
    return web.FileResponse(ROOT / 'ide.html')


_STATIC_JS = {'data.js', 'data_c.js', 'extra.js', 'extra_c.js', 'theory.js', 'theory_c.js', 'langs.js'}


async def page_js(request: web.Request) -> web.FileResponse:
    name = request.path.lstrip('/')
    if name not in _STATIC_JS:
        raise web.HTTPNotFound()
    return web.FileResponse(ROOT / name)


def build_web_app() -> web.Application:
    app = web.Application(client_max_size=MAX_BODY)
    # отдаём только явные маршруты — server/ и .env наружу не торчат
    app.router.add_get('/', page_index)
    app.router.add_get('/index.html', page_index)
    app.router.add_get('/ide', page_ide)
    app.router.add_get('/ide.html', page_ide)
    app.router.add_get('/data.js', page_js)
    app.router.add_get('/data_c.js', page_js)
    app.router.add_get('/extra.js', page_js)
    app.router.add_get('/extra_c.js', page_js)
    app.router.add_get('/theory.js', page_js)
    app.router.add_get('/theory_c.js', page_js)
    app.router.add_get('/langs.js', page_js)
    app.router.add_get('/api/health', api_health)
    app.router.add_get('/api/progress', api_get_progress)
    app.router.add_post('/api/progress', api_save_progress)
    app.router.add_post('/api/run', api_run)
    return app

# ---------------- бот ----------------

def _app_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='🚀 Открыть тренажёр', web_app=WebAppInfo(url=APP_URL)),
    ]])


@dp.message(CommandStart())
async def cmd_start(message: types.Message) -> None:
    await message.answer(
        '<b>C++ Hero</b> — подготовка к экзамену по ООП/C++ за неделю в стиле Duolingo 🎮\n\n'
        '• 8 дней · 40 уроков · 310 заданий\n'
        '• 🧪 песочница: код реально компилируется и запускается\n'
        '• 🧠 интервальные повторения слабых тем\n'
        '• сердечки, XP, стрик и пробный экзамен\n'
        '• прогресс привязан к Telegram и общий на всех устройствах\n\n'
        'Команды: /stats — твой прогресс, /top — таблица лидеров',
        reply_markup=_app_button(),
    )


def _progress_summary(progress: dict) -> dict:
    """Суммирует прогресс по обоим языкам (новый вложенный формат) либо по старому плоскому."""
    langs = progress.get('langs') if isinstance(progress.get('langs'), dict) else None
    if langs:
        buckets = list(langs.values())
        return {
            'xp': sum(int(b.get('xp', 0) or 0) for b in buckets),
            'streak': max([int(b.get('streak', 0) or 0) for b in buckets] + [0]),
            'done': sum(len(b.get('done') or {}) for b in buckets),
            'code': sum(len(b.get('codeDone') or {}) for b in buckets),
            'best': max([int(b.get('bestExam', 0) or 0) for b in buckets] + [0]),
            'per': {k: int((langs[k] or {}).get('xp', 0) or 0) for k in langs},
        }
    return {
        'xp': int(progress.get('xp', 0) or 0),
        'streak': int(progress.get('streak', 0) or 0),
        'done': len(progress.get('done') or {}),
        'code': len(progress.get('codeDone') or {}),
        'best': int(progress.get('bestExam', 0) or 0),
        'per': {'cpp': int(progress.get('xp', 0) or 0)},
    }


@dp.message(Command('stats'))
async def cmd_stats(message: types.Message) -> None:
    progress = await storage.load(message.from_user.id)
    if not progress:
        await message.answer('Ты ещё не начинал 🙃 Жми кнопку и вперёд!', reply_markup=_app_button())
        return
    s = _progress_summary(progress)
    per = s['per']
    per_line = ' · '.join(f'{"C++" if k == "cpp" else "C"}: {v}' for k, v in per.items())
    await message.answer(
        f'📊 <b>Твой прогресс</b>\n\n'
        f'⚡ XP всего: <b>{s["xp"]}</b>  ({per_line})\n'
        f'🔥 Стрик: <b>{s["streak"]}</b> дн.\n'
        f'📚 Уроков пройдено: <b>{s["done"]}</b>\n'
        f'🧪 Код-челленджей: <b>{s["code"]}</b>\n'
        f'🎓 Лучший пробный экзамен: <b>{s["best"]}%</b>',
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

async def _on_startup(app: web.Application) -> None:
    global _http
    await storage.init()
    _http = aiohttp.ClientSession()
    await _pick_compilers()
    try:
        await bot.set_webhook(
            f'{APP_URL}{WEBHOOK_PATH}',
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=True,
            allowed_updates=dp.resolve_used_update_types(),
        )
        log.info('webhook set: %s%s', APP_URL, WEBHOOK_PATH)
    except Exception as e:
        log.error('set_webhook failed: %s', e)


async def _on_cleanup(app: web.Application) -> None:
    if _http is not None:
        await _http.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    app = build_web_app()
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    web.run_app(app, host='0.0.0.0', port=8080)


if __name__ == '__main__':
    main()
