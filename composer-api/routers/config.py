"""
/api/config — currently just GUSTAVO_API_URL, the address routers/auth.py
delegates login credential checks to. Backs the Settings page.
"""
from fastapi import APIRouter, Depends

import config_store
from auth_dep import require_admin
from session import Session

router = APIRouter()


@router.get("")
async def get_config():
    cfg = config_store.get()
    return {"error": False, "response": {"gustavo_api_url": cfg.get("GUSTAVO_API_URL", "")}}


@router.put("")
async def update_config(body: dict, session: Session = Depends(require_admin)):
    gustavo_api_url = body.get("gustavo_api_url")
    if gustavo_api_url is None:
        return {"error": True, "response": "gustavo_api_url is required"}
    cfg = config_store.update({"GUSTAVO_API_URL": gustavo_api_url})
    return {"error": False, "response": {"gustavo_api_url": cfg.get("GUSTAVO_API_URL", "")}}
