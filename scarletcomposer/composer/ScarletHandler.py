import os, redis, logging
from scarletcomposer.composer.ScarletInterpreter import ScarletInterpreter
from scarlets.types.ScarletBase import ScarletBase
from scarlets.utils.ScarletUtils import register_scarlet_definition


class ScarletHandler(ScarletBase):
    """
    Handles Scarlet extraction and deployment.

    Parses Python source files for #scarlet declarations via ScarletInterpreter,
    then writes the resulting scarlet definitions to Redis.
    """

    def __init__(self):
        ScarletBase.__init__(self, "ScarletHandler", True)
        self.interpreter = ScarletInterpreter()

    def interpretScript(self, scriptFile):
        """Parse scriptFile for #scarlet declarations."""
        self.interpreter.scarletExtractor(scriptFile)

    def getScarlets(self):
        """Return the dict of scarlets extracted from the last interpretScript call."""
        return self.interpreter.scarletContent

    def deployScarlets(self):
        """
        Write all scarlets extracted by the interpreter to Redis.

        Uses overwrite=True — CLI deploy always takes precedence over
        agent-created definitions, allowing the operator to reset contracts.
        Definitions are stored as JSON so agents and LLMs can read them
        directly without deserialisation.
        """
        for scarlet_name, entry in self.interpreter.scarletContent.items():
            attrs = entry.get("scarlet_attributes", {})
            expiry = int(attrs["expiry"]) if "expiry" in attrs else None
            register_scarlet_definition(
                scarlet_name=scarlet_name,
                scarlet_type=entry["scarlet_type"],
                description=entry.get("description", ""),
                attributes=attrs,
                expiry=expiry,
                overwrite=True,
            )
            logging.info(f"Scarlet '{scarlet_name}' deployed to Redis")
