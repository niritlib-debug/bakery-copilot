"""OWASP Top 10:2025 checks (security review, 2026-11-20)."""

from app import agent, auth


def test_security_headers_on_pages_and_api(client):
    for path in ("/", "/health", "/static/app.js"):
        h = client.get(path).headers
        assert "script-src 'self' https://cdnjs.cloudflare.com" in h["content-security-policy"]
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"


def test_no_public_api_map(client):
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(path).status_code == 404


def test_health_shows_no_internals(client):
    body = client.get("/health").json()
    assert set(body) == {"status", "problems", "time"}


def test_markdown_script_is_pinned(client):
    html = client.get("/").text
    assert 'marked.min.js" integrity="sha512-' in html and 'crossorigin="anonymous"' in html


def test_login_locks_after_repeated_failures(client, monkeypatch):
    monkeypatch.setattr(auth, "LOGIN_MAX_FAILURES", 3)
    auth._failures.clear()
    client.cookies.clear()
    headers = {"X-Forwarded-For": "203.0.113.7"}
    for _ in range(3):
        r = client.post("/api/login", json={"name": "Dana", "password": "wrong"}, headers=headers)
        assert r.status_code == 401
    blocked = client.post("/api/login", json={"name": "Dana", "password": "test-pass"}, headers=headers)
    assert blocked.status_code == 429  # even the right password waits out the window
    other = client.post("/api/login", json={"name": "Dana", "password": "test-pass"}, headers={"X-Forwarded-For": "203.0.113.8"})
    assert other.status_code == 200  # other people are not locked out
    auth._failures.clear()


def test_client_key_trusts_only_the_proxy_entry():
    class Req:
        headers = {"x-forwarded-for": "1.2.3.4, 198.51.100.9"}
        client = None
    assert auth.client_key(Req()) == "198.51.100.9"  # the first entry is client-supplied


def test_failed_login_is_logged_without_the_password(client, capsys):
    auth._failures.clear()
    client.post("/api/login", json={"name": "Dana", "password": "s3cret-guess"})
    out = capsys.readouterr().out
    assert "security login_failed" in out and "s3cret-guess" not in out
    auth._failures.clear()


def test_digest_secret_checked(client):
    assert client.post("/internal/digest", headers={"X-Cron-Secret": "cron-tesX"}).status_code == 401
    assert client.post("/internal/digest", headers={"X-Cron-Secret": "cron-test"}).status_code == 200


def test_provider_error_text_not_shown_to_users():
    if agent.anthropic is None:
        return
    import httpx
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    def bad(msg):
        return agent.anthropic.BadRequestError(msg, response=httpx.Response(400, request=req), body=None)
    assert "out of credits" in agent._friendly(bad("Your credit balance is too low ... req_011Cg"))
    msg = agent._friendly(bad("internal detail req_abc123"))
    assert "req_abc123" not in msg and "recorded" in msg
