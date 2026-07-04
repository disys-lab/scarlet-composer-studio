import logging, os, redis, json, time


def redisConnect(decode_responses=False):
    """Create and return a Redis client from environment variables."""
    redis_host = os.environ.get("REDIS_HOST") or os.environ.get("REDIS_DB_HOST")
    redis_port = os.environ.get("REDIS_PORT") or os.environ.get("REDIS_DB_PORT")
    redis_pwd = os.environ.get("REDIS_AUTH_TOKEN") or os.environ.get("REDIS_DB_PWD")

    if not redis_host:
        logging.critical("REDIS_HOST or REDIS_DB_HOST not set in os.environ")
        raise Exception("REDIS_HOST or REDIS_DB_HOST not set in os.environ")
    if not redis_port:
        logging.critical("REDIS_PORT or REDIS_DB_PORT not set in os.environ")
        raise Exception("REDIS_PORT or REDIS_DB_PORT not set in os.environ")
    if not redis_pwd:
        logging.critical("REDIS_AUTH_TOKEN or REDIS_DB_PWD not set in os.environ")
        raise Exception("REDIS_AUTH_TOKEN or REDIS_DB_PWD not set in os.environ")

    return redis.StrictRedis(
        host=str(redis_host),
        port=int(redis_port),
        password=str(redis_pwd),
        decode_responses=decode_responses,
    )


def register_scarlet_definition(
    scarlet_name,
    scarlet_type,
    description="",
    attributes=None,
    expiry=None,
    overwrite=False,
):
    """
    Write a scarlet definition to Redis under scarlet_definition_{scarlet_name}.

    Called automatically by Mapper and Messenger on instantiation so
    agents can discover and reason about available scarlets without a CLI deploy
    step. Also called by ScarletHandler.deployScarlets() with overwrite=True.

    Parameters
    ----------
    scarlet_name : str
    scarlet_type : str       "mapper" or "messaging"
    description  : str       Natural language contract — data format, key naming,
                             usage intent. Fed directly into agent context windows.
    attributes   : dict      Mode, expiry, and any other scarlet attributes.
    expiry       : int|None  TTL in seconds for both the definition key and data.
                             None means the definition persists indefinitely.
    overwrite    : bool      If False (default), skip write when the key already
                             exists so a head agent's rich description is not
                             clobbered by workers joining later.
    """
    try:
        r = redisConnect(decode_responses=True)
        key = f"scarlet_definition_{scarlet_name}"

        if not overwrite and r.exists(key):
            return

        app_id       = os.environ.get("APP_ID", "unknown")
        node_address = os.environ.get("NODE_ADDRESS", "")
        created_by   = f"{app_id}_{node_address}" if node_address else app_id

        definition = {
            "scarlet_type":       scarlet_type,
            "scarlet_name":       scarlet_name,
            "scarlet_attributes": attributes or {"mode": "redis-scarlet"},
            "description":        description,
            "created_by":         created_by,
            "created_at":         time.time(),
            "app_id":             app_id,
            "node_address":       node_address,
        }

        r.set(key, json.dumps(definition))
        if expiry:
            r.expire(key, int(expiry))

    except Exception as e:
        logging.warning(f"Could not register scarlet definition for '{scarlet_name}': {e}")
