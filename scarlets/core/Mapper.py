from scarlets.types.RedisScarlet import RedisScarlet
from scarlets.utils.RedisLogger import RedisLogger as logging
from scarlets.utils.ScarletUtils import register_scarlet_definition
import time


class Mapper(RedisScarlet):
    """
    Mapper Scarlet maps keys to values.

    Delegates all storage operations to a RedisScarlet backend.
    In the open source release only pure-hybrid (Redis) mode is supported.

    Methods
    -------
    Map(modelLocal, key)       — write a value to a key
    AllGather(modelLocal=None) — read all key-value pairs
    Reduce(modelLocal, op)     — AllGather + fold with op
    resetAll(modelLocal)       — overwrite all keys
    clearAll()                 — delete all keys
    """

    def __init__(self, scarletName, description=""):
        self.super = RedisScarlet(scarletName)
        register_scarlet_definition(
            scarlet_name=scarletName,
            scarlet_type="mapper",
            description=description,
            attributes={"mode": "redis-scarlet"},
            expiry=self.super.scarletDataExpiry,
        )

    def refresh(self):
        """Reload the Redis contract for the next operation."""
        self.super.loadContract()

    def _registerNewKey(self, key):
        """registers new key by calling the corresponding underlying contract function

        Attributes
        ----------
        key : string
            value of key to be registered

        """
        keyRegisterSuccess = self.super.contract.registerNewKey(key)
        return keyRegisterSuccess

    def Map(self, modelLocal, key, timeseries=False):

        """maps model parameters to a given key

        Attributes
        ----------
        modelLocal : numpy array
            the content concerning modelLocal

        key : string
            value of key to be registered

        timeseries : boolean
            whether to store these as time series data or not

        Returns
        -------

        successChunksList : list
            concerns the chunks which were successfully mapped

        status : boolean
            status of the Map operation

        exception : Exception
            exception if any else it will be None

        """

        if timeseries:
            timestamp = int(time.time())
            key = f"{key}:{timestamp}"

            self.super.loadContract()  # _registerNewKey(key)
            self._registerNewKey(key)

        successChunksList = []
        try:
            if not self.super.debug:
                self.refresh()
            successChunksList = self.super.Push(modelLocal, key, [])
        except Exception as exception:
            logging.error("{}.Map failed".format(self.super.scarletName))
            return successChunksList, False, exception
        return successChunksList, True, None

    def AllGather(self, modelLocal=None):
        """Performs an AllGather operation in which all the key-value pairs are obtained from the decentralized
        infrastructure.

        Attributes
        ----------
        modelLocal : numpy array
            the content concerning modelLocal

        Returns
        -------

        allgather_dict : dict
            the dictionary containing all key value pairs

        status : boolean
            status of the Map operation

        exception : Exception
            exception if any else it will be None

        """
        allgather_dict = {}
        try:
            if not self.super.debug:
                self.refresh()

            mapperLength = self.super.contract.getMapperLength()
            for key_index in range(int(mapperLength)):
                key = self.super.contract.getKey(key_index)
                modelOut, status = self.super.Pull(modelLocal, key)
                if not status:
                    logging.error(
                        "{}.AllGather.Pull failed for key :{}".format(
                            self.super.scarletName, key
                        )
                    )
                allgather_dict[key] = modelOut

            return allgather_dict, True, None

        except Exception as exception:
            logging.error(
                "{}.AllGather failed with exception {}".format(
                    self.super.scarletName, exception
                )
            )
            return allgather_dict, False, exception

    def Reduce(self, modelLocal, op):
        """Performs a Reduce operation which comprises of an AllGather followed by an operation on all the values
        obtained thus far. The choice of operations is SUM,MAX,MIN,MULT. In case of MAX,MIN and MULT it will be an
        element wise operation.

        Attributes
        ----------
        modelLocal : numpy array
            the content concerning modelLocal

        op : operation
            any one of the 4 operations SUM,MAX,MIN,MULT

        Returns
        -------

        sumV : numpy array
            final value after carrying out the operation sequentially on all values.

        status : boolean
            status of the Map operation

        exception : Exception
            exception if any else it will be None

        """
        sumV = modelLocal
        allgather_dict, status, exception = self.AllGather(modelLocal)
        if status:
            for key in allgather_dict.keys():
                sumV = self.super.performOperation(allgather_dict[key], sumV, op)
            return sumV, status, None
        else:
            return sumV, status, exception

    def resetAll(self, modelLocal):
        """Resets all the key-value pairs

        Attributes
        ----------
        modelLocal : numpy array
            the content concerning modelLocal

        Returns
        -------

        successChunksList : list
            concerns the chunks which were successfully reset

        exception : Exception
            exception if any else it will be None

        """
        successChunksList = []
        try:
            if not self.super.debug:
                self.refresh()
            mapperLength = self.super.contract.getMapperLength()
            for key_index in range(int(mapperLength)):
                key = self.super.contract.getKey(key_index)
                successChunksList = self.super.Push(modelLocal, key)
        except Exception as exception:
            logging.error("{}.resetAll failed".format(self.super.scarletName))
            return successChunksList, exception
        return successChunksList, None

    def clearAll(self):
        """Clears all the key-value pairs

        Attributes
        ----------

        Returns
        -------

        successChunksList : list
            concerns the chunks which were successfully reset

        exception : Exception
            exception if any else it will be None

        """
        successChunksList = []
        try:
            if not self.super.debug:
                self.refresh()
            mapperLength = self.super.contract.getMapperLength()
            for key_index in range(int(mapperLength)):
                key = self.super.contract.getKey(key_index)
                clearSuccess = self.super.Clear(key)
                successChunksList.append(clearSuccess)
            self.super.ClearAll()
        except Exception as exception:
            logging.error("{}.clearAll failed {}".format(self.super.scarletName,exception))
            return successChunksList, exception
        return successChunksList, None