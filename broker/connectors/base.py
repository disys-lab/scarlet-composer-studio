"""
Connector — the pluggable interface every data-source-specific connector
implements. The broker itself (main.py) never knows about SQL, PI, Redis,
etc. directly - it only ever calls .query(payload) on whichever Connector
its own deployment is configured with (BROKER_CONNECTOR_TYPE env var,
see main.py's _load_connector()).

query() takes a caller-supplied payload and returns a plain JSON-
serializable dict - the *result*, not the credential, not the connection.
The credential this connector uses lives entirely in its own __init__,
read from this process's own env vars - never passed in from a caller,
never returned to one.
"""
from abc import ABC, abstractmethod


class Connector(ABC):
    @abstractmethod
    def query(self, payload: dict) -> dict:
        """Execute payload's query against this connector's configured data
        source and return a JSON-serializable result. Raise on failure -
        main.py's /query handler turns that into a clean error response,
        never a raw stack trace."""
        ...
