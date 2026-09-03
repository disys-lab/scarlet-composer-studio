from scarlets.utils.RedisLogger import RedisLogger as logging
from scarlets.core.Mapper import Mapper

class Federator(Mapper):
    """
    Federated aggregation — workers post local models, the head aggregates.

    Extends `Mapper` with a fixed reduction `op`, applied automatically
    on every `Aggregate` call, and a second `Mapper` (`mpr_global`)
    holding the aggregated result.

    Parameters
    ----------
    scarletName : str
        Base name for this Federator. Two underlying Mapper scarlets are
        constructed from it: ``{scarletName}_mapper_reducer`` (local
        contributions) and ``{scarletName}_mapper_global`` (the
        aggregated result).
    op : callable
        Reduction applied on every `Aggregate` call - one of
        `Mapper.SUM`, `Mapper.MAX`, `Mapper.MIN`, `Mapper.MUL`.

    Attributes
    ----------
    op : callable
        The reduction operation, as passed to `__init__`.
    mpr_global : Mapper
        The Mapper storing the aggregated global model.

    Methods
    -------
    Aggregate(modelLocal)
        Aggregate all local models into the global model.
    """
    def __init__(self,scarletName,op):
        self.op = op

        Mapper.__init__(self,scarletName+"_mapper_reducer")

        self.mpr_global = Mapper(scarletName+"_mapper_global")


    def Aggregate(self,modelLocal):
        """
        Post this worker's local model, then fold it and every other
        contribution with `op` and store the result on `mpr_global`.

        Parameters
        ----------
        modelLocal : numpy.ndarray
            This worker's local contribution.

        Returns
        -------
        sumV : numpy.ndarray
            The aggregated result (`op` applied across every worker's
            contribution).
        status : bool
            Whether the operation succeeded.
        exception : Exception or None
            The exception raised, if any; `None` on success.
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


