from scarlets.types.RedisScarlet import RedisScarlet
from scarlets.utils.RedisLogger import RedisLogger as logging
from scarlets.utils.ScarletUtils import register_scarlet_definition
import time


class Mapper(RedisScarlet):
    """
    Distributed key-value store — workers write independently, any node reads all values.

    Delegates all storage operations to a `RedisScarlet` backend.
    In the open source release only pure-hybrid (Redis) mode is supported.

    Parameters
    ----------
    scarletName : str
        Redis-namespaced name for this Mapper. Agents that share the same
        `scarletName` participate in the same shared object.
    description : str, optional
        Human-readable description registered alongside this scarlet's
        definition (surfaced in the Composer UI's Scarlets page).

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
        """
        Register a new key with the underlying contract.

        Parameters
        ----------
        key : str
            Key to register.

        Returns
        -------
        bool
            Whether registration succeeded.
        """
        keyRegisterSuccess = self.super.contract.registerNewKey(key)
        return keyRegisterSuccess

    def Map(self, modelLocal, key, timeseries=False):
        """
        Write a value to a key.

        Parameters
        ----------
        modelLocal : numpy.ndarray
            Value to write.
        key : str
            Key to write it under.
        timeseries : bool, optional
            If `True`, append a Unix-timestamp suffix to `key` and
            register it as a new key rather than overwriting an existing
            one, so successive calls accumulate a time series instead of
            replacing the previous value. Default `False`.

        Returns
        -------
        successChunksList : list
            Chunks that were successfully mapped.
        status : bool
            Whether the operation succeeded.
        exception : Exception or None
            The exception raised, if any; `None` on success.
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
        """
        Read all key-value pairs currently stored.

        Parameters
        ----------
        modelLocal : numpy.ndarray, optional
            Passed through to the underlying `Pull` call per key; not
            required for a plain read.

        Returns
        -------
        allgather_dict : dict
            All key-value pairs, keyed by the original `Map` key.
        status : bool
            Whether the operation succeeded.
        exception : Exception or None
            The exception raised, if any; `None` on success.
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
        """
        `AllGather` followed by folding all values with `op`.

        `MAX`/`MIN`/`MUL` are applied element-wise; `SUM` sums.

        Parameters
        ----------
        modelLocal : numpy.ndarray
            Initial value the fold starts from.
        op : callable
            One of `Mapper.SUM`, `Mapper.MAX`, `Mapper.MIN`, `Mapper.MUL`
            (inherited from `ScarletBase` — see its `Attributes`).

        Returns
        -------
        sumV : numpy.ndarray
            Result of folding `op` over every gathered value, starting
            from `modelLocal`.
        status : bool
            Whether the operation succeeded.
        exception : Exception or None
            The exception raised, if any; `None` on success.
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
        """
        Overwrite every existing key with `modelLocal`.

        Parameters
        ----------
        modelLocal : numpy.ndarray
            Value to write to every existing key.

        Returns
        -------
        successChunksList : list
            Chunks that were successfully reset.
        exception : Exception or None
            The exception raised, if any; `None` on success.
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
        """
        Delete every key.

        Returns
        -------
        successChunksList : list
            Per-key deletion results.
        exception : Exception or None
            The exception raised, if any; `None` on success.
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