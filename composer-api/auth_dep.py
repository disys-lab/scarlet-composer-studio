"""
Request authentication dependency - mirrors gustavo/api/auth.py's shape.

When AUTH_ENABLED=false (default): every route passes through as a fixed
local admin session, no login required at all - same dev-mode behavior
composer already has today, and the same default Gustavo itself uses.
When AUTH_ENABLED=true: every request must carry a composer session token
(minted at POST /api/auth/login, which itself delegates the real
credential check to a live Gustavo instance - see routers/auth.py).
"""
import os

from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from session import InvalidSession, Session, decode_session_token

AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "false").lower() in ("1", "true", "yes", "on")

_bearer = HTTPBearer(auto_error=False)

_LOCAL_SESSION = Session(username="local", is_admin=True)


async def verify_session(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> Session:
    if not AUTH_ENABLED:
        return _LOCAL_SESSION

    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    try:
        return decode_session_token(credentials.credentials)
    except InvalidSession:
        raise HTTPException(status_code=401, detail="Invalid or expired session")


def require_admin(session: Session = Depends(verify_session)) -> Session:
    if not session.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return session
