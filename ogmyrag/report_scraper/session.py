import time
import logging
from typing import Any, Dict, Optional

import requests
import curl_cffi.requests as c_requests

scraper_logger = logging.getLogger("scraper")


class CloudflareSession:
    """
    Bypass Cloudflare protections for both HTML and binary fetches.
    """
    CHALLENGE_URL = "https://disclosure.bursamalaysia.com/Corporate/InfobursaApplication/announcements.aspx"

    def __init__(self, impersonate: str = "chrome120"):
        self.impersonate = impersonate

    def _get_session(self) -> c_requests.Session:
        """
        Perform the Cloudflare handshake and return a session with the correct cookies set
        """
        session = c_requests.Session(impersonate=self.impersonate)
        resp = session.get(
            self.CHALLENGE_URL,
            headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Referer":        "https://www.bursamalaysia.com/",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-User": "?1"
            }
        )
        # wait for challenge
        time.sleep(4)
        session.cookies.update(resp.cookies)
        return session
    
    def _merge_headers(self, extra: Optional[Dict[str,str]]) -> Dict[str,str]:
        base = {
            # Generic UA for both JSON and HTML
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/112.0.0.0 Safari/537.36"
            ),
            # Default referer can be overridden
            "Referer": self.CHALLENGE_URL,
            # Helpful when hitting JSON endpoints
            "X-Requested-With": "XMLHttpRequest"
        }
        if extra:
            base.update(extra)
        return base
    
    def get_json(self, url: str, params: Dict[str,Any] = None, extra_headers: Optional[Dict[str,str]] = None) -> Any:
        """
        Fetch a JSON endpoint via the bypassed session.
        """
        session = self._get_session()
        resp = session.get(
            url,
            params=params,
            headers=self._merge_headers(extra_headers),
        )
        resp.raise_for_status()
        return resp.json()

    def get_html(self, url: str, extra_headers: Optional[Dict[str,str]] = None) -> str:
        """
        Fetch HTML content, bypassing Cloudflare.
        """
        session = self._get_session()
        resp = session.get(
            url,
            headers=self._merge_headers(extra_headers)
        )
        resp.raise_for_status()
        return resp.text

    def get_bytes(self, url: str, extra_headers: Optional[Dict[str,str]] = None) -> bytes:
        """
        Fetch raw bytes content, bypassing Cloudflare.
        """
        session = self._get_session()
        resp = session.get(
            url,
            headers=self._merge_headers(extra_headers)
        )
        resp.raise_for_status()
        return resp.content


class BaseScraper:
    """
    All HTTP (JSON, HTML, PDF) goes through a single CFSession
    """
    API_URL = "https://www.bursamalaysia.com/api/v1/announcements/search"

    def __init__(self, cf_session: Optional[CloudflareSession] = None):
        self.cf = cf_session or CloudflareSession()