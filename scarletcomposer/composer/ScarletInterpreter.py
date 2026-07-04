import tokenize
import os


class ScarletInterpreter:
    """
    Parses Python source files for Scarlet declarations.

    Scarlet declarations are annotated comments of the form:
        #scarlet <type> <name> <attr>=<val>,<attr>=<val>,...

    Multiline descriptions use the #scarlet+ continuation token on any
    number of lines immediately following (or anywhere after) the declaration:
        #scarlet+ <description line>

    Example:
        #scarlet mapper GradientAggregator mode=redis-scarlet,expiry=3600
        #scarlet+ Accepts numpy float32 arrays of shape (128,). Dtype must be float32.
        #scarlet+ Key format: {APP_ID}_{NODE_ADDRESS}.
        #scarlet+ AllGather returns dict keyed by node address.

    The resulting dict is consumed by ScarletHandler to deploy scarlets to Redis.
    The default mode is redis-scarlet (Redis-backed shared memory).
    """

    def __init__(self):
        self.scarletContent = {}
        self._last_scarlet = None

    def checkScarlet(self, token):
        return token.split(" ")[0] == "#scarlet"

    def checkScarletDoc(self, token):
        return token.startswith("#scarlet+")

    def extractScarletAttributes(self, token):
        attrdict = {}
        for attribute in token.split(","):
            parts = attribute.split("=")
            if len(parts) == 2:
                attrdict[parts[0].strip()] = parts[1].strip()
        return attrdict

    def extractScarletParams(self, token):
        token_comps = token.split(" ")
        if token_comps[0] != "#scarlet" or len(token_comps) < 3:
            return {}
        scarlet_type = token_comps[1]
        scarlet_name = token_comps[2]
        scarlet_attributes = self.extractScarletAttributes(token_comps[3]) if len(token_comps) > 3 else {}
        return {
            "scarlet_type": scarlet_type,
            "scarlet_name": scarlet_name,
            "scarlet_attributes": scarlet_attributes,
        }

    def processScarlet(self, scarlet_details, token_details):
        scarlet_name = scarlet_details["scarlet_name"]
        scarlet_attributes = scarlet_details["scarlet_attributes"]
        if "mode" not in scarlet_attributes:
            scarlet_attributes["mode"] = "redis-scarlet"
        self.scarletContent[scarlet_name] = {
            "scarlet_type": scarlet_details["scarlet_type"],
            "scarlet_name": scarlet_name,
            "scarlet_attributes": scarlet_attributes,
            "content": "",
            "description": "",
        }
        self._last_scarlet = scarlet_name

    def appendDescription(self, token):
        """Append a #scarlet+ continuation line to the last declared scarlet."""
        if self._last_scarlet is None or self._last_scarlet not in self.scarletContent:
            return
        text = token[len("#scarlet+"):].strip()
        existing = self.scarletContent[self._last_scarlet]["description"]
        self.scarletContent[self._last_scarlet]["description"] = (
            existing + "\n" + text if existing else text
        )

    def scarletExtractor(self, scriptFile):
        """Tokenize scriptFile and extract all #scarlet declarations."""
        for toktype, token, start, end, line in tokenize.tokenize(
            open(scriptFile, "rb").readline
        ):
            if toktype == tokenize.COMMENT:
                if self.checkScarletDoc(token):
                    self.appendDescription(token)
                elif self.checkScarlet(token):
                    scarlet_details = self.extractScarletParams(token)
                    if "scarlet_type" in scarlet_details:
                        if scarlet_details["scarlet_name"] not in self.scarletContent:
                            self.processScarlet(scarlet_details, {"start": start, "end": end})
                        else:
                            raise Exception(
                                f"Scarlet at line {start} with name "
                                f"'{scarlet_details['scarlet_name']}' already defined"
                            )
