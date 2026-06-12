"""Валидация Telegram WebApp initData (HMAC-SHA256 по докам Telegram)."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def validate_init_data(init_data: str, bot_token: str, max_age: int = 86400) -> dict | None:
    """Проверяет подпись initData. Возвращает dict пользователя или None."""
    if not init_data or len(init_data) > 4096:
        return None
    try:
        data = dict(parse_qsl(init_data, keep_blank_values=True))
    except ValueError:
        return None
    received_hash = data.pop('hash', None)
    if not received_hash:
        return None

    check_string = '\n'.join(f'{k}={v}' for k, v in sorted(data.items()))
    secret_key = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        return None

    if max_age:
        try:
            auth_date = int(data.get('auth_date', '0'))
        except ValueError:
            return None
        if time.time() - auth_date > max_age:
            return None

    try:
        user = json.loads(data.get('user', '{}'))
    except json.JSONDecodeError:
        return None
    if not isinstance(user, dict) or not user.get('id'):
        return None
    return user
