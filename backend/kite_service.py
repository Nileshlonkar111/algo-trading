from kiteconnect import KiteConnect
from kiteconnect.exceptions import TokenException, NetworkException
from enum import Enum
import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

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
        self._token_file = Path("kite_token.json")
        self._load_stored_token()

    def _load_stored_token(self):
        """Load and validate stored access token"""
        try:
            if self._token_file.exists():
                with open(self._token_file, 'r') as f:
                    data = json.load(f)
                    token = data.get('access_token')
                    stored_date = data.get('date')
                    
                    # Kite tokens expire at 6 AM daily
                    today = datetime.now().date().isoformat()
                    
                    if token and stored_date == today:
                        self.access_token = token
                        self.kite.set_access_token(token)
                        
                        # Validate token by making a test API call
                        if self._validate_token():
                            self._authenticated = True
                            logger.info("[KITE] Loaded and validated stored token")
                            return
                        else:
                            logger.warning("[KITE] Stored token validation failed")
                    else:
                        logger.info(f"[KITE] Token expired or stale (stored: {stored_date}, current: {today})")
                
                # Clean up invalid token
                self._clear_stored_token()
        except Exception as e:
            logger.error(f"[KITE] Error loading stored token: {e}")
            self._clear_stored_token()

    def _save_token(self):
        """Persist access token to disk"""
        try:
            data = {
                'access_token': self.access_token,
                'date': datetime.now().date().isoformat()
            }
            with open(self._token_file, 'w') as f:
                json.dump(data, f)
            logger.info("[KITE] Token saved successfully")
        except Exception as e:
            logger.error(f"[KITE] Error saving token: {e}")

    def _clear_stored_token(self):
        """Remove stored token file"""
        try:
            if self._token_file.exists():
                self._token_file.unlink()
                logger.info("[KITE] Cleared stored token")
        except Exception as e:
            logger.error(f"[KITE] Error clearing token: {e}")

    def _validate_token(self) -> bool:
        """Validate token by making a lightweight API call"""
        try:
            if not self.access_token:
                return False
            # Make a lightweight API call to validate token
            self.kite.profile()
            return True
        except TokenException as e:
            logger.warning(f"[KITE] Token validation failed: {e}")
            return False
        except Exception as e:
            logger.error(f"[KITE] Token validation error: {e}")
            return False

    def get_login_url(self):
        return self.kite.login_url()

    def generate_access_token(self, request_token: str):
        try:
            data = self.kite.generate_session(request_token, api_secret=self.api_secret)
            self.access_token = data["access_token"]
            self.kite.set_access_token(self.access_token)
            self._authenticated = True
            self._save_token()
            logger.info("[KITE] Access token generated and saved successfully")
            return TokenStatus.AUTHENTICATED
        except Exception as e:
            logger.error(f"[KITE] Error generating access token: {e}")
            self._authenticated = False
            self.access_token = None
            raise

    def token_status(self):
        """Check current token status with validation"""
        if not self._authenticated or not self.access_token:
            return TokenStatus.NOT_AUTHENTICATED
        
        # Validate token is still working
        if self._validate_token():
            return TokenStatus.AUTHENTICATED
        else:
            # Token expired or invalid
            self._authenticated = False
            self.access_token = None
            self._clear_stored_token()
            return TokenStatus.EXPIRED

    def is_authenticated(self):
        """Check if service is authenticated with live validation"""
        if not self._authenticated or not self.access_token:
            return False
        
        # Quick validation without extra API call for frequently called method
        return True

    def ensure_authenticated(self):
        """Ensure authentication is valid, raise exception if not"""
        status = self.token_status()
        if status != TokenStatus.AUTHENTICATED:
            raise Exception(f"Kite authentication required. Status: {status.value}")
        return True

    def get_account_info(self):
        """Get account info with automatic authentication check"""
        try:
            self.ensure_authenticated()
            return self.kite.profile()
        except TokenException as e:
            logger.error(f"[KITE] Token expired while fetching account: {e}")
            self._authenticated = False
            self.access_token = None
            self._clear_stored_token()
            raise Exception("Kite authentication expired. Please re-authenticate.")
        except Exception as e:
            logger.error(f"[KITE] Error fetching account info: {e}")
            raise