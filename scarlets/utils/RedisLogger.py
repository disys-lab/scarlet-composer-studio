import logging,time,redis,uuid,inspect,os,json
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(filename)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)

class RedisLogger:
    nodeIp = "undefined" #default is undefined

    expiry_time = 600 #default 600 secs

    app_id = "undefined"

    @staticmethod
    def redisConnect(decode_responses=False):
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
        logging.debug(log_message)
        RedisLogger.setRedisLog(log_message,"DEBUG")

    @staticmethod
    def info(log_message):
        logging.info(log_message)
        RedisLogger.setRedisLog(log_message,"INFO")

    @staticmethod
    def warning(log_message):
        logging.warning(log_message)
        RedisLogger.setRedisLog(log_message,"WARNING")

    @staticmethod
    def error(log_message):
        logging.error(log_message)
        RedisLogger.setRedisLog(log_message,"ERROR")

    @staticmethod
    def critical(log_message):
        logging.critical(log_message)
        RedisLogger.setRedisLog(log_message,"CRITICAL")
