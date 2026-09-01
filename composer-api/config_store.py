"""
YAML-backed config singleton for composer-api - mirrors gustavo/api/config_store.py's
pattern (load()/get()/update(), DEFAULTS merged with whatever's on disk).

Holds GUSTAVO_API_URL (login delegation) and REDIS_HOST/PORT/AUTH_TOKEN -
the latter three are also pushed into os.environ on every load()/update()
(see _sync_env()) because scarlets' own ScarletUtils.redisConnect() -
which every Mapper/Federator/Messenger/register_scarlet_definition call in
this process ultimately goes through - reads those straight from
os.environ on every single call, not once at import time. That's what
makes a live Settings-page update take effect on the very next Redis
operation, no container restart required.
"""
import logging
import os
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(os.environ.get("COMPOSER_API_CONFIG", "/etc/scarlet-composer/composer_api.yaml"))

DEFAULTS: dict[str, Any] = {
    "GUSTAVO_API_URL": os.environ.get("GUSTAVO_API_URL", ""),
    "REDIS_HOST": os.environ.get("REDIS_HOST", ""),
    "REDIS_PORT": os.environ.get("REDIS_PORT", "6379"),
    "REDIS_AUTH_TOKEN": os.environ.get("REDIS_AUTH_TOKEN", ""),
}

# Keys synced into os.environ - see module docstring.
_ENV_SYNCED_KEYS = ("REDIS_HOST", "REDIS_PORT", "REDIS_AUTH_TOKEN")

_config: dict[str, Any] = {}


def _sync_env(cfg: dict[str, Any]) -> None:
    for key in _ENV_SYNCED_KEYS:
        value = cfg.get(key)
        if value:
            os.environ[key] = str(value)


def load() -> dict[str, Any]:
    """Read YAML from disk, merge with DEFAULTS, and return the result."""
    global _config
    merged = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open() as f:
                on_disk = yaml.safe_load(f) or {}
            merged.update({k: v for k, v in on_disk.items() if v is not None})
        except Exception as exc:
            logging.error(f"config_store: failed to load {CONFIG_PATH}: {exc}")
    _config = merged
    _sync_env(_config)
    return _config


def get() -> dict[str, Any]:
    """Return the current in-memory config (loads lazily if not yet initialised)."""
    if not _config:
        load()
    return _config


def update(partial: dict[str, Any]) -> dict[str, Any]:
    """Merge *partial* into the config, persist to YAML, and sync os.environ."""
    global _config
    if not _config:
        load()
    _config.update(partial)
    _persist()
    _sync_env(_config)
    return _config


def _persist() -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CONFIG_PATH.open("w") as f:
            yaml.safe_dump(_config, f, default_flow_style=False)
    except Exception as exc:
        logging.error(f"config_store: failed to write {CONFIG_PATH}: {exc}")
