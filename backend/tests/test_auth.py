import time

from jose import jwt
from sqlalchemy import func, select

from app.config import DEFAULT_DEPARTMENTS, DEFAULT_THRESHOLDS, get_settings
from app.database import SessionLocal
from app.models import AppSetting, Department, User
from app.seed import seed

API = "/api/v1"


def test_health_is_public(client):
    r = client.get(f"{API}/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_login_success_returns_token_and_user(client):
    r = client.post(f"{API}/auth/login", json={"username": "admin", "password": "Admin@123"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] > 0
    assert body["user"] == {"id": body["user"]["id"], "username": "admin", "role": "admin"}
    assert "password" not in str(body).lower().replace("password_hash", "")  # no hash/password leakage


def test_login_wrong_password_and_unknown_user_look_identical(client):
    bad_pw = client.post(f"{API}/auth/login", json={"username": "admin", "password": "nope"})
    bad_user = client.post(f"{API}/auth/login", json={"username": "ghost", "password": "nope"})
    assert bad_pw.status_code == bad_user.status_code == 401
    assert bad_pw.json()["detail"] == bad_user.json()["detail"] == "Invalid username or password"


def test_login_validation_errors_do_not_echo_input(client):
    r = client.post(f"{API}/auth/login", json={"username": "", "password": "secret-value-123"})
    assert r.status_code == 422
    assert r.json()["error"] == "validation_error"
    assert "secret-value-123" not in r.text


def test_login_throttle_locks_after_repeated_failures(client):
    max_attempts = get_settings().login_max_attempts
    for _ in range(max_attempts):
        assert client.post(f"{API}/auth/login", json={"username": "admin", "password": "bad"}).status_code == 401
    locked = client.post(f"{API}/auth/login", json={"username": "admin", "password": "Admin@123"})
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) >= 1


def test_protected_routes_require_token(client):
    for path in ("/auth/me", "/departments"):
        r = client.get(f"{API}{path}")
        assert r.status_code == 401
        assert r.json()["code"] == 401


def test_invalid_and_tampered_tokens_rejected(client, auth_headers):
    assert client.get(f"{API}/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    tampered = auth_headers["Authorization"][:-3] + "abc"
    assert client.get(f"{API}/auth/me", headers={"Authorization": tampered}).status_code == 401


def test_expired_token_rejected(client):
    s = get_settings()
    expired = jwt.encode({"sub": "admin", "role": "admin", "exp": int(time.time()) - 10}, s.secret_key, algorithm=s.jwt_algorithm)
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401


def test_me_returns_current_user(client, auth_headers):
    r = client.get(f"{API}/auth/me", headers=auth_headers)
    assert r.status_code == 200 and r.json()["username"] == "admin"


def test_non_admin_forbidden_from_admin_routes(client):
    from app.security.passwords import hash_password

    with SessionLocal() as db:
        db.add(User(username="viewer", password_hash=hash_password("Viewer@123"), role="viewer"))
        db.commit()
    token = client.post(f"{API}/auth/login", json={"username": "viewer", "password": "Viewer@123"}).json()["access_token"]
    r = client.get(f"{API}/departments", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_departments_listed_for_admin(client, auth_headers):
    r = client.get(f"{API}/departments", headers=auth_headers)
    assert r.status_code == 200
    names = [d["name"] for d in r.json()]
    assert names == [n for n, _, _ in DEFAULT_DEPARTMENTS]
    assert sum(d["total_beds"] for d in r.json()) == 300


def test_seed_is_idempotent(client):
    with SessionLocal() as db:
        seed(db)
        seed(db)
        assert db.scalar(select(func.count()).select_from(User).where(User.username == "admin")) == 1
        assert db.scalar(select(func.count()).select_from(Department)) == len(DEFAULT_DEPARTMENTS)
        assert db.scalar(select(func.count()).select_from(AppSetting)) == len(DEFAULT_THRESHOLDS)


def test_cors_preflight_allows_frontend_origin(client):
    r = client.options(
        f"{API}/auth/login",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "content-type"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
