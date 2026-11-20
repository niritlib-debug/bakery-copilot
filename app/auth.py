"""Shared-password login with a signed cookie. Ten staff, one business (spec.md §1).

Not a user-management system: everyone knows the one password and types their
own name, which becomes their user row for history and rate limits. With
APP_USERNAME set, the name must be that username, so everyone shares one user.
"""
from __future__ import annotations

import base64
import hmac
import hashlib
import re
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import User

COOKIE_NAME = "bc_session"
_NAME_RE = re.compile(r"^[\w .'\-֐-׿]{2,40}$")  # latin, digits, Hebrew letters


def password_ok(candidate: str) -> bool:
    return hmac.compare_digest((candidate or "").encode(), settings.app_password.encode())


def username_ok(name: str) -> bool:
    """With APP_USERNAME set, only that username may sign in (any letter case); unset, any name."""
    if not settings.app_username:
        return True
    return hmac.compare_digest(" ".join((name or "").split()).casefold().encode(),
                               settings.app_username.casefold().encode())


# ---- sign-in throttle (OWASP A07) ----------------------------------------------
# Failed sign-ins per client in a sliding window, kept in memory: one web replica, and a
# restart forgetting old failures is acceptable. Success clears the client's count.
LOGIN_MAX_FAILURES = 10
LOGIN_WINDOW_S = 15 * 60
_failures: dict[str, deque] = defaultdict(deque)


def client_key(request: Request) -> str:
    """The caller's address. Behind Railway's proxy the last X-Forwarded-For entry is the one the
    proxy added; earlier entries are whatever the client sent, so they are not trusted."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded.strip():
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _recent(key: str, now: float) -> deque:
    q = _failures[key]
    while q and now - q[0] > LOGIN_WINDOW_S:
        q.popleft()
    return q


def login_blocked(key: str) -> bool:
    return len(_recent(key, time.time())) >= LOGIN_MAX_FAILURES


def record_login_failure(key: str) -> None:
    _recent(key, time.time()).append(time.time())


def clear_login_failures(key: str) -> None:
    _failures.pop(key, None)


def security_log(event: str, **fields) -> None:
    """One line per security event in the Railway logs (OWASP A09). Never pass a password."""
    detail = " ".join(f"{k}={str(v)[:60]!r}" for k, v in fields.items())
    print(f"security {event} {detail}".rstrip(), flush=True)


def normalise_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not _NAME_RE.match(name):
        raise HTTPException(400, "Name must be 2-40 letters, digits or spaces.")
    return name


def _sign(payload: bytes) -> bytes:
    # Hex, not the raw digest: raw bytes can include the "|" that separates the
    # signature from the payload, and such a token would never read back (ticket 25).
    return hmac.new(settings.app_secret.encode(), payload, hashlib.sha256).hexdigest().encode()


def make_token(user_id: int, name: str) -> str:
    exp = int(time.time()) + settings.session_hours * 3600
    payload = f"{user_id}|{name}|{exp}".encode()
    return base64.urlsafe_b64encode(payload + b"|" + _sign(payload)).decode()


def read_token(token: str | None) -> tuple[int, str] | None:
    if not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode())
        payload, sig = raw.rsplit(b"|", 1)
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        user_id, name, exp = payload.decode().split("|")
        if int(exp) < time.time():
            return None
        return int(user_id), name
    except Exception:
        return None


def get_or_create_user(db: Session, name: str) -> User:
    user = db.scalar(select(User).where(User.name == name))
    if user is None:
        user = User(name=name)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def current_user(request: Request, db: Session) -> User:
    parsed = read_token(request.cookies.get(COOKIE_NAME))
    if parsed is None:
        raise HTTPException(401, "Please sign in.")
    user = db.get(User, parsed[0])
    if user is None:
        raise HTTPException(401, "Please sign in.")
    return user
