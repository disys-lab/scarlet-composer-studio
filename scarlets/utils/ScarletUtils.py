import logging, os, redis, json, time


def redisConnect(decode_responses=False):
    """
    Create a Redis client from environment variables.

    Parameters
    ----------
    decode_responses : bool, optional
        Passed through to `redis.StrictRedis` - `True` decodes replies
        to `str`, `False` (the default) leaves them as `bytes`.

    Returns
    -------
    redis.StrictRedis

    Raises
    ------
    Exception
        If `REDIS_HOST`/`REDIS_PORT`/`REDIS_AUTH_TOKEN` (or their
        `REDIS_DB_*` aliases) aren't set in the environment.
    """
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
    scarlet_type : str
        ``"mapper"`` or ``"messaging"``.
    description : str, optional
        Natural language contract - data format, key naming, usage
        intent. Fed directly into agent context windows.
    attributes : dict, optional
        Mode, expiry, and any other scarlet attributes. Defaults to
        ``{"mode": "redis-scarlet"}`` if not given.
    expiry : int or None, optional
        TTL in seconds for the definition key. `None` (the default)
        means the definition persists indefinitely.
    overwrite : bool, optional
        If `False` (the default), skip the write when the key already
        exists, so a head agent's rich description isn't clobbered by
        workers joining later with an empty description.
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
