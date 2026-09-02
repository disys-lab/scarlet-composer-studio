"""
Data-source broker — fronts exactly one data source, deployed co-located
with it (like a Gustavo app, wherever that data source actually lives).

Never verifies a caller's identity itself, and never holds any Nebula
credential: a caller (a worker, via HarnessContext.query_data_source())
already authenticated to composer-api separately and presents that
composer session token here as Bearer auth. This process's only auth-
related job is one cheap forwarded call to composer-api's own
POST /api/data-sources/{name}/authorize with that same token - composer-api
already fully vetted it at login time (delegated to Gustavo -> Nebula
then), so this never needs its own elevated Nebula access or Nebula
reachability at all.

What this process *does* hold: its own data-source credential (e.g. an
MS SQL Kerberos ticket, a PI service account), configured entirely via its
own env vars at deploy time - never touches composer-api's config store,
never returned to anyone over any API. Query requests and results only
ever flow directly between the caller and this process - composer-api is
never in that path (see docker/broker/'s own docstring for the full
rationale - a real requirement given a data source is often edge-co-
located with the specific worker that needs it, not centralized where
composer-api runs).
"""
import logging
import os

import requests
from fastapi import FastAPI, Header, HTTPException

from connectors.base import Connector

logging.basicConfig(level=logging.INFO)

COMPOSER_API_URL = os.environ.get("COMPOSER_API_URL", "").rstrip("/")
DATA_SOURCE_NAME = os.environ.get("DATA_SOURCE_NAME", "")

# Each connector module is imported lazily, inside its own branch below -
# not at module level - so a broker deployed for one connector type never
# needs another type's system dependencies importable at all (e.g. a
# non-mssql broker shouldn't need pyodbc/unixODBC installed just to start,
# and a non-pi broker shouldn't need the pitalk package importable).
_KNOWN_CONNECTOR_TYPES = ("mssql", "pi", "influx", "postgres", "mysql", "redis")


def _load_connector() -> Connector:
    connector_type = os.environ.get("BROKER_CONNECTOR_TYPE", "")
    if connector_type == "mssql":
        from connectors.mssql import MssqlConnector
        return MssqlConnector()
    if connector_type == "pi":
        from connectors.pi import PiConnector
        return PiConnector()
    if connector_type == "influx":
        from connectors.influx import InfluxConnector
        return InfluxConnector()
    if connector_type == "postgres":
        from connectors.postgres import PostgresConnector
        return PostgresConnector()
    if connector_type == "mysql":
        from connectors.mysql import MysqlConnector
        return MysqlConnector()
    if connector_type == "redis":
        from connectors.redis_connector import RedisConnector
        return RedisConnector()
    raise ValueError(
        f"BROKER_CONNECTOR_TYPE={connector_type!r} is not a known connector "
        f"(known: {_KNOWN_CONNECTOR_TYPES})"
    )


app = FastAPI(title="scarlet-composer data-source broker")
_connector: Connector | None = None


@app.on_event("startup")
async def _startup():
    global _connector
    if not COMPOSER_API_URL:
        logging.critical("COMPOSER_API_URL is not set - every /query call will fail authorization")
    if not DATA_SOURCE_NAME:
        logging.critical("DATA_SOURCE_NAME is not set - must match this broker's own registration in composer-api")
    _connector = _load_connector()
    logging.info(f"broker ready: data_source={DATA_SOURCE_NAME!r} connector={type(_connector).__name__}")


@app.get("/health")
async def health():
    return {"status": "ok"}


def _authorized(bearer_token: str) -> bool:
    try:
        resp = requests.post(
            f"{COMPOSER_API_URL}/api/data-sources/{DATA_SOURCE_NAME}/authorize",
            headers={"Authorization": f"Bearer {bearer_token}"},
            timeout=10,
        )
    except Exception as exc:
        logging.error(f"authorize check failed: could not reach composer-api at {COMPOSER_API_URL}: {exc}")
        return False
    if resp.status_code != 200:
        logging.warning(f"authorize check: composer-api returned HTTP {resp.status_code}")
        return False
    data = resp.json()
    return bool(not data.get("error") and data.get("response", {}).get("authorized"))


@app.post("/query")
async def query(body: dict, authorization: str = Header(default="")):
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1]

    if not _authorized(token):
        raise HTTPException(status_code=403, detail=f"Not authorized for data source {DATA_SOURCE_NAME!r}")

    try:
        result = _connector.query(body)
        return {"error": False, "response": result}
    except Exception as exc:
        logging.error(f"query failed: {exc}")
        return {"error": True, "response": str(exc)}
