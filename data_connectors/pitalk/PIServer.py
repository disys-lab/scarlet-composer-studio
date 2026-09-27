from requests.auth import HTTPBasicAuth
from requests_kerberos import HTTPKerberosAuth

class PIServer:
    def __init__(self, url, server_name,server_id,verify_ssl):
        self.url = url
        self.security_method = None
        self.name = server_name
        self.server_id = server_id
        self.verify_ssl = verify_ssl

    def call_security_method(self, security_method_type, credential):
        """ Create API call security method
            @param security_method string: Security method to use: basic or kerberos
            @param user_name string: The user's credentials name
            @param user_password string: The user's credentials password
        """

        security_auth = None

        if "token" in credential.keys():
            token = credential["token"]

        elif "user_name" in credential.keys() and "user_password" in credential.keys():
            user_name = credential['user_name']
            user_password = credential['user_password']

            if security_method_type.lower() == 'basic':
                security_auth = HTTPBasicAuth(user_name, user_password)
            else:
                security_auth = HTTPKerberosAuth(mutual_authentication='REQUIRED',
                                                 sanitize_mutual_error_response=False)
        else:
            raise Exception("Unknown security type detected")

        self.security_method = security_auth