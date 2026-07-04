import redis
import pickle
from scarlets.utils.RedisLogger import RedisLogger as logging

from scarlets.types.ScarletBase import ScarletBase

class ContractBase:
    """
    Base class for all types of Contracts. Contains all Contract attributes

    Attributes
    ----------
    contractName : string
        name of the contract

    contractABI : dict
        MODE APPLICABILITY: pure-decent, full-decent
        contract Application Binary Interface, relevant for SmartContracts, contains signatures of Solidity functions

    contractHandle : ethereum contract handle
        MODE APPLICABILITY: pure-decent, full-decent
        the object yielded by web3.eth.contract(abi=contractABI, bytecode=contractBin), serves as a handle to invoke
        SmartContract functions

    contractAddress : string
        MODE APPLICABILITY: pure-decent, full-decent
        the hexstring representing the contract address obtained during deployment

    redisDBHost : string
        the IP or hostname hosting redis

    redisDBPort : string
        the port for redis

    redisDBPwd : string
        the password for redis.

    debug : boolean
        the flag that determines whether scarlet being invoked in debug mode.
        debug mode is usually for local development debugging

    defaultAccount : string
        the local default account address

    defaultPassword : string
        the default account password. right now hardcoded

    contractMode : string
        the contract mode (set during deployment) obtained from redis during runtime

    Methods
    -------
    * `getContractDetails()`
        Obtains the contract details from redis

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
        Obtains the contract details from redis
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
        pass

