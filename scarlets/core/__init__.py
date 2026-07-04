"""

##Core modules

This module contains the implementation of the core Scarlet classes. These are also referred to as the element scarlets.

* `Accumulator`
    deprecated::
    Accumulator Scarlet does a shared memory update of model parameters only in the pure-decent mode. This has been
    deprecated since superior performance with the same results can be obtained through Mapper in other modes.


* `Mapper`
    Mapper Scarlet maps keys to values. Values could be anything such as model parameters, arrays etc.
    This Mapper inherits from multiple classes. However, at run time depending on the mode of the scarlet declaration,
    the classes are initialized.

"""