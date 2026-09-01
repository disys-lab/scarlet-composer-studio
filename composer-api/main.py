"""
scarlet-composer FastAPI application factory.

Start with:
    uvicorn main:app --reload --port 8000

Replaces Streamlit's direct-Redis-access pages with a real HTTP API a
browser frontend (composer-ui/) can call. Reuses `scarlets` as an
installed dependency (Messenger, redisConnect) rather than reimplementing
Redis access - see routers/agents.py's docstring for the specific bug
this fixes versus the old Streamlit page.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config_store
from auth_dep import verify_session
from routers import agents as agents_router
from routers import auth as auth_router
from routers import config as config_router
from routers import dashboard as dashboard_router
from routers import scarlets as scarlets_router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config_store.load()
    yield


app = FastAPI(
    title="scarlet-composer API",
    description="FastAPI backend for the scarlet-composer operator UI",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow the Next.js dev server and the same-origin production proxy,
# matching gustavo's own api/main.py convention.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router, prefix="/api/auth", tags=["auth"])
app.include_router(config_router.router, prefix="/api/config", tags=["config"])
# Real data endpoints - gated by verify_session (a no-op pass-through
# admin session when AUTH_ENABLED=false, the default - see auth_dep.py).
app.include_router(
    dashboard_router.router, prefix="/api/dashboard", tags=["dashboard"],
    dependencies=[Depends(verify_session)],
)
app.include_router(
    agents_router.router, prefix="/api/agents", tags=["agents"],
    dependencies=[Depends(verify_session)],
)
app.include_router(
    scarlets_router.router, prefix="/api/scarlets", tags=["scarlets"],
    dependencies=[Depends(verify_session)],
)


@app.get("/health")
async def health():
    return {"status": "ok"}
