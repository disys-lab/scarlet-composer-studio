from scarlets.utils.RedisLogger import RedisLogger as logging
import redis,time,os,re
from scarlets.contract.ContractBase import ContractBase
# /*********AUTO INSERTION FROM FILE:chunkUtils.sol*********/
#
# /*********AUTO INSERTION FROM FILE:chunkArrayList.sol*********/
# pragma solidity >=0.5.0;
#
# struct ChunkCore{
#             bytes acmPiece;
#             bool exists;
#             uint lastUpdatedTime;
#             uint256 updater;
#         }
#
# struct ChunkArrayList{
#
#         uint acm_lastUpdatedTime;
#
#         uint numChunks;
#
#         uint chunkSize;
#
#         uint mult;
#
#         mapping(uint => ChunkCore) chunkArray;
# }
#
# /*********INSERTION ENDED FROM FILE:chunkArrayList.sol*********/
#
# library ChunkArrayListLibrary{
#
#     function setChunk(ChunkArrayList storage self, uint chunk, bytes memory acm_chunk, uint256 updater) internal {
#
#         self.chunkArray[chunk].acmPiece = acm_chunk;
#         self.chunkArray[chunk].exists = true;
#         self.chunkArray[chunk].lastUpdatedTime = now;
#         self.chunkArray[chunk].updater = updater;
#
#     }
#
#     function getChunkUpdater(ChunkArrayList storage self, uint chunk) internal view returns (uint){
#         self.chunkArray[chunk].updater;
#     }
#
#     function checkChunkExists(ChunkArrayList storage self, uint chunk) internal view returns (bool){
#         return self.chunkArray[chunk].exists;
#     }
#
#     function getChunk(ChunkArrayList storage self, uint chunk) internal view returns ( bytes memory) {
#         if (!self.chunkArray[chunk].exists){
#             return "";
#         }
#         return self.chunkArray[chunk].acmPiece;
#     }
#
#     function getChunkLastUpdateTime(ChunkArrayList storage self, uint chunk) internal view returns ( uint) {
#         return self.chunkArray[chunk].lastUpdatedTime;
#     }

class RedisContract(ContractBase):
    """
    `ContractBase` implementation storing chunks as Redis hashes.

    Each ``(key, chunk)`` pair is stored at
    ``{contractName}_key-value:{key}:{chunk}``, a hash with fields
    ``updater``, ``content``, ``lastUpdatedTime``, expiring after
    `scarletDataExpiry` seconds.

    Attributes
    ----------
    key_list : list of str
        Cached list of keys, populated by `getMapperLength` and indexed
        by `getKey`.

    Methods
    -------
    load()
        No-op in this release (open-source builds skip the license/env
        re-validation the commercial release performs here).
    registerNewKey(key)
        Register a new key on the contract.
    loadRedis()
        Connect to Redis using `redisDBHost`/`redisDBPort`/`redisDBPwd`.
    setChunk(key, chunk, chunk_content, address)
        Set one chunk's value.
    checkChunkExists(key, chunk)
        Check whether a chunk exists.
    getChunk(key, chunk)
        Get one chunk's value.
    getChunkUpdater(key, chunk)
        Get the address that last updated a chunk.
    getLastUpdateTime(key, chunk)
        Get a chunk's last-updated timestamp.
    getMapperLength()
        Count unique keys (Mapper scarlets only).
    getKey(key_index)
        Look up a key by index (Mapper scarlets only).
    """

    def __init__(self,contractname,redisDBHost,redisDBPort,redisDBPwd,defaultAccount,defaultPassword,debug,scarletDataExpiry):
        ContractBase.__init__(self, contractname, redisDBHost, redisDBPort, redisDBPwd, defaultAccount, defaultPassword,
                              debug,scarletDataExpiry)
        self.key_list = []

        self.load()

    def load(self):
        """No-op in the open source release — see class summary."""
        pass


        # if self.debug:
        # """
        #       Loads contract details from redis. Only done if debug is True.
        #       """

        #
        #
        #     if "REDIS_DB_HOST" not in os.environ.keys():
        #         raise Exception("REDIS_DB_HOST not set in os.environ")
        #
        #     if "REDIS_DB_PORT" not in os.environ.keys():
        #         raise Exception("REDIS_DB_PORT not set in os.environ")
        #
        #     if "REDIS_DB_PWD" not in os.environ.keys():
        #         raise Exception("REDIS_DB_PWD not set in os.environ")
        #
        #     self.redisDBHost = os.environ["REDIS_DB_HOST"]
        #     self.redisDBPort = os.environ["REDIS_DB_PORT"]
        #     self.redisDBPwd = os.environ["REDIS_DB_PWD"]
        #
        #     # if "KEYGEN_PUBLIC_KEY" not in os.environ.keys():
        #     #     raise Exception("KEYGEN_PUBLIC_KEY not set in os.environ")
        #     #
        #     # if "DEBUG_TEST_KEY" not in os.environ.keys():
        #     #     raise Exception("DEBUG_TEST_KEY not set in os.environ")
        #
        #     # public_key = os.environ["KEYGEN_PUBLIC_KEY"]
        #
        #
        #     # debug_test_key = os.environ["DEBUG_TEST_KEY"]
        #     #
        #     # license_status, key = verify_license_key(debug_test_key, public_key)
        #     #
        #     # if license_status:
        #     #     if "REDIS_DB_PWD" not in key.keys():
        #     #         raise Exception("REDIS_DB_PWD not found in DEBUG_TEST_KEY")
        #     # else:
        #     #     raise Exception("License: {} could not be verified".format(debug_test_key))



    def registerNewKey(self, key):

        """
        Register a new key on the contract.

        Parameters
        ----------
        key : str
            The key to register.

        Returns
        -------
        bool
            `True` if the key was newly registered, or already existed
            and `debug` is `True`; `False` otherwise.
        """

        key = str(key)
        r, status, exception = self.loadRedis()
        if status:
            if not r.exists(self.contractName + "_key-value"+":"+key):
                r.set(self.contractName + "_key-value"+":"+key,"exists")
                return True
            else:
                if self.debug:
                    return True

        return False


    def loadRedis(self):
        """
        Connect to Redis using `redisDBHost`/`redisDBPort`/`redisDBPwd`.

        Returns
        -------
        r : redis.StrictRedis or None
            The connected client, or `None` on failure.
        success : bool
            Whether the connection (and `PING`) succeeded.
        exception : Exception or None
            The exception raised, if any; `None` on success.
        """
        try:
            if self.debug:
                logging.info(f"{self.redisDBHost},{self.redisDBPort},{self.redisDBPwd}")

            r = redis.StrictRedis(host=self.redisDBHost, port=int(self.redisDBPort),
                                  password=self.redisDBPwd)
            r.ping()
            return r,True,None

        except Exception as exception:
            logging.error("could not connect to redis due to exception {}".format(exception))
            return None,False,exception


    def setChunk(self, key, chunk, chunk_content, address):
        """
        Set one chunk's value.

        Parameters
        ----------
        key : str
        chunk : int
        chunk_content : bytes
            Binary content to store.
        address : str
            Address of the agent performing the write, stored as
            `updater`.

        Returns
        -------
        bool
            Whether the write succeeded.
        exception : Exception or None
            The exception raised, if any; `None` on success.
        """


        r, status, exception = self.loadRedis()
        if status:
            r.hset(self.contractName+"_key-value"+":"+str(key)+":"+str(chunk), mapping={
                                                                                    "updater":address,
                                                                                    "content":chunk_content,
                                                                                    "lastUpdatedTime":time.time()
                                                                                })
            r.expire(self.contractName+"_key-value"+":"+str(key)+":"+str(chunk), self.scarletDataExpiry)
            return True,None
        else:
            return status,exception

    def clearChunk(self, key, chunk):
        """
        Delete one chunk, and its parent key entry if present.

        Parameters
        ----------
        key : str
        chunk : int

        Returns
        -------
        bool
            Whether the chunk was found and deleted.
        exception : str or None
            Error message, if any; `None` on success.
        """


        r, status, exception = self.loadRedis()
        if status:
            key_scarlet_name = f"{self.contractName}_key-value:{str(key)}".encode('utf-8')
            key_scarlet_chunk_name = f"{self.contractName}_key-value:{str(key)}:{str(chunk)}".encode('utf-8')
            try:
                if r.exists(key_scarlet_name):
                    r.delete(key_scarlet_name)
                    logging.info(f"{key_scarlet_name} deleted from redis")
                    #return True, None
                else:
                    logging.error(f"{key_scarlet_name} does not exist on redis")
                    #return False, f"{key_scarlet_name} does not exist on redis"

                if r.exists(key_scarlet_chunk_name):
                    r.delete(key_scarlet_chunk_name)
                    logging.info(f"{key_scarlet_chunk_name} deleted from redis")
                    return True, None
                else:
                    logging.error(f"{key_scarlet_chunk_name} does not exist on redis")
                    return False, f"{key_scarlet_chunk_name} does not exist on redis"

            except Exception as e:
                logging.error(f"Exception occured while deleting {key_scarlet_name}")
                return False, str(e)

    def clearAll(self,):
        """
        Delete every chunk/key entry belonging to this contract.

        Returns
        -------
        bool
            Whether the operation succeeded.
        exception : str or None
            Error message, if any; `None` on success.
        """


        r, status, exception = self.loadRedis()
        if status:
            key_scarlet_name = f"{self.contractName}_key-value:*".encode('utf-8')
            #key_scarlet_chunk_name = f"{self.contractName}_key-value:{str(key)}:{str(chunk)}".encode('utf-8')
            try:
                # Scan and delete matching keys
                cursor = 0
                while True:
                    cursor, keys = r.scan(cursor, match=key_scarlet_name, count=100)
                    if keys:
                        r.delete(*keys)  # Delete the found keys
                    if cursor == 0:
                        break
                return True, None

            except Exception as e:
                logging.error(f"Exception occured while clearing {key_scarlet_name}")
                return False, str(e)

    def checkChunkExists(self, key, chunk):
        """
        Check whether a chunk exists.

        Parameters
        ----------
        key : str
        chunk : int

        Returns
        -------
        bool
        """


        r, status, exception = self.loadRedis()
        if status:
            if r.exists(self.contractName+"_key-value"+":"+str(key)+":"+str(chunk)):
                return True
        return False


    def getChunk(self,key, chunk):
        """
        Get one chunk's stored content.

        Parameters
        ----------
        key : str
        chunk : int

        Returns
        -------
        bytes
            The chunk's `content` field, or `b""` if it doesn't exist or
            Redis is unreachable.
        """

        r, status, exception = self.loadRedis()

        if status:
            if r.exists(self.contractName+"_key-value"+":"+str(key)+":"+str(chunk)):
                chunkDict = r.hgetall(self.contractName+"_key-value"+":"+str(key)+":"+str(chunk))
                return chunkDict[b'content']
        return b''


    def getChunkUpdater(self,key, chunk):
        """
        Get the address that last updated a chunk.

        Parameters
        ----------
        key : str
        chunk : int

        Returns
        -------
        str or None
            The `updater` field, or `None` if the chunk doesn't exist or
            Redis is unreachable.
        """

        r, status, exception = self.loadRedis()
        if status:
            if r.exists(self.contractName + "_key-value" + ":" + str(key) + ":" + str(chunk)):
                chunkDict = r.hgetall(self.contractName + "_key-value" + ":" + str(key) + ":" + str(chunk))
                return chunkDict[b'updater']
        return None


    def getLastUpdateTime(self, key, chunk):
        """
        Get a chunk's last-updated timestamp.

        Parameters
        ----------
        key : str
        chunk : int

        Returns
        -------
        lastUpdatedTime : str
            The stored `lastUpdatedTime` field.
        exception : None
            Always `None` on the success path; the method returns
            ``""`` alone (no tuple) if the chunk doesn't exist or Redis
            is unreachable.
        """
        r, status, exception = self.loadRedis()
        if status:
            if r.exists(self.contractName + "_key-value" + ":" + str(key) + ":" + str(chunk)):
                chunkDict = r.hgetall(self.contractName + "_key-value" + ":" + str(key) + ":" + str(chunk))
                return chunkDict[b'lastUpdatedTime'], None
        return ""


    def getMapperLength(self):
        """
        Count unique keys registered on this contract.

        Applicable only for Mapper scarlets. Refreshes `key_list` as a
        side effect.

        Returns
        -------
        int
            Number of unique keys, or `0` if Redis is unreachable.
        """

        r, status, exception = self.loadRedis()
        if status:

            comprehensive_keys_list = r.keys(self.contractName + "_key-value:*")

            self.key_list = [key.decode("utf-8").split(":")[1] for key in comprehensive_keys_list]

            if not len(self.key_list):
                logging.warning("getMapperLength yielded 0 keys for mapper:{}".format(self.contractName))
            return len(self.key_list)

        else:
            return 0

    def getKey(self,key_index):
        """
        Look up a key by its index in `key_list`.

        Applicable only for Mapper scarlets. Call `getMapperLength`
        first to ensure `key_list` is populated.

        Parameters
        ----------
        key_index : int

        Returns
        -------
        str
            The key at `key_index`.
        """
        return self.key_list[key_index]
