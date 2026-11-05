from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.schemas.auth import LoginRequest, TokenResponse, UserOut
from app.security.dependencies import get_current_user
from app.security.passwords import hash_password, verify_password
from app.security.throttle import LoginThrottle
from app.security.tokens import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])

_s = get_settings()
throttle = LoginThrottle(_s.login_max_attempts, _s.login_lock_seconds)

# Verified against when the username does not exist, so response time doesn't reveal valid usernames.
_DUMMY_HASH = hash_password("not-a-real-password")


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    key = f"{body.username.lower()}|{client_ip}"

    wait = throttle.retry_after(key)
    if wait:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {wait} seconds.",
            headers={"Retry-After": str(wait)},
        )

    user = db.scalar(select(User).where(User.username == body.username))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active:
        throttle.record_failure(key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    throttle.reset(key)
    user.last_login = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()

    token, expires_in = create_access_token(user.username, user.role)
    return TokenResponse(access_token=token, expires_in=expires_in, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
