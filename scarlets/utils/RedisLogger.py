import logging,time,redis,uuid,inspect,os,json
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(filename)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)

class RedisLogger:
    """
    Static utility for structured, timestamped logging to Redis.

    No constructor — every method is a `@staticmethod`, called directly
    as ``RedisLogger.info(...)`` etc. Also writes through to Python's
    standard `logging` module, so every call is visible on
    stdout/file even without Redis reachable.

    Attributes
    ----------
    nodeIp : str
        This process's node address, used as the ``node`` field on every
        log entry. Set externally (`ScarletBase`/harness's
        `HarnessConfig`) before logging is meaningful; defaults to
        ``"undefined"``.
    expiry_time : int
        TTL in seconds for each log entry written to Redis. Default
        `600`.
    app_id : str
        This process's `APP_ID`, used as the ``app`` field on every log
        entry. Set externally before logging is meaningful; defaults to
        ``"undefined"``.
    """

    nodeIp = "undefined" #default is undefined

    expiry_time = 600 #default 600 secs

    app_id = "undefined"

    @staticmethod
    def redisConnect(decode_responses=False):
        """
        Create a Redis client from environment variables.

        Parameters
        ----------
        decode_responses : bool, optional
            Passed through to `redis.StrictRedis`. Default `False`.

        Returns
        -------
        redis.StrictRedis

        Raises
        ------
        Exception
            If `REDIS_HOST`/`REDIS_PORT`/`REDIS_AUTH_TOKEN` (or their
            `REDIS_DB_*` aliases) aren't set in the environment.
        """
        if "REDIS_DB_HOST" not in os.environ.keys() and "REDIS_HOST" not in os.environ.keys():
            logging.critical("REDIS_DB_HOST/REDIS_HOST not set in os.environ")
            raise Exception("REDIS_DB_HOST/REDIS_HOST not set in os.environ")

        if "REDIS_DB_PORT" not in os.environ.keys() and "REDIS_PORT" not in os.environ.keys():
            logging.critical("REDIS_DB_PORT/REDIS_PORT not set in os.environ")
            raise Exception("REDIS_DB_PORT/REDIS_PORT not set in os.environ")

        if "REDIS_DB_PWD" not in os.environ.keys() and "REDIS_AUTH_TOKEN" not in os.environ.keys():
            logging.critical("REDIS_DB_PWD/REDIS_AUTH_TOKEN not set in os.environ")
            raise Exception("REDIS_DB_PWD/REDIS_AUTH_TOKEN not set in os.environ")

        if "REDIS_DB_HOST" in os.environ.keys():
            redisDBHost = os.environ["REDIS_DB_HOST"]
        else:
            redisDBHost = os.environ["REDIS_HOST"]

        if "REDIS_DB_PORT" in os.environ.keys():
            redisDBPort = os.environ["REDIS_DB_PORT"]
        else:
            redisDBPort = os.environ["REDIS_PORT"]

        if "REDIS_DB_PWD" in os.environ.keys():
            redisDBPwd = os.environ["REDIS_DB_PWD"]
        else:
            redisDBPwd = os.environ["REDIS_AUTH_TOKEN"]

        r = redis.StrictRedis(
            host=str(redisDBHost),
            port=int(redisDBPort),
            password=str(redisDBPwd),
            decode_responses=decode_responses
        )

        return r


    @staticmethod
    def setRedisLog(log_message="",level="DEBUG"):
        """
        Write one structured log entry to Redis.

        Called internally by `debug`/`info`/`warning`/`error`/`critical`
        - not usually called directly.

        Parameters
        ----------
        log_message : str, optional
            The log message.
        level : str, optional
            One of ``"DEBUG"``/``"INFO"``/``"WARNING"``/``"ERROR"``/
            ``"CRITICAL"``. Default ``"DEBUG"``.

        Notes
        -----
        Stores at a fresh ``logs_{uuid4}`` key (never reused), with
        fields ``time``, ``app``, ``node``, ``filename``, ``line``,
        ``level``, ``msg`` - ``filename``/``line`` are the *caller's*
        caller (two frames up from here), i.e. wherever
        `debug`/`info`/etc. was actually called from. Expires after
        `expiry_time` seconds. Silently returns (logging the failure via
        standard `logging`, not raising) if Redis is unreachable.
        """
        try:
            r = RedisLogger.redisConnect(decode_responses=True)
        except Exception as e:
            logging.error("redis connect failed")
            return

        log_msg_id = f"logs_{uuid.uuid4()}"
        # Get the current stack frame
        frame = inspect.stack()[2]  # [1] refers to the immediate caller
        filename = frame.filename  # Get the filename of the caller
        line = frame.lineno  # Get the line number in the caller file
        log_message_dict = {"time":time.time(),
                            "file":filename,
                            "app":RedisLogger.app_id,
                            "node":RedisLogger.nodeIp,
                            "filename": filename,
                            "line": line,
                            "level": level,
                            "msg":log_message,
                            }

        try:
            r.hset(log_msg_id,mapping=log_message_dict)
            r.expire(log_msg_id,RedisLogger.expiry_time)
        except Exception as e:
            logging.error("redis.hset failed for log setting")

    @staticmethod
    def debug(log_message):
        """
        Log at DEBUG level — stdout/file via `logging`, plus Redis via `setRedisLog`.

        Parameters
        ----------
        log_message : str
        """
        logging.debug(log_message)
        RedisLogger.setRedisLog(log_message,"DEBUG")

    @staticmethod
    def info(log_message):
        """
        Log at INFO level — stdout/file via `logging`, plus Redis via `setRedisLog`.

        Parameters
        ----------
        log_message : str
        """
        logging.info(log_message)
        RedisLogger.setRedisLog(log_message,"INFO")

    @staticmethod
    def warning(log_message):
        """
        Log at WARNING level — stdout/file via `logging`, plus Redis via `setRedisLog`.

        Parameters
        ----------
        log_message : str
        """
        logging.warning(log_message)
        RedisLogger.setRedisLog(log_message,"WARNING")

    @staticmethod
    def error(log_message):
        """
        Log at ERROR level — stdout/file via `logging`, plus Redis via `setRedisLog`.

        Parameters
        ----------
        log_message : str
        """
        logging.error(log_message)
        RedisLogger.setRedisLog(log_message,"ERROR")

    @staticmethod
    def critical(log_message):
        """
        Log at CRITICAL level — stdout/file via `logging`, plus Redis via `setRedisLog`.

        Parameters
        ----------
        log_message : str
        """
        logging.critical(log_message)
        RedisLogger.setRedisLog(log_message,"CRITICAL")
