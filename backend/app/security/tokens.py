from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.config import get_settings


def create_access_token(subject: str, role: str) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    s = get_settings()
    expires = timedelta(minutes=s.access_token_expire_minutes)
    payload = {"sub": subject, "role": role, "exp": datetime.now(timezone.utc) + expires}
    return jwt.encode(payload, s.secret_key, algorithm=s.jwt_algorithm), int(expires.total_seconds())


def decode_access_token(token: str) -> dict | None:
    s = get_settings()
    try:
        return jwt.decode(token, s.secret_key, algorithms=[s.jwt_algorithm])
    except JWTError:
        return None
