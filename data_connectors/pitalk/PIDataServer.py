import os, yaml, requests, json

class PIDataServer:

    def __init__(self):

        self.PI_DATA_ARCHIVE_URL = None
        self.PI_DATA_AUTH_TOKEN = None
        self.PI_DATA_AUTH_HEADER =None

        self.pitalk_config = None

        self.configFile = None
        if "PITALK_CONFIG_FILE" in os.environ.keys():
            self.configFile = os.environ["PITALK_CONFIG_FILE"]
        else:
            raise Exception("PITALK_CONFIG_FILE not specified")
        self.readConfig()



    def readConfig(self):
        with open(self.configFile, 'r') as stream:
            try:
                self.pitalk_config = yaml.safe_load(stream)
            except yaml.YAMLError as exc:
                print(exc)

        for server in self.pitalk_config.keys():
            if "type" not in self.pitalk_config[server].keys():
                print("Server type not specified for {}....skipping".format(server))
            if self.pitalk_config[server]["type"] == "DF":
                if "data_archive_url" in self.pitalk_config[server].keys():
                    self.PI_DATA_ARCHIVE_URL = self.pitalk_config[server]["data_archive_url"]
                else:
                    raise Exception("PI_DATA_ARCHIVE_URL not specified")

                if "data_auth_token" in self.pitalk_config[server].keys():
                    self.PI_DATA_AUTH_TOKEN = self.pitalk_config[server]["data_auth_token"]
                else:
                    raise Exception("PI_DATA_AUTH_TOKEN not specified")

                self.PI_DATA_AUTH_HEADER = {'Authorization': self.PI_DATA_AUTH_TOKEN}

        if self.PI_DATA_ARCHIVE_URL == None:
            raise Exception("Could not find any data servers in the specification...")


    def writeData(self,start_time,var_names,value_list):
        #time_index = pd.date_range(start=start_time, periods=2, freq=freq, tz='America/New_York')
        #print(time_index[0], value_list)
        payload = {"timestamp": str(start_time.strftime("%Y-%m-%d %H:%M:%S.%f"))}
        tag_list = []
        for var_ind, var_name in enumerate(var_names):
            tag_list = tag_list + [{"tag": var_name, "value": value_list[var_ind]}]

        payload["tag_list"] = tag_list
        print(payload)
        r = requests.put(self.PI_DATA_ARCHIVE_URL, data=json.dumps(payload), headers=self.PI_DATA_AUTH_HEADER, verify=False)
        if r.status_code != 200:
            print("could not push to " + self.PI_DATA_ARCHIVE_URL + " returned error code: " + str(r.status_code))
        else:
            print("successfully pushed for timestamp " + str(start_time))