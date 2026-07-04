from scarlets.utils.RedisLogger import RedisLogger as logging
import os, configparser, time, operator
import numpy as np


class ScarletBase:
    """
    Base class for all Scarlets. Handles env var validation, Redis config,
    and node identity resolution. License activation is not required in the
    open source release — set KEYGEN_PUBLIC_KEY only if running against the
    commercial license server.
    """

    SUM = operator.add
    MUL = operator.mul
    MAX = np.maximum
    MIN = np.minimum
    opArray = [SUM, MUL, MAX, MIN]

    def __init__(self, name="ScarletBase", composer=False):
        self.composer = composer
        self.scarletName = name
        self.configFile = None
        self.config = {}
        self.CHUNK_SIZE = 16 * 1024
        self.MULT = 1000
        self.address = "127.0.0.1"
        self.redisDBHost = ""
        self.redisDBPort = ""
        self.managerHost = ""
        self.managerPort = ""
        self.redisDBPwd = ""
        self.scarletid = ""
        self.scarletDataExpiry = 3600
        self.start_time = None

        if "SCARLET_CONFIG_FILE" in os.environ:
            self.configFile = os.environ["SCARLET_CONFIG_FILE"]
            if not os.path.isfile(self.configFile):
                raise Exception("Config file not found", self.configFile)
            self.config = configparser.ConfigParser()
            self.config.read(self.configFile)
        else:
            logging.warning("SCARLET_CONFIG_FILE not specified, using default values")

        self._initScarlet()

    def _initScarlet(self):
        self.debug = False

        if "APP" in self.config:
            if "DEBUG" in self.config["APP"]:
                self.debug = self.config.getboolean("APP", "DEBUG")
            if "COMPOSER" in self.config["APP"]:
                self.composer = self.config.getboolean("APP", "COMPOSER")

        if "SCARLET" in self.config:
            if "CHUNK_SIZE" in self.config["SCARLET"]:
                self.CHUNK_SIZE = int(self.config["SCARLET"]["CHUNK_SIZE"])
            if "MULT" in self.config["SCARLET"]:
                self.MULT = float(self.config["SCARLET"]["MULT"])

        if not self.composer:
            # APP_ID optional — defaults to "ScarletComposer" for dashboard use
            self.app_id = os.environ.get("APP_ID", "ScarletComposer")
            self.managerHost = os.environ.get("MANAGER_HOST", "")
            self.managerPort = os.environ.get("MANAGER_PORT", "")
            self.scarletid = self.app_id + ":" + self.scarletName
            self.start_time = time.time()

            logging.app_id = self.app_id

            if "LOG_EXPIRY_TIME" in os.environ:
                logging.expiry_time = int(os.environ["LOG_EXPIRY_TIME"])

            self.address = self._resolveNodeAddress()
            logging.nodeIp = self.address

        if not self.debug:
            self.redisDBHost = os.environ.get("REDIS_HOST") or os.environ.get("REDIS_DB_HOST")
            self.redisDBPort = os.environ.get("REDIS_PORT") or os.environ.get("REDIS_DB_PORT")
            self.redisDBPwd = os.environ.get("REDIS_AUTH_TOKEN") or os.environ.get("REDIS_DB_PWD")

            if not self.redisDBHost:
                raise Exception("REDIS_HOST or REDIS_DB_HOST not set in os.environ")
            if not self.redisDBPort:
                raise Exception("REDIS_PORT or REDIS_DB_PORT not set in os.environ")
            if not self.redisDBPwd:
                raise Exception("REDIS_AUTH_TOKEN or REDIS_DB_PWD not set in os.environ")

            if "SCARLET_DATA_EXPIRY" in os.environ:
                self.scarletDataExpiry = os.environ["SCARLET_DATA_EXPIRY"]

        self.defaultAccount = self.address
        self.defaultPassword = ""

    def _resolveNodeAddress(self):
        """
        Resolve stable node address in priority order:
          1. NODE_ADDRESS env var (set explicitly by Gustavo app config)
          2. /api/v2/getNodeInfo endpoint on the Scarlet Composer Tornado server
          3. Local hostname IP (fallback)
        """
        node_address = os.environ.get("NODE_ADDRESS")
        if node_address:
            return node_address

        if self.managerHost and self.managerPort and hasattr(self, "app_id"):
            try:
                import requests
                url = f"http://{self.managerHost}:{self.managerPort}/api/v2/getNodeInfo"
                resp = requests.get(url, params={"app_id": self.app_id}, timeout=3)
                if resp.status_code == 200:
                    data = resp.json()
                    resolved = data.get("node_address")
                    if resolved:
                        os.environ["NODE_ADDRESS"] = resolved
                        device_group = data.get("device_group")
                        if device_group:
                            os.environ.setdefault("DEVICE_GROUP", device_group)
                        return resolved
            except Exception as e:
                logging.warning(f"Could not resolve node address via getNodeInfo: {e}")

        try:
            import socket
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"

    def acquireMode(self):
        """
        Returns the backend mode for this scarlet.
        Open source release supports Redis only ('pure-hybrid').
        IPFS and blockchain backends are not included in this release.
        """
        return "pure-hybrid"

    def performOperation(self, modelLocal, globalModel, operation):
        if operation not in self.opArray:
            return None
        return operation(modelLocal, globalModel)

    def printLog(self):
        logging.info(f"SCARLET_CONFIG_FILE={self.configFile}")
        logging.info(f"DEBUG={self.debug}, CHUNK_SIZE={self.CHUNK_SIZE}, MULT={self.MULT}")
        if not self.debug:
            logging.info(f"REDIS_DB={self.redisDBHost}:{self.redisDBPort}")
