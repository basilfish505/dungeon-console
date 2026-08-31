"""Character name validation, password hashing, and signed auth tokens.

Framework-free so store / world_persistence can import it without pulling
Flask or game state. Tokens are signed with itsdangerous; passwords use
werkzeug.security (both already Flask dependencies).
"""

from __future__ import annotations

import re
import time
from collections import defaultdict

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

NAME_MIN_LEN = 3
NAME_MAX_LEN = 16
NAME_PATTERN = re.compile(r'^[A-Za-z0-9_-]+$')

PASSWORD_MIN_LEN = 6
PASSWORD_MAX_LEN = 128

AUTH_TOKEN_SALT = 'permaquest-auth-v1'
AUTH_TOKEN_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 days

# In-memory login throttle: name_key -> list of attempt timestamps.
_LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
LOGIN_WINDOW_SECONDS = 60
LOGIN_MAX_ATTEMPTS = 8


def normalize_name(raw) -> str:
    """Strip surrounding whitespace; preserve chosen capitalization."""
    if raw is None:
        return ''
    return str(raw).strip()


def name_key(raw) -> str:
    """Case-insensitive key used for uniqueness and login lookup."""
    return normalize_name(raw).casefold()


def validate_name(raw) -> str | None:
    """
    Return an error message if the name is invalid, else None.

    Valid names are 3–16 chars of [A-Za-z0-9_-].
    """
    name = normalize_name(raw)
    if not name:
        return 'Choose a character name.'
    if len(name) < NAME_MIN_LEN:
        return f'Name must be at least {NAME_MIN_LEN} characters.'
    if len(name) > NAME_MAX_LEN:
        return f'Name must be at most {NAME_MAX_LEN} characters.'
    if not NAME_PATTERN.fullmatch(name):
        return 'Name may only use letters, numbers, hyphens, and underscores.'
    return None


def validate_password(raw) -> str | None:
    """Return an error message if the password is invalid, else None."""
    if raw is None:
        return 'Choose a password.'
    password = str(raw)
    if len(password) < PASSWORD_MIN_LEN:
        return f'Password must be at least {PASSWORD_MIN_LEN} characters.'
    if len(password) > PASSWORD_MAX_LEN:
        return f'Password must be at most {PASSWORD_MAX_LEN} characters.'
    return None


def hash_password(password: str) -> str:
    return generate_password_hash(str(password))


def verify_password(password_hash, password: str) -> bool:
    if not password_hash or password is None:
        return False
    try:
        return check_password_hash(str(password_hash), str(password))
    except (TypeError, ValueError):
        return False


def make_auth_token(secret_key: str, *, player_id: str, world_id: str) -> str:
    serializer = URLSafeTimedSerializer(str(secret_key), salt=AUTH_TOKEN_SALT)
    return serializer.dumps({'pid': player_id, 'wid': world_id})


def read_auth_token(secret_key: str, token, *, world_id: str | None = None):
    """
    Verify a token. Returns {'player_id', 'world_id'} or None.

    When world_id is provided, the token's world must match (rejects tokens
    from a wiped / retired world).
    """
    if not token:
        return None
    serializer = URLSafeTimedSerializer(str(secret_key), salt=AUTH_TOKEN_SALT)
    try:
        payload = serializer.loads(
            str(token), max_age=AUTH_TOKEN_MAX_AGE_SECONDS
        )
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    pid = payload.get('pid')
    wid = payload.get('wid')
    if not pid or not wid:
        return None
    if world_id is not None and str(wid) != str(world_id):
        return None
    return {'player_id': str(pid), 'world_id': str(wid)}


def login_allowed(name_key_value: str) -> bool:
    """Return False if this name_key is currently rate-limited."""
    key = name_key_value or ''
    now = time.monotonic()
    window_start = now - LOGIN_WINDOW_SECONDS
    attempts = [t for t in _LOGIN_ATTEMPTS[key] if t >= window_start]
    _LOGIN_ATTEMPTS[key] = attempts
    return len(attempts) < LOGIN_MAX_ATTEMPTS


def record_login_attempt(name_key_value: str) -> None:
    key = name_key_value or ''
    _LOGIN_ATTEMPTS[key].append(time.monotonic())


def clear_login_attempts(name_key_value: str) -> None:
    _LOGIN_ATTEMPTS.pop(name_key_value or '', None)
