import os
import tempfile
from pathlib import Path

# Point the app at a throwaway database BEFORE any app module is imported.
_tmp = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}"
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789"
os.environ["SEED_ADMIN_USERNAME"] = "admin"
os.environ["SEED_ADMIN_PASSWORD"] = "Admin@123"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.routers import auth as auth_router  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:  # runs lifespan: creates tables and seeds
        yield c


@pytest.fixture(autouse=True)
def _reset_throttle():
    auth_router.throttle._fails.clear()
    yield


@pytest.fixture()
def auth_headers(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin@123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
