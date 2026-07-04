"""

##Types submodule

This modules contains the various types of scarlet classes including their base classes

* `ScarletBase`
    Base class for all Scarlets. Contains all Scarlet attributes
* `Scarlet`
    Scarlet class for pure-decent mode, i.e. storage and pointer on the blockchain
* `IPFSBaseScarlet`
    Base scarlet class for full-decent and full-hybrid mode, i.e. any mode that concerns storage on IPFS
* `IPFSBCScarlet`
    Scarlet class for full-decent mode, i.e. pointer on the blockchain, storage on IPFS
* `IPFSRedisScarlet`
    Scarlet class for full-hybrid mode, i.e. pointer on redis, storage on IPFS
* `RedisScarlet`
    Scarlet class for pure-hybrid mode, i.e. storage and pointer on the blockchain
"""