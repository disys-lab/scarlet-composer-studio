import redis
import pickle
from scarlets.utils.RedisLogger import RedisLogger as logging

from scarlets.types.ScarletBase import ScarletBase

class ContractBase:
    """
    Base class for all Contracts — holds Redis connection details and (open-source-inert) contract metadata.

    `contractABI`/`contractHandle`/`contractAddress` are vestigial in the
    open source release: they only apply to the commercial pure-decent/
    full-decent (smart-contract-backed) modes, not available here.
    `contractMode` is always ``"pure-hybrid"`` in this release (see
    `scarlets.types.ScarletBase.ScarletBase.acquireMode`).

    Parameters
    ----------
    contractname : str
        Name of the contract (matches the owning scarlet's name).
    redisDBHost : str
        Redis hostname or IP.
    redisDBPort : str
        Redis port.
    redisDBPwd : str
        Redis password.
    defaultAccount : str
        Local default account address.
    defaultPassword : str
        Default account password.
    debug : bool
        Whether the owning scarlet is running in debug mode.
    scarletDataExpiry : int
        TTL in seconds for values this contract writes to Redis.

    Attributes
    ----------
    contractName : str
    contractABI : dict
        Inert in this release — see class summary.
    contractHandle : object
        Inert in this release — see class summary.
    contractAddress : str
        Inert in this release — see class summary.
    redisDBHost, redisDBPort, redisDBPwd : str
    debug : bool
    defaultAccount, defaultPassword : str
    scarletDataExpiry : int
    contractMode : str
        Always ``"pure-hybrid"`` in the open source release.

    Methods
    -------
    getContractDetails()
        Fetch this contract's data from Redis.
    """

    def __init__(self, contractname, redisDBHost, redisDBPort, redisDBPwd, defaultAccount, defaultPassword, debug,scarletDataExpiry):
        self.contractName = contractname
        self.contractABI = ""
        self.contractHandle = ""
        self.contractAddress = ""
        self.redisDBHost = redisDBHost
        self.redisDBPort = redisDBPort
        self.redisDBPwd = redisDBPwd
        self.defaultAccount = defaultAccount
        self.defaultPassword = defaultPassword
        self.scarletDataExpiry = scarletDataExpiry
        # TODO: This checks for activation twice! Replace and make more elegant.
        self.contractMode = ScarletBase(contractname).acquireMode()
        self.debug = debug

    def getContractDetails(self):
        """
        Fetch and unpickle this contract's data from Redis.

        Returns
        -------
        object
            The unpickled value stored under `contractName`, or `None`
            (logged as critical) if the key doesn't exist or Redis is
            unreachable.
        """
        try:
            r = redis.StrictRedis(host=self.redisDBHost, port=self.redisDBPort, password=self.redisDBPwd)  # ,password=redisDBPass)
            rawContractData = r.get(self.contractName)
            if rawContractData == None:
                raise Exception("Scarlet {} not found in remote DB".format(self.contractName))
            contractData = pickle.loads(rawContractData)
            return contractData
        except:
            logging.critical("could not establish connection to remote DB {}".format(str(self.redisDBHost)+":"+str(self.redisDBPort)))


    def load(self):
        """No-op in the base class; overridden by subclasses that need to load contract state."""
        pass

