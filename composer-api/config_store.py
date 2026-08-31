"""
YAML-backed config singleton for composer-api - mirrors gustavo/api/config_store.py's
pattern (load()/get()/update(), DEFAULTS merged with whatever's on disk).

Deliberately minimal right now - just what the Settings page / login
delegation actually needs (GUSTAVO_API_URL). Not a place to move
REDIS_HOST/etc into unless a later pass actually needs that.
"""
import logging
import os
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(os.environ.get("COMPOSER_API_CONFIG", "/etc/scarlet-composer/composer_api.yaml"))

DEFAULTS: dict[str, Any] = {
    "GUSTAVO_API_URL": os.environ.get("GUSTAVO_API_URL", ""),
}

_config: dict[str, Any] = {}


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
    return _config


def get() -> dict[str, Any]:
    """Return the current in-memory config (loads lazily if not yet initialised)."""
    if not _config:
        load()
    return _config


def update(partial: dict[str, Any]) -> dict[str, Any]:
    """Merge *partial* into the config and persist to YAML."""
    global _config
    if not _config:
        load()
    _config.update(partial)
    _persist()
    return _config


def _persist() -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CONFIG_PATH.open("w") as f:
            yaml.safe_dump(_config, f, default_flow_style=False)
    except Exception as exc:
        logging.error(f"config_store: failed to write {CONFIG_PATH}: {exc}")
