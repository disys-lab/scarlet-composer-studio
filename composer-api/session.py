"""
composer-api session tokens.

Not a competing credential store - the actual password check happens
against a live Gustavo instance (see routers/auth.py's /login, which
POSTs the caller's credential to {GUSTAVO_API_URL}/api/auth/login and
only proceeds on Gustavo's own answer). Once that one delegated check
succeeds, composer keeps its own lightweight session token - same
*shape* as gustavo/api/session.py (JWT HS256, single root secret env
var, TTL), but without the Fernet-encrypted Nebula-secret passthrough
Gustavo's own Session carries: composer never needs to re-authenticate
to Nebula on a user's behalf per request, so there's nothing secret left
to hold onto after login.
"""
import logging
import os
import secrets as _secrets
import time
from dataclasses import dataclass, field

import jwt

SESSION_TTL_SECONDS = int(os.environ.get("COMPOSER_SESSION_TTL", str(12 * 3600)))
_JWT_ALGORITHM = "HS256"


def _load_signing_key() -> bytes:
    configured = os.environ.get("COMPOSER_SESSION_SECRET", "")
    if configured:
        return configured.encode("utf-8")
    logging.warning(
        "COMPOSER_SESSION_SECRET is not set - generating a random secret for this "
        "process. Every session will be invalidated on restart. Set "
        "COMPOSER_SESSION_SECRET for production deployments."
    )
    return _secrets.token_bytes(32)


_SIGNING_KEY = _load_signing_key()


@dataclass
class Session:
    username: str
    is_admin: bool
    # Nebula group memberships, straight from Gustavo's own login response
    # (see routers/auth.py) - carried through the token so a later request
    # (e.g. a data-source authorize check) can test group-based grants
    # without a second round-trip to Gustavo/Nebula. Empty for the
    # AUTH_ENABLED=false local admin session, same as everywhere else that
    # short-circuits on is_admin instead.
    groups: list[str] = field(default_factory=list)


class InvalidSession(Exception):
    pass


def create_session_token(session: Session) -> str:
    claims = {
        "username": session.username,
        "is_admin": session.is_admin,
        "groups": session.groups,
        "exp": int(time.time()) + SESSION_TTL_SECONDS,
    }
    return jwt.encode(claims, _SIGNING_KEY, algorithm=_JWT_ALGORITHM)


def decode_session_token(token: str) -> Session:
    try:
        claims = jwt.decode(token, _SIGNING_KEY, algorithms=[_JWT_ALGORITHM])
        return Session(
            username=claims["username"],
            is_admin=claims["is_admin"],
            groups=claims.get("groups", []),
        )
    except (jwt.PyJWTError, KeyError) as exc:
        raise InvalidSession(str(exc)) from exc
