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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import agents as agents_router
from routers import dashboard as dashboard_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="scarlet-composer API",
    description="FastAPI backend for the scarlet-composer operator UI",
    version="0.1.0",
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

app.include_router(dashboard_router.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(agents_router.router, prefix="/api/agents", tags=["agents"])


@app.get("/health")
async def health():
    return {"status": "ok"}
