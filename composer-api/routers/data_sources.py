"""
/api/data-sources — registry + access-policy authority for data-source
brokers. Never in the query data path (see docker/broker/'s own docstring
for the full architecture) - this router only ever answers "what brokers
exist" and "is this caller allowed to use this one", never anything a
query itself needs.

GET  /api/data-sources                  -> list, filtered to the caller's
                                            grants for non-admins (mirrors
                                            gustavo's own GET /api/apps
                                            behavior exactly).
POST/PUT/DELETE /api/data-sources[/{name}] -> require_admin-gated registry CRUD.
POST /api/data-sources/{name}/authorize -> the one endpoint a *broker*
                                            calls, forwarding the querying
                                            worker's own Bearer token as
                                            this call's own auth. Checks
                                            that token's username/is_admin/
                                            groups (see session.py) against
                                            the registered grants. No data-
                                            source credential is involved
                                            anywhere in this file.
"""
import logging

from fastapi import APIRouter, Depends

import data_sources_store
from auth_dep import require_admin, verify_session
from session import Session

router = APIRouter()


def _is_authorized(session: Session, entry: dict) -> bool:
    if session.is_admin:
        return True
    if session.username in entry.get("allowed_users", []):
        return True
    return bool(set(session.groups) & set(entry.get("allowed_groups", [])))


def _public_shape(entry: dict) -> dict:
    # No credential field exists on these entries at all (see
    # data_sources_store.py's docstring) - nothing to mask here, unlike
    # the Redis/Gustavo Settings fields.
    return {
        "name": entry["name"],
        "type": entry["type"],
        "broker_url": entry["broker_url"],
        "description": entry["description"],
        "allowed_users": entry["allowed_users"],
        "allowed_groups": entry["allowed_groups"],
    }


@router.get("")
async def list_data_sources(session: Session = Depends(verify_session)):
    try:
        entries = data_sources_store.list_all()
        visible = [e for e in entries if _is_authorized(session, e)]
        return {"error": False, "response": {"data_sources": [_public_shape(e) for e in visible]}}
    except Exception as exc:
        logging.error(f"list_data_sources failed: {exc}")
        return {"error": True, "response": str(exc)}


@router.post("")
async def create_data_source(body: dict, session: Session = Depends(require_admin)):
    name = body.get("name")
    if not name:
        return {"error": True, "response": "name is required"}
    if data_sources_store.get(name) is not None:
        return {"error": True, "response": f"data source '{name}' already exists"}
    try:
        entry = data_sources_store.create(body)
        return {"error": False, "response": _public_shape(entry)}
    except Exception as exc:
        logging.error(f"create_data_source failed: {exc}")
        return {"error": True, "response": str(exc)}


@router.put("/{name}")
async def update_data_source(name: str, body: dict, session: Session = Depends(require_admin)):
    entry = data_sources_store.update(name, body)
    if entry is None:
        return {"error": True, "response": f"data source '{name}' not found"}
    return {"error": False, "response": _public_shape(entry)}


@router.delete("/{name}")
async def delete_data_source(name: str, session: Session = Depends(require_admin)):
    deleted = data_sources_store.delete(name)
    if not deleted:
        return {"error": True, "response": f"data source '{name}' not found"}
    return {"error": False, "response": {"deleted": name}}


@router.post("/{name}/authorize")
async def authorize(name: str, session: Session = Depends(verify_session)):
    entry = data_sources_store.get(name)
    if entry is None:
        return {"error": False, "response": {"authorized": False}}
    return {"error": False, "response": {"authorized": _is_authorized(session, entry)}}
