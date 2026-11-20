"""Bakery Copilot backend: the API, the static UI, the health check, the digest hook.

One service does everything (architecture.md, "Where things run"). The agent
loop itself lives in agent.py; this file is doors, locks and plumbing.
"""
from __future__ import annotations

import hmac
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import auth, limits
from .agent import get_model_client, run_turn
from .config import ROOT, settings
from .db import Conversation, Message, SessionLocal, engine, get_db, init_db
from .digest import build_digest, send_digest
from .tools.invoices import recent_invoices


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.init_report = init_db()
    # One line in the deploy log, so a first deploy can be checked (docs/deploy-railway.md, step 7).
    print("seed report: " + ", ".join(f"{k}: {v}" for k, v in app.state.init_report.items()), flush=True)
    app.state.model_client = get_model_client()
    yield


# openapi_url=None: no public map of the API (OWASP A02); docs were already off.
app = FastAPI(title="Bakery Copilot", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


# Security headers on every response (OWASP A02). The CSP allows scripts only from this site and
# the pinned cdnjs file, images from this site or from photos the user attaches (data:/blob:),
# and no framing, so injected markup cannot load or send anything elsewhere.
CSP = ("default-src 'self'; script-src 'self' https://cdnjs.cloudflare.com; style-src 'self'; "
       "img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; object-src 'none'; "
       "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
SECURITY_HEADERS = [
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]
if settings.is_production:  # HTTPS only there; locally the app runs on plain http
    SECURITY_HEADERS.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))


class SecurityHeaders:
    """Plain ASGI middleware, so streamed chat replies pass through untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [h for h in SECURITY_HEADERS if h[0] not in present]
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(SecurityHeaders)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LoginIn(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    password: str = Field(min_length=1, max_length=200)


class ImageIn(BaseModel):
    media_type: str = Field(pattern=r"^image/(png|jpeg|webp|gif)$")
    data: str  # base64, no data: prefix


class ChatIn(BaseModel):
    conversation_id: int | None = None
    message: str = Field(default="", max_length=4000)
    image: ImageIn | None = None


# ---------------------------------------------------------------------------
# Pages and health
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def index():
    # no-cache: browsers re-check the page on every visit (cheap, via ETag), so the ?v= on
    # styles.css and app.js reaches them after a deploy. Bump ?v= when either file changes.
    return FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/health")
def health(db: Session = Depends(get_db)):
    """Railway's health check. 200 only when the database answers and a model is configured."""
    problems = []
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - exercised on a broken deploy, not in tests
        problems.append(f"db: {type(exc).__name__}")
    if settings.model_provider == "anthropic" and not settings.anthropic_api_key:
        problems.append("ANTHROPIC_API_KEY missing")
    # Public endpoint: status and problems only, not which model, database or environment (OWASP A02).
    body = {"status": "ok" if not problems else "degraded", "problems": problems,
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if problems:
        raise HTTPException(503, body)
    return body


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.post("/api/login")
def login(payload: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    key = auth.client_key(request)
    if auth.login_blocked(key):  # OWASP A07: no unlimited password guessing
        auth.security_log("login_blocked", client=key)
        raise HTTPException(429, "Too many sign-in attempts. Try again in 15 minutes.")
    # One message for both, so a wrong guess does not say which half was wrong.
    if not (auth.username_ok(payload.name) and auth.password_ok(payload.password)):
        auth.record_login_failure(key)
        auth.security_log("login_failed", client=key, name=payload.name)
        raise HTTPException(401, "Wrong username or password.")
    auth.clear_login_failures(key)
    name = settings.app_username or payload.name  # "bell" and "Bell" are the same user
    user = auth.get_or_create_user(db, auth.normalise_name(name))
    response.set_cookie(auth.COOKIE_NAME, auth.make_token(user.id, user.name), httponly=True, samesite="lax",
                        secure=settings.is_production, max_age=settings.session_hours * 3600, path="/")
    return {"id": user.id, "name": user.name}


@app.post("/api/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return Response(status_code=204)


@app.get("/api/me")
def me(request: Request, db: Session = Depends(get_db)):
    user = auth.current_user(request, db)
    return {"id": user.id, "name": user.name}


# ---------------------------------------------------------------------------
# Conversations and messages
# ---------------------------------------------------------------------------

@app.get("/api/conversations")
def list_conversations(request: Request, db: Session = Depends(get_db)):
    user = auth.current_user(request, db)
    rows = db.scalars(select(Conversation).where(Conversation.user_id == user.id)
                      .order_by(Conversation.updated_at.desc()).limit(100)).all()
    return [{"id": c.id, "title": c.title, "updated_at": c.updated_at.isoformat(timespec="seconds")} for c in rows]


@app.get("/api/conversations/{conversation_id}/messages")
def list_messages(conversation_id: int, request: Request, db: Session = Depends(get_db)):
    user = auth.current_user(request, db)
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "Conversation not found.")
    rows = db.scalars(select(Message).where(Message.conversation_id == conv.id).order_by(Message.id)).all()
    return [{"id": m.id, "role": m.role, "content": m.content, "has_image": m.has_image,
             "created_at": m.created_at.isoformat(timespec="seconds")} for m in rows]


@app.post("/api/chat")
def chat(payload: ChatIn, request: Request, db: Session = Depends(get_db)):
    """One turn. Checks the three limits, then streams the agent's events as SSE."""
    user = auth.current_user(request, db)
    if not payload.message.strip() and payload.image is None:
        raise HTTPException(400, "Say something or attach an invoice.")
    limits.check_rate_limit(db, user.id)
    limits.check_daily_cap(db)
    limits.check_upload_size(payload.image.data if payload.image else None)

    conv = None
    if payload.conversation_id is not None:
        conv = db.get(Conversation, payload.conversation_id)
        if conv is None or conv.user_id != user.id:
            raise HTTPException(404, "Conversation not found.")
    conv_id = conv.id if conv else None
    user_id = user.id
    image = payload.image.model_dump() if payload.image else None
    client = request.app.state.model_client

    def sse():
        # A dedicated session: the request-scoped one may close before the stream ends.
        with SessionLocal() as sdb:
            suser = sdb.get(type(user), user_id)
            sconv = sdb.get(Conversation, conv_id) if conv_id else None
            for event in run_turn(sdb, user=suser, conversation=sconv, text=payload.message, image=image, client=client):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}
    return StreamingResponse(sse(), media_type="text/event-stream", headers=headers)


# ---------------------------------------------------------------------------
# Invoices, stats, digest
# ---------------------------------------------------------------------------

@app.get("/api/invoices")
def invoices(request: Request, db: Session = Depends(get_db)):
    auth.current_user(request, db)
    return recent_invoices(db, limit=50)


@app.get("/api/stats")
def stats(request: Request, db: Session = Depends(get_db)):
    user = auth.current_user(request, db)
    return {"spend_today_usd": round(limits.spend_today_usd(db), 4), "daily_cap_usd": settings.daily_cap_usd,
            "messages_last_hour": limits.messages_last_hour(db, user.id), "rate_limit_per_hour": settings.rate_limit_per_hour}


@app.post("/internal/digest")
def digest(db: Session = Depends(get_db), x_cron_secret: str | None = Header(default=None)):
    """Manual or cron trigger for the morning digest. Protected by CRON_SECRET."""
    # compare_digest: the check takes the same time however much of a guess is right (OWASP A04).
    if not settings.cron_secret or not hmac.compare_digest((x_cron_secret or "").encode(), settings.cron_secret.encode()):
        auth.security_log("digest_bad_secret")
        raise HTTPException(401, "Bad or missing X-Cron-Secret.")
    body = build_digest(db)
    sent = send_digest(body)
    return {"text": body, "sent": sent}
