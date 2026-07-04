from scarlets.utils.RedisLogger import RedisLogger as logging
from scarlets.core.Mapper import Mapper

class Federator(Mapper):
    """

    Federator class for conducting federated learning

    Attributes
    ----------
    op : operation
        The operation concerning the federation

    mpr_global : Mapper
        The mapper for storing the global model

    Methods
    -------

    * `Aggregate(modelLocal)`
        Aggregates all the local models present into the global model.

    """
    def __init__(self,scarletName,op):
        self.op = op

        Mapper.__init__(self,scarletName+"_mapper_reducer")

        self.mpr_global = Mapper(scarletName+"_mapper_global")


    def Aggregate(self,modelLocal):
        """
        Aggregates all the local models present into the global model.

        Parameters
        ----------
        modelLocal : numpy array
            The local model that is used as input for the federated learning

        Returns
        -------

        sumV : numpy array
            final value after carrying out the operation sequentially on all values.

        status : boolean
            status of the Map operation

        exception : Exception
            exception if any else it will be None

        """
        sumV, status, exception = self.Reduce(modelLocal, self.op)

        if status:
            successChunksList, map_status, exception = self.mpr_global.Map(sumV,"global")
            if map_status:
                return sumV, map_status, exception
            else:
                return sumV, map_status, exception
        else:
            return sumV, status, exception


