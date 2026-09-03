from scarlets.contract.RedisContract import RedisContract
from scarlets.types.ScarletBase import ScarletBase
from scarlets.utils.RedisLogger import RedisLogger as logging
import pickle, zlib


class RedisScarlet(ScarletBase):
    """
    Low-level storage primitive: chunked, compressed values over Redis.

    Extends `ScarletBase` with `Push`/`Pull`/`Clear`/`ClearAll`, backed by
    a `RedisContract`. In the open source release only pure-hybrid
    (Redis) mode is supported.

    Parameters
    ----------
    scarletName : str
        Redis-namespaced name for this scarlet.

    Attributes
    ----------
    contract : RedisContract or None
        The contract handling Redis reads/writes for this scarlet.
        `None` until `loadContract` is called.

    Methods
    -------
    loadContract()
        (Re)connect `contract` to Redis.
    Pull(modelLocal, key="0x0", average=False)
        Read a chunk's value from Redis.
    Push(modelLocal, key="0x0", wait4Tx=None)
        Write a chunk's value to Redis.
    Clear(key="0x0", wait4Tx=None)
        Delete one chunk.
    ClearAll(wait4Tx=None)
        Delete every chunk.
    """

    def __init__(self, scarletName):

        ScarletBase.__init__(self, scarletName)
        self.scarletName = scarletName
        self.contract = None

    def loadContract(self):
        """(Re)connect `contract` to Redis using this instance's current connection settings."""
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
        Read one chunk's value from Redis.

        Parameters
        ----------
        modelLocal : numpy.ndarray
            Fallback value returned if `key` doesn't exist in Redis.
        key : str, optional
            Chunk key. Default ``"0x0"``.
        average : bool, optional
            Currently unused by this implementation. Default `False`.

        Returns
        -------
        modelOut : numpy.ndarray
            The value read from Redis (unpickled, decompressed), or
            `modelLocal` if `key` wasn't found.
        status : bool
            Whether the read succeeded.
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
        Write one chunk's value to Redis (pickled, then zlib-compressed).

        Parameters
        ----------
        modelLocal : numpy.ndarray
            Value to write.
        key : str, optional
            Chunk key. Default ``"0x0"``.
        wait4Tx : list, optional
            Currently unused by this implementation.

        Returns
        -------
        list of bool
            Single-element list: whether the write succeeded.
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
        Delete one chunk.

        Parameters
        ----------
        key : str, optional
            Chunk key. Default ``"0x0"``.
        wait4Tx : list, optional
            Currently unused by this implementation.

        Returns
        -------
        list of bool
            Single-element list: whether the delete succeeded.
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
        Delete every chunk belonging to this scarlet.

        Parameters
        ----------
        wait4Tx : list, optional
            Currently unused by this implementation.

        Returns
        -------
        list of bool
            Single-element list: whether the delete succeeded.
        """

        # check if any debug values have been sent in wait4Tx


        status, exception = self.contract.clearAll()

        if not status:
            logging.error("fail to clear all elements of key exception: {}".format(exception))

        return [status]
