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
import asyncio
import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor

import requests
from fastapi import FastAPI, Header, HTTPException

from data_connectors.base import Connector

logging.basicConfig(level=logging.INFO)

# TODO: BROKER_POOL_SIZE bounds how many queries this broker runs at once,
# but every connector still opens (and closes) a fresh connection per
# query - no pooling at the data-source level yet. Fine for queries in
# the low seconds; a real production MS SQL query has taken 17 minutes,
# which this pool alone doesn't fix - a submit/poll job-id model (query
# returns immediately, caller polls for the result) is the real answer
# for that case and is deliberately not built here. See the
# "Local-First Data Access" plan (2026-09) for the full reasoning.
COMPOSER_API_URL = os.environ.get("COMPOSER_API_URL", "").rstrip("/")
DATA_SOURCE_NAME = os.environ.get("DATA_SOURCE_NAME", "")
BROKER_POOL_SIZE = int(os.environ.get("BROKER_POOL_SIZE", "4"))

# Each connector module is imported lazily, inside its own branch below -
# not at module level - so a broker deployed for one connector type never
# needs another type's system dependencies importable at all (e.g. a
# non-mssql broker shouldn't need pyodbc/unixODBC installed just to start,
# and a non-pi broker shouldn't need the pitalk package importable).
_KNOWN_CONNECTOR_TYPES = ("mssql", "pi", "influx", "postgres", "mysql", "redis", "csv", "excel")


def _load_connector() -> Connector:
    connector_type = os.environ.get("BROKER_CONNECTOR_TYPE", "")
    if connector_type == "mssql":
        from data_connectors.mssql import MssqlConnector
        return MssqlConnector()
    if connector_type == "pi":
        from data_connectors.pi import PiConnector
        return PiConnector()
    if connector_type == "influx":
        from data_connectors.influx import InfluxConnector
        return InfluxConnector()
    if connector_type == "postgres":
        from data_connectors.postgres import PostgresConnector
        return PostgresConnector()
    if connector_type == "mysql":
        from data_connectors.mysql import MysqlConnector
        return MysqlConnector()
    if connector_type == "redis":
        from data_connectors.redis_connector import RedisConnector
        return RedisConnector()
    if connector_type == "csv":
        from data_connectors.csv_connector import CsvConnector
        return CsvConnector()
    if connector_type == "excel":
        from data_connectors.excel_connector import ExcelConnector
        return ExcelConnector()
    raise ValueError(
        f"BROKER_CONNECTOR_TYPE={connector_type!r} is not a known connector "
        f"(known: {_KNOWN_CONNECTOR_TYPES})"
    )


class Broker:
    """
    Owns one Connector and a bounded thread pool - every /query call runs
    the connector's (blocking) .query() on that pool instead of directly
    on the FastAPI request-handling path, so N concurrent callers actually
    run in parallel (up to pool_size) instead of serializing on uvicorn's
    single asyncio event loop. Found this the hard way: /query was
    `async def` calling straight-through blocking code (pyodbc/psycopg2/
    pymysql/requests/redis-py, no `await`, no thread offload) - an async
    handler that blocks the event loop blocks it for every other request
    too, not just the one in flight.
    """

    def __init__(self, connector: Connector, pool_size: int = 4):
        self._connector = connector
        self._executor = ThreadPoolExecutor(max_workers=pool_size)

    def submit_query(self, payload: dict) -> Future:
        return self._executor.submit(self._connector.query, payload)


app = FastAPI(title="scarlet-composer data-source broker")
_broker: Broker | None = None


@app.on_event("startup")
async def _startup():
    global _broker
    if not COMPOSER_API_URL:
        logging.critical("COMPOSER_API_URL is not set - every /query call will fail authorization")
    if not DATA_SOURCE_NAME:
        logging.critical("DATA_SOURCE_NAME is not set - must match this broker's own registration in composer-api")
    connector = _load_connector()
    _broker = Broker(connector, pool_size=BROKER_POOL_SIZE)
    logging.info(
        f"broker ready: data_source={DATA_SOURCE_NAME!r} connector={type(connector).__name__} "
        f"pool_size={BROKER_POOL_SIZE}"
    )


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
        # Runs on the Broker's own thread pool, not this coroutine's
        # thread - wrap_future() lets the event loop keep serving other
        # requests (health checks, other callers' /query calls) while
        # this one's connector.query() is in flight, instead of blocking
        # everything until it returns.
        result = await asyncio.wrap_future(_broker.submit_query(body))
        return {"error": False, "response": result}
    except Exception as exc:
        logging.error(f"query failed: {exc}")
        return {"error": True, "response": str(exc)}
