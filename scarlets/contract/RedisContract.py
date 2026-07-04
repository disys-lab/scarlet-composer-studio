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
    Base class for all types of Contracts. Contains all Contract attributes

    Attributes
    ----------
    key_list : list
        list of keys

    Methods
    -------

    * `load()`
        Loads contract details from redis. Only done if debug is True.

    * `registerNewKey(key)`
        registers new key on contract

    * `loadRedis()`
        Connect to redis given redisDBHost,redisDBPort and redisDBPwd

    * `setChunk(key, chunk, chunk_content, address)`
        Set the chunk for a particular key

    * `checkChunkExists(key, chunk)`
        Check if the chunk exists for a particular key

    * `getChunk(key, chunk)`
        Get chunk for a particular key

    * `getChunkUpdater(key, chunk)`
        Get the updater (address) of chunk for a particular key

    * `getLastUpdateTime(key, chunk)`
        Get the last updated time of chunk for a particular key

    * `getMapperLength()`
        gets mapper length, i.e. number of unique keys on the mapper. applicable only in case of Mapper scarlets.

    * `getKey()`
        if given an index key_index, retrieves the key at that location. applicable in case of Mapper scarlets.

    """

    def __init__(self,contractname,redisDBHost,redisDBPort,redisDBPwd,defaultAccount,defaultPassword,debug,scarletDataExpiry):
        ContractBase.__init__(self, contractname, redisDBHost, redisDBPort, redisDBPwd, defaultAccount, defaultPassword,
                              debug,scarletDataExpiry)
        self.key_list = []

        self.load()

    def load(self):
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
        registers new key on contract

        Parameters
        ----------
        key : string
            the key to be registered

        Returns
        -------

        ret_val : boolean
            represents whether the register method was successful on the SmartContract

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
        Connect to redis given redisDBHost,redisDBPort and redisDBPwd

        Returns
        -------

        r : redis object
            the object that can connect to redis

        success : boolean
            flag that indicates whether the connect succeeded

        exception : Exception
            the exception that is thrown in case of an error

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
        Set the chunk for a particular key

        Parameters
        ----------

        key : string
           the key id

        chunk : int
            the chunk id to be set

        chunk_content : string
            binary string that represents the chunk content

        address : string
            the address of the agent setting the string


        Returns
        -------

        ret_val : boolean
            flag that represents whether the set operation was successful or not

        exception : Exception
            Exception thrown in case of an error, None in case of no exception
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
        Clear chunk for a particular key

        Parameters
        ----------

        key : string
           the key id

        chunk : int
            the chunk id to be set

        Returns
        -------

        ret_val : boolean
            flag representing the success of operation
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
        Clear chunk for a particular key

        Parameters
        ----------

        Returns
        -------

        ret_val : boolean
            flag representing the success of operation
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
        Check if the chunk exists for a particular key

        Parameters
        ----------

        key : string
           the key id

        chunk : int
            the chunk id to be set

        Returns
        -------

        ret_val : boolean
            flag representing the existence of the flag
        """


        r, status, exception = self.loadRedis()
        if status:
            if r.exists(self.contractName+"_key-value"+":"+str(key)+":"+str(chunk)):
                return True
        return False


    def getChunk(self,key, chunk):
        """
        Get chunk for a particular key

        Parameters
        ----------

        key : string
           the key id

        chunk : int
            the chunk id to be set

        Returns
        -------

        chunk_content : string
            binary string representing the chunk content, defaults to empty string in case of failure

        """

        r, status, exception = self.loadRedis()

        if status:
            if r.exists(self.contractName+"_key-value"+":"+str(key)+":"+str(chunk)):
                chunkDict = r.hgetall(self.contractName+"_key-value"+":"+str(key)+":"+str(chunk))
                return chunkDict[b'content']
        return b''


    def getChunkUpdater(self,key, chunk):
        """
        Get the updater (address) of chunk for a particular key

        Parameters
        ----------

        key : string
           the key id

        chunk : int
            the chunk id to be set

        Returns
        -------

        chunk_updater : string
            address of the last updater, None in case of failure

        """

        r, status, exception = self.loadRedis()
        if status:
            if r.exists(self.contractName + "_key-value" + ":" + str(key) + ":" + str(chunk)):
                chunkDict = r.hgetall(self.contractName + "_key-value" + ":" + str(key) + ":" + str(chunk))
                return chunkDict[b'updater']
        return None


    def getLastUpdateTime(self, key, chunk):
        """
        Get the last updated time of chunk for a particular key

        Parameters
        ----------

        key : string
           the key id

        chunk : int
            the chunk id to be set

        Returns
        -------

        lastUpdatedTime : string
            time of the last update, empty string in case of failure

        """
        r, status, exception = self.loadRedis()
        if status:
            if r.exists(self.contractName + "_key-value" + ":" + str(key) + ":" + str(chunk)):
                chunkDict = r.hgetall(self.contractName + "_key-value" + ":" + str(key) + ":" + str(chunk))
                return chunkDict[b'lastUpdatedTime'], None
        return ""


    def getMapperLength(self):

        """
        gets mapper length, i.e. number of unique keys on the mapper. applicable only in case of Mapper scarlets.
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
        if given an index key_index, retrieves the key at that location. applicable in case of Mapper scarlets.
        """
        return self.key_list[key_index]
