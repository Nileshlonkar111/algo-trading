from kiteconnect import KiteConnect
from enum import Enum
import os

class TokenStatus(Enum):
    NOT_AUTHENTICATED = "not_authenticated"
    AUTHENTICATED = "authenticated"
    EXPIRED = "expired"

class KiteService:
    def __init__(self):
        self.api_key = os.getenv("KITE_API_KEY", "")
        self.api_secret = os.getenv("KITE_API_SECRET", "")
        self.access_token = None
        self.kite = KiteConnect(api_key=self.api_key)
        self._authenticated = False

    def get_login_url(self):
        return self.kite.login_url()

    def generate_access_token(self, request_token: str):
        data = self.kite.generate_session(request_token, api_secret=self.api_secret)
        self.access_token = data["access_token"]
        self.kite.set_access_token(self.access_token)
        self._authenticated = True
        return TokenStatus.AUTHENTICATED

    def token_status(self):
        if self._authenticated and self.access_token:
            return TokenStatus.AUTHENTICATED
        return TokenStatus.NOT_AUTHENTICATED

    def is_authenticated(self):
        return self._authenticated and self.access_token is not None

    def get_account_info(self):
        if not self.is_authenticated():
            raise Exception("Not authenticated")
        return self.kite.profile()