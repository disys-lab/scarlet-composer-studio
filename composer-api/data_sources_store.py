"""
YAML-backed registry of configured data-source brokers - same load/get/
update discipline as config_store.py, but a *collection* (each entry keyed
by name), not a flat singleton.

Deliberately holds no data-source credential at all: {name, type,
broker_url, description, allowed_users, allowed_groups}. The actual
PI/SQL/etc. credential lives only in the broker's own deployment (its own
env vars, set once when that broker is deployed - see docker/broker/), and
is never returned by, sent to, or stored in this API. This store is
authorization *policy* + a directory of where to find each broker - never
anything a query itself needs to pass through.

allowed_users/allowed_groups are checked in routers/data_sources.py's
/authorize endpoint against a caller's Session.username/is_admin/groups
(see session.py) - the same Nebula group-membership data Gustavo's own
apps/device_groups grant checks use (gustavo/api/routers/device_groups.py's
_require_dg_access is the direct precedent for this shape).
"""
import logging
import os
from pathlib import Path
from typing import Any

import yaml

STORE_PATH = Path(os.environ.get("COMPOSER_DATA_SOURCES_CONFIG", "/etc/scarlet-composer/data_sources.yaml"))

_sources: dict[str, dict[str, Any]] = {}
_loaded = False


def _normalize(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": entry["name"],
        "type": entry.get("type", ""),
        "broker_url": entry.get("broker_url", ""),
        "description": entry.get("description", ""),
        "allowed_users": list(entry.get("allowed_users") or []),
        "allowed_groups": list(entry.get("allowed_groups") or []),
    }


def load() -> dict[str, dict[str, Any]]:
    """Read YAML from disk (a list of entries under a top-level
    `data_sources` key) into the in-memory dict, keyed by name."""
    global _sources, _loaded
    sources: dict[str, dict[str, Any]] = {}
    if STORE_PATH.exists():
        try:
            with STORE_PATH.open() as f:
                on_disk = yaml.safe_load(f) or {}
            for entry in on_disk.get("data_sources", []) or []:
                normalized = _normalize(entry)
                sources[normalized["name"]] = normalized
        except Exception as exc:
            logging.error(f"data_sources_store: failed to load {STORE_PATH}: {exc}")
    _sources = sources
    _loaded = True
    return _sources


def list_all() -> list[dict[str, Any]]:
    if not _loaded:
        load()
    return sorted(_sources.values(), key=lambda s: s["name"])


def get(name: str) -> dict[str, Any] | None:
    if not _loaded:
        load()
    return _sources.get(name)


def create(entry: dict[str, Any]) -> dict[str, Any]:
    if not _loaded:
        load()
    normalized = _normalize(entry)
    _sources[normalized["name"]] = normalized
    _persist()
    return normalized


def update(name: str, partial: dict[str, Any]) -> dict[str, Any] | None:
    if not _loaded:
        load()
    existing = _sources.get(name)
    if existing is None:
        return None
    merged = {**existing, **{k: v for k, v in partial.items() if v is not None}}
    normalized = _normalize({**merged, "name": name})
    _sources[name] = normalized
    _persist()
    return normalized


def delete(name: str) -> bool:
    if not _loaded:
        load()
    if name not in _sources:
        return False
    del _sources[name]
    _persist()
    return True


def _persist() -> None:
    try:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with STORE_PATH.open("w") as f:
            yaml.safe_dump({"data_sources": list(_sources.values())}, f, default_flow_style=False)
    except Exception as exc:
        logging.error(f"data_sources_store: failed to write {STORE_PATH}: {exc}")
