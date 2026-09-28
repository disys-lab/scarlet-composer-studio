from scarlets.types.RedisScarlet import RedisScarlet
from scarlets.utils.RedisLogger import RedisLogger as logging
from scarlets.utils.ScarletUtils import register_scarlet_definition, touch_scarlet_definition
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
        # Kept for _touchDefinition()'s recreate path - a definition that
        # has already expired has to be rebuilt from scratch, and its
        # description would otherwise be lost on the first rebuild.
        self._description = description
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

    def _touchDefinition(self):
        """
        Renew this scarlet's definition TTL. Called from the write paths only.

        The definition is registered with `scarletDataExpiry` in
        `__init__`, the same TTL the data chunks carry
        (`RedisContract.Push`). The difference was that a chunk's TTL is
        reset every time it is rewritten, while the definition's was set
        once and never renewed - so the definition expired on a timer
        from construction regardless of use, and a Mapper written to
        continuously for longer than `scarletDataExpiry` kept working
        while disappearing from the Scarlets page, the dashboard count,
        and any existence check built on that key.

        Renewing here puts both on the same footing: written to, both
        live; abandoned, both expire together `scarletDataExpiry` after
        the last write.

        Deliberately not called from `AllGather`/`Reduce` - a read is not
        use for this purpose, and refreshing on read would let any
        polling dashboard keep every Mapper it looks at alive forever,
        which is the opposite of what the TTL is for. Also not called
        from `clearAll`, which empties the scarlet: extending the
        lifetime of a definition for something just emptied would be
        backwards. `refresh()` is not the hook either, despite the name -
        it reloads the local contract object and is called by the read
        paths too.
        """
        touch_scarlet_definition(
            scarlet_name=self.super.scarletName,
            expiry=self.super.scarletDataExpiry,
            scarlet_type="mapper",
            description=self._description,
            attributes={"mode": "redis-scarlet"},
        )

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

        Raises
        ------
        Exception
            If `key` contains "@" or ":" - both are reserved for this
            storage layer's own key-value:key:time:chunk convention
            (RedisContract's marker/chunk keys, and this method's own
            "#" timestamp suffix relies on "@"/":" never appearing in a
            caller-supplied key). Never previously enforced - a key
            violating this before would have been silently misread back
            rather than rejected up front.
        """

        if "@" in str(key) or ":" in str(key):
            logging.error("{}.Map failed - key {!r} contains a reserved character ('@' or ':')".format(self.super.scarletName, key))
            raise Exception("Map key {!r} contains a reserved character ('@' or ':') - both are reserved for this storage layer's own key convention".format(key))

        if timeseries:
            timestamp = int(time.time())
            key = f"{key}#{timestamp}"

        successChunksList = []
        try:
            if not self.super.debug:
                self.refresh()
            self._registerNewKey(key)
            successChunksList = self.super.Push(modelLocal, key, [])
        except Exception as exception:
            logging.error("{}.Map failed".format(self.super.scarletName))
            return successChunksList, False, exception
        # After the write succeeded, so a failed Map never extends the
        # definition's life - see _touchDefinition().
        self._touchDefinition()
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
        # A write, so it renews the definition the same way Map does.
        self._touchDefinition()
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