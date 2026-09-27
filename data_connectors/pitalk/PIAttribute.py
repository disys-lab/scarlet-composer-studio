from urllib.parse import urlparse
import requests
import json
import pandas as pd

# https://isye-nagi-mgr.ad.gatech.edu/piwebapi/attributes?path=\\ISYE-NAGI-MGR\UserTestDB\PaperRoller1|Throughput
# https://isye-nagi-mgr.ad.gatech.edu/piwebapi/streams/F1AbEsOBnHP1gyEqhFzOY5ZEOQQZfKGIXX96xGudIcy8g5ltw5as-fAljo0GwpzBTmAMz7wSVNZRS1OQUdJLU1HUlxVU0VSVEVTVERCXFBBUEVSUk9MTEVSMXxUSFJPVUdIUFVU/recorded?starttime=*-1m


class PIAttribute:
    def __init__(self,tag_name,element,group_id,database,server,start_time,end_time):
        """ Read a set of values
            @param piwebapi_url string: The URL of the PI Web API
            @param asset_server string: Name of the Asset Server
            @param user_name string: The user's credentials name
            @param user_password string: The user's credentials password
            @param piwebapi_security_method string: Security method: basic or kerberos
            @param verify_ssl: If certificate verification will be performed
        """
        tag_name = tag_name.strip()
        # Replace All space (unicode is \\s) to %20
        tag_name = tag_name.replace(' ', "%20")
        self.tag_name = tag_name

        self.element = element
        self.database = database
        self.group_id = group_id
        self.server = server
        self.start_time = start_time
        self.end_time = end_time

    def checkNameEquality(self,tag_name):
        tag_name = tag_name.strip()
        # Replace All space (unicode is \\s) to %20
        tag_name = tag_name.replace(' ', "%20")
        if tag_name == self.tag_name:
            return True
        return False

    def call_headers(self, include_content_type):
        """ Create API call headers
            @includeContentType boolean: Flag determines whether or not the
            content-type header is included
        """
        if include_content_type is True:
            header = {
                'content-type': 'application/json',
                'X-Requested-With': 'XmlHttpRequest'
            }
        else:
            header = {
                'X-Requested-With': 'XmlHttpRequest'
            }

        return header

    def create_attribute(self):

        pass


    def read_attribute_stream(self):

        #  Get the sample tag
        request_url = '{}/attributes?path=\\\\{}\\{}\\{}|{}'.format(self.server.url, self.server.name, self.database, self.element, self.tag_name)

        url = urlparse(request_url)
        # Validate URL
        assert url.scheme == 'https'
        assert url.geturl().startswith(self.server.url)

        if self.server.security_method == None:
            raise Exception("{},{},{},{},{}: security method not defined",self.tag_name,self.group_id,self.element,self.database,self.server.name)

        response = requests.get(url.geturl(), auth=self.server.security_method, verify=self.server.verify_ssl)
        df = None
        #  Only continue if the first request was successful
        if response.status_code == 200:
            #  Deserialize the JSON Response
            data = json.loads(response.text)

            url = urlparse(self.server.url + '/streams/' + data['WebId'] +
                           '/recorded?startTime='+self.start_time+'&endTime='+self.end_time+"&selectedFields=Items.Timestamp;Items.Value")
            # Validate URL
            assert url.scheme == 'https'
            assert url.geturl().startswith(self.server.url)

            #  Read the set of values
            response = requests.get(
                url.geturl(), auth=self.server.security_method, verify=self.server.verify_ssl)

            if response.status_code == 200:
                dict_v = json.loads(response.text)
                df = pd.DataFrame(dict_v["Items"])

            else:
                print(response.status_code, response.reason, response.text)
        else:
            print(response.status_code, response.reason, response.text,response.headers)
        return df,response.status_code
