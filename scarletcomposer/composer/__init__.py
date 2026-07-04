"""

The composer module contains the scarlet interpreter, scarlet handler and scarlet driver

* `scarletDriver`
    This script file is based on the python Click library and provides a command line interface to `scarlet-composer`

* `ScarletHandler`
    This class handles Scarlet extraction and deployment

* `ScarletInterpreter`
    The scarlet interpreter parses through a code file written in python, identifies scarlet declarations starting with
    the keyword "#scarlet....", extracts scarlet attributes. It also generates SmartContract code for scarlets that
    pertain to blockchain in the Solidity language.

    Each scarlet can be either a compound or an element scarlet. Compound Scarlets are those which are comprised of one
    or more element Scarlets. Element Scarlets are the ones which cannot be divided any further and are self contained.

    The interpreter performs a scarlet resolution recursivel, wherein a scarlet dependency tree is constructed based on
    dependecies as defined in the scarlet_templates/formulations folder. This dependency tree structure is used to
    determine the scarlet name in case of hierarchical compound scarlet. (see function scourFormulations)

    For generating SmartContract code for scarlets, the interpreter recursively injects code from multiple nested .sol
    files using the key word "import ...". All .sol files for libraries must be present in scarlet_templates/libraries.

"""