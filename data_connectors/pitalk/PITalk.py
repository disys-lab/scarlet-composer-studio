
import os
import yaml
from .PIServer import PIServer
from .PIAttribute import PIAttribute

# https://isye-nagi-mgr.ad.gatech.edu/piwebapi/attributes?path=\\ISYE-NAGI-MGR\UserTestDB\PaperRoller1|Throughput

# https://isye-nagi-mgr.ad.gatech.edu/piwebapi/streams/F1AbEsOBnHP1gyEqhFzOY5ZEOQQZfKGIXX96xGudIcy8g5ltw5as-fAljo0GwpzBTmAMz7wSVNZRS1OQUdJLU1HUlxVU0VSVEVTVERCXFBBUEVSUk9MTEVSMXxUSFJPVUdIUFVU/recorded?starttime=*-1m
class PITalk:
    def __init__(self):

        self.configFile = None
        if "PITALK_CONFIG_FILE" in os.environ.keys():
            self.configFile = os.environ["PITALK_CONFIG_FILE"]
        else:
            raise Exception("PITALK_CONFIG_FILE not specified")

        if not os.path.isfile(self.configFile):
            raise Exception("Config file not found", self.configFile)

        self.pitalk_config = None

        self.server_list = {}

        self.attribute_list = {}

        self.group_list = {}

        self.readConfig()


    def readConfig(self):
        with open(self.configFile, 'r') as stream:
            try:
                self.pitalk_config = yaml.safe_load(stream)
            except yaml.YAMLError as exc:
                print(exc)

        self.no_servers = len(self.pitalk_config.keys())

        for server in self.pitalk_config.keys():
            if "type" not in self.pitalk_config[server].keys():
                print("Server type not specified for {}....skipping".format(server))
                continue
            if self.pitalk_config[server]["type"] == "AF":
                server_obj = self.initServer(server)
                self.server_list[server] ={}
                self.server_list[server]["obj"] = server_obj

                no_groups = len(self.pitalk_config[server]["attributes"].keys())
                self.server_list[server]["no_groups"] = no_groups

                for group in self.pitalk_config[server]["attributes"].keys():
                    group_lvl = self.pitalk_config[server]["attributes"][group]

                    tag_list = group_lvl["tag_name"]
                    self.group_list[group] = tag_list

                    for tag_name in tag_list:
                        element = group_lvl["element"]
                        database = group_lvl["database"]
                        start_time = group_lvl["start_time"]
                        end_time = group_lvl["end_time"]
                        attribute = PIAttribute(tag_name,element,group,database,server_obj,start_time,end_time)
                        self.attribute_list[tag_name] = attribute

        if len(self.server_list.keys()) == 0:
            raise Exception ("Could not find any AF Server specifications...")

    def initServer(self,server):
        if "url" not in self.pitalk_config[server].keys():
            raise Exception("URL not specified for AF server: {}", server)
        else:
            url = self.pitalk_config[server]["url"]

        if "af_server_name" not in self.pitalk_config[server].keys():
            raise Exception("Server name not specified for AF server: {}", server)
        else:
            server_name = self.pitalk_config[server]["af_server_name"]

        verify_ssl = self.pitalk_config[server]["security"]["verify_ssl"]

        piserver = PIServer(url, server_name,server,verify_ssl)
        security_method_type = self.pitalk_config[server]["security"]["method"]

        credential = None
        if "token" in self.pitalk_config[server]["security"].keys():
            credential = {"token": self.pitalk_config[server]["security"]["token"]}
        elif "user" in self.pitalk_config[server]["security"].keys() and "password" in \
                self.pitalk_config[server]["security"].keys():
            credential = {"user_name": self.pitalk_config[server]["security"]["user"],
                          "user_password": self.pitalk_config[server]["security"]["password"]}
        else:
            raise Exception("Unknown security type detected")

        piserver.call_security_method(security_method_type, credential)

        return piserver

    def getRecorded(self,tag_name):
        self.attribute_list[tag_name].read_attribute_stream()
        pass