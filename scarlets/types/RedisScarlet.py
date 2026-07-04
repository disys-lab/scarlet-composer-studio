from scarlets.contract.RedisContract import RedisContract
from scarlets.types.ScarletBase import ScarletBase
from scarlets.utils.RedisLogger import RedisLogger as logging
import pickle, zlib


class RedisScarlet(ScarletBase):
    """
    Scarlet class for pure-hybrid mode, i.e. storage and pointer on the blockchain

    Attributes
    ----------

    super : ScarletBase
        superclass is ScarletBase

    lastUpdatedTime : list
        list of unix timestamp for each chunk part of the model

    contract : Contract
        the contract object that handles communication with the SmartContracts

    Methods
    -------

    * `_verifyScarletParameters()`
        Verifies whether scarlet parameters match

    * `loadContract()`
        Loads contract details from remote DB

    * `Pull(modelLocal, key="0x0", calcWD=False, average=False)`
        Pull the global model from chain and update the local model

    * `Push( modelLocal, key="0x0", wait4Tx=None)`
        Push the local model to the chain.

    """

    def __init__(self, scarletName):

        ScarletBase.__init__(self, scarletName)
        self.scarletName = scarletName
        self.contract = None

    def loadContract(self):
        self.contract = RedisContract(
            self.scarletName,
            self.redisDBHost,
            self.redisDBPort,
            self.redisDBPwd,
            self.defaultAccount,
            self.defaultPassword,
            self.debug,
            self.scarletDataExpiry,
        )

    def Pull(
        self,
        modelLocal,
        key="0x0",
        average=False,
    ):

        """
        Pull the global model from chain and update the local model.

        Parameters
        ----------
        modelLocal : numpy array
            A unidimensional numpy array representing the local estimate
        key: string
            Used as key for Mapper
        calcWD : bool
            Boolean indicating whether to calculate weight difference with the global model
        average : bool
            Boolean indicating whether to average the global model with the local model or not

        Returns
        -------
        modelOut:
            The updated model
        numUpdatedChunks:
            The number of chunks which were successfully pulled from global model

        """

        val = self.contract.checkChunkExists(key, 0)
        if val:

            modelBytes = self.contract.getChunk(key, 0)

            modelBytes = zlib.decompress(modelBytes)
            modelOut = pickle.loads(modelBytes)

            return modelOut, True
        else:
            logging.error("chunk key: {} not found".format(key))
            return modelLocal, False

    def Push(self, modelLocal, key="0x0", wait4Tx=None):
        """
        Push the local model to the chain.

        Parameters
        ----------
        modelLocal : numpy array
            A unidimensional numpy array representing the local estimate
        key: string
            Used as key for Mapper
        wait4Tx (optional): list
            contains the wait4Tx bool as well as wait4TxRecieptTime
            If empty, the config default is taken


        Returns
        -------
        successChunksList:
            List with one element, either 0/1 depending on whether the push was successful or not
        """

        # check if any debug values have been sent in wait4Tx

        modelBinCompr = pickle.dumps(modelLocal, protocol=pickle.HIGHEST_PROTOCOL)
        modelBinCompr = zlib.compress(modelBinCompr, level=9)

        status, exception = self.contract.setChunk(
            key, 0, modelBinCompr, self.address
        )

        if not status:
            logging.error("fail to set chunk for key: {}".format(key))

        return [status]

    def Clear(self, key="0x0", wait4Tx=None):
        """
        Clears the scarlet.

        Parameters
        ----------
        key: string
            Used as key for Mapper
        wait4Tx (optional): list
            contains the wait4Tx bool as well as wait4TxRecieptTime
            If empty, the config default is taken


        Returns
        -------
        successChunksList:
            List with one element, either 0/1 depending on whether the push was successful or not
        """

        # check if any debug values have been sent in wait4Tx


        status, exception = self.contract.clearChunk(
            key, 0
        )

        if not status:
            logging.error("fail to clear chunk for key: {}".format(key))

        return [status]


    def ClearAll(self, wait4Tx=None):
        """
        Clear all data of the scarlet.

        Parameters
        ----------

        wait4Tx (optional): list
            contains the wait4Tx bool as well as wait4TxRecieptTime
            If empty, the config default is taken


        Returns
        -------
        successChunksList:
            List with one element, either 0/1 depending on whether the push was successful or not
        """

        # check if any debug values have been sent in wait4Tx


        status, exception = self.contract.clearAll()

        if not status:
            logging.error("fail to clear all elements of key exception: {}".format(exception))

        return [status]
