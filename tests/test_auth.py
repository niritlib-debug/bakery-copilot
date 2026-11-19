"""Session tokens (app/auth.py): a token made at login must read back on the next request."""
import base64

from app import auth


def test_session_token_round_trips_for_every_second(monkeypatch):
    # The expiry is a whole second, so 1,000 consecutive seconds give 1,000 different
    # signatures; about one raw HMAC digest in nine contains the byte '|' (ticket 25).
    start = 1_800_000_000
    for offset in range(1000):
        monkeypatch.setattr(auth.time, "time", lambda: start + offset)
        assert auth.read_token(auth.make_token(1, "Dana")) == (1, "Dana"), f"rejected at second {offset}"


def test_tampered_token_is_rejected():
    payload, sig = base64.urlsafe_b64decode(auth.make_token(1, "Dana")).rsplit(b"|", 1)

    def encode(p: bytes, s: bytes) -> str:
        return base64.urlsafe_b64encode(p + b"|" + s).decode()

    other_user = payload.replace(b"1|", b"2|", 1)  # claims user 2 under user 1's signature
    flipped = sig[:-1] + (b"0" if sig[-1:] != b"0" else b"1")
    assert auth.read_token(encode(payload, sig)) == (1, "Dana")
    assert auth.read_token(encode(other_user, sig)) is None
    assert auth.read_token(encode(payload, flipped)) is None
    assert auth.read_token("not-a-token") is None


def test_username_check_off_when_not_set(monkeypatch):
    import dataclasses
    monkeypatch.setattr(auth, "settings", dataclasses.replace(auth.settings, app_username=None))
    assert auth.username_ok("Dana") and auth.username_ok("anyone")


def test_login_requires_the_set_username(client, monkeypatch):
    import dataclasses
    from app import main
    with_user = dataclasses.replace(auth.settings, app_username="Bell")
    monkeypatch.setattr(auth, "settings", with_user)
    monkeypatch.setattr(main, "settings", with_user)
    client.cookies.clear()

    wrong_user = client.post("/api/login", json={"name": "Dana", "password": "test-pass"})
    assert wrong_user.status_code == 401
    assert wrong_user.json()["detail"] == "Wrong username or password."
    wrong_pass = client.post("/api/login", json={"name": "Bell", "password": "nope"})
    assert wrong_pass.status_code == 401
    assert wrong_pass.json()["detail"] == "Wrong username or password."

    ok = client.post("/api/login", json={"name": "Bell", "password": "test-pass"})
    assert ok.status_code == 200 and ok.json()["name"] == "Bell"
    lower = client.post("/api/login", json={"name": " bell ", "password": "test-pass"})
    assert lower.status_code == 200 and lower.json() == ok.json()  # same user, any capitals
