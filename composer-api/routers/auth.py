"""
/api/auth — delegates the actual credential check to a live Gustavo
instance, then mints composer's own session token.

Gustavo keeps no local user database of its own (real users live in
Nebula, which Gustavo proxies to - see gustavo/api/nebula_auth.py). Its
JWT scheme has no JWKS/public key and no documented path for a different
service to verify its tokens directly - reimplementing that would mean
sharing GUSTAVO_SESSION_SECRET and duplicating Gustavo's internal
HKDF+HS256+Fernet logic, which is fragile and undocumented. What *is*
safe to call from anywhere: Gustavo's own POST /api/auth/login endpoint,
with the same "identifier:secret" credential shape it already accepts.
So: forward the credential there, and only mint a composer session if
Gustavo itself says the credential is valid.

GET  /api/auth/status → whether composer's own auth is enabled.
POST /api/auth/login  → body {"credential": "identifier:secret"}, same
                         shape gustavo/api/routers/auth.py's LoginRequest
                         uses (so the same "username:password" a Gustavo
                         user already has works here unchanged).
"""
import logging

import requests
from fastapi import APIRouter
from pydantic import BaseModel

import config_store
from auth_dep import AUTH_ENABLED
from session import Session, create_session_token

router = APIRouter()


class LoginRequest(BaseModel):
    credential: str


@router.get("/status")
async def auth_status():
    return {"auth_enabled": AUTH_ENABLED}


@router.post("/login")
async def login(req: LoginRequest):
    gustavo_url = config_store.get().get("GUSTAVO_API_URL", "").rstrip("/")
    if not gustavo_url:
        return {
            "error": True,
            "response": "Gustavo API URL is not configured - set it on the Settings page first.",
        }

    try:
        resp = requests.post(
            f"{gustavo_url}/api/auth/login",
            json={"credential": req.credential},
            timeout=10,
        )
    except Exception as exc:
        logging.error(f"login: could not reach Gustavo at {gustavo_url}: {exc}")
        return {"error": True, "response": f"Could not reach Gustavo API at {gustavo_url}: {exc}"}

    if resp.status_code != 200:
        return {"error": True, "response": f"Gustavo API returned HTTP {resp.status_code}"}

    data = resp.json()
    if data.get("error"):
        # Pass Gustavo's own error message straight through - it already
        # says exactly what was wrong with the credential.
        return {"error": True, "response": data.get("response", "Login failed")}

    gustavo_session = data.get("response", {})
    session = Session(
        username=gustavo_session.get("username", ""),
        is_admin=bool(gustavo_session.get("is_admin", False)),
    )
    return {
        "error": False,
        "response": {
            "token": create_session_token(session),
            "username": session.username,
            "is_admin": session.is_admin,
        },
    }
