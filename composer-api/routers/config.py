"""
/api/config — GUSTAVO_API_URL (login delegation) and REDIS_HOST/PORT/
AUTH_TOKEN (which Redis every Mapper/Federator/Messenger call in this
process actually talks to - see config_store.py's docstring for how a
change here takes effect immediately, no restart). Backs the Settings page.

redis_auth_token is never echoed back in a GET/PUT response - only whether
one is currently set (redis_auth_token_set). PUT only overwrites it when
the caller actually sends a non-empty value, so leaving the field blank in
the UI doesn't wipe out an existing token.
"""
import logging

from fastapi import APIRouter, Depends

import config_store
from auth_dep import require_admin
from session import Session

router = APIRouter()


def _response_shape(cfg: dict) -> dict:
    return {
        "gustavo_api_url": cfg.get("GUSTAVO_API_URL", ""),
        "redis_host": cfg.get("REDIS_HOST", ""),
        "redis_port": cfg.get("REDIS_PORT", ""),
        "redis_auth_token_set": bool(cfg.get("REDIS_AUTH_TOKEN")),
    }


def _test_redis() -> tuple[bool, str | None]:
    try:
        from scarlets.utils.ScarletUtils import redisConnect
        redisConnect().ping()
        return True, None
    except Exception as exc:
        logging.error(f"config: redis connection test failed: {exc}")
        return False, str(exc)


@router.get("")
async def get_config():
    return {"error": False, "response": _response_shape(config_store.get())}


@router.put("")
async def update_config(body: dict, session: Session = Depends(require_admin)):
    partial: dict = {}
    if "gustavo_api_url" in body and body["gustavo_api_url"] is not None:
        partial["GUSTAVO_API_URL"] = body["gustavo_api_url"]
    if "redis_host" in body and body["redis_host"] is not None:
        partial["REDIS_HOST"] = body["redis_host"]
    if "redis_port" in body and body["redis_port"] is not None:
        partial["REDIS_PORT"] = str(body["redis_port"])
    # Only overwrite the token when a real, non-empty value was sent -
    # see module docstring.
    if body.get("redis_auth_token"):
        partial["REDIS_AUTH_TOKEN"] = body["redis_auth_token"]

    if not partial:
        return {"error": True, "response": "no recognized fields in request body"}

    cfg = config_store.update(partial)

    redis_ok, redis_error = _test_redis()
    response = _response_shape(cfg)
    response["redis_ok"] = redis_ok
    response["redis_error"] = redis_error
    return {"error": False, "response": response}
