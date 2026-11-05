from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security.tokens import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise _unauthorized()
    payload = decode_access_token(creds.credentials)
    if not payload or "sub" not in payload:
        raise _unauthorized("Invalid or expired token")
    user = db.scalar(select(User).where(User.username == payload["sub"]))
    if user is None or not user.is_active:
        raise _unauthorized("User not found or disabled")
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """Dependency for every admin-only router."""
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return user
