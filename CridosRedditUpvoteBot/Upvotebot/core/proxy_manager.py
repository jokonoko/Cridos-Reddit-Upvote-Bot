import time
import logging
import requests
from typing import Optional
from config import (
    PROXY_HOST,
    PROXY_PORT,
    PROXY_USERNAME,
    PROXY_PASSWORD,
    PROXY_PROVIDER,
    PROXY_TYPE,
    PROXY_ROTATION_URL,
    PROXY_ROTATION_ENABLED,
    get_proxy_url,
)

logger = logging.getLogger(__name__)


class ProxyManager:
    """Manages proxy rotation and sticky sessions."""

    def __init__(self):
        self.provider = PROXY_PROVIDER

    def get_proxy_for_account(self, account_id: int, custom_proxy: str = None) -> Optional[str]:
        """
        Get proxy URL for an account.
        Uses sticky session based on account_id for consistent IP per account.
        """
        # If account has a custom proxy assigned, use that
        if custom_proxy:
            return custom_proxy

        # Generate sticky session proxy
        return get_proxy_url(session_id=str(account_id))

    def get_rotating_proxy(self) -> Optional[str]:
        """Get a rotating proxy (new IP each time)."""
        return get_proxy_url(session_id=None)

    def format_proxy_for_provider(self, account_id: int) -> Optional[str]:
        """
        Format proxy URL based on provider's sticky session format.

        Different providers have different formats:
        - IPRoyal: user:pass_session-{id}@host:port
        - Smartproxy: user:pass@host:port:session-{id}
        - Bright Data: user-session-{id}:pass@host:port
        """
        if not all([PROXY_HOST, PROXY_PORT, PROXY_USERNAME, PROXY_PASSWORD]):
            return None

        session_id = f"reddit_{account_id}"

        if self.provider.lower() == "iproyal":
            # IPRoyal format: username:password_session-{id}_lifetime-24h
            auth = f"{PROXY_USERNAME}:{PROXY_PASSWORD}_session-{session_id}_lifetime-24h"
            return f"http://{auth}@{PROXY_HOST}:{PROXY_PORT}"

        elif self.provider.lower() == "smartproxy":
            # Smartproxy format: user:pass@gate.smartproxy.com:port:session-{id}
            auth = f"{PROXY_USERNAME}:{PROXY_PASSWORD}"
            return f"http://{auth}@{PROXY_HOST}:{PROXY_PORT}-session-{session_id}"

        elif self.provider.lower() == "brightdata":
            # Bright Data format: user-session-{id}:pass@host:port
            auth = f"{PROXY_USERNAME}-session-{session_id}:{PROXY_PASSWORD}"
            return f"http://{auth}@{PROXY_HOST}:{PROXY_PORT}"

        elif self.provider.lower() == "oxylabs":
            # Oxylabs format: user:pass@host:port with session in user
            auth = f"customer-{PROXY_USERNAME}-sessid-{session_id}:{PROXY_PASSWORD}"
            return f"http://{auth}@{PROXY_HOST}:{PROXY_PORT}"

        else:
            # Generic format - try basic sticky session
            return get_proxy_url(session_id=session_id)

    def test_proxy(self, proxy_url: str) -> dict:
        """Test proxy connectivity and get IP info."""
        from playwright.sync_api import sync_playwright

        result = {
            "working": False,
            "ip": None,
            "country": None,
            "error": None,
        }

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    proxy={"server": proxy_url} if proxy_url else None,
                )
                page = browser.new_page()

                # Check IP using httpbin
                page.goto("https://httpbin.org/ip", timeout=30000)
                content = page.content()

                import json
                import re

                # Extract IP from response
                match = re.search(r'"origin":\s*"([^"]+)"', content)
                if match:
                    result["ip"] = match.group(1)
                    result["working"] = True

                # Get geo info
                page.goto(f"https://ipapi.co/{result['ip']}/json/", timeout=30000)
                geo_content = page.text_content("body")
                geo_data = json.loads(geo_content)
                result["country"] = geo_data.get("country_name")

                browser.close()

        except Exception as e:
            result["error"] = str(e)

        return result

    def validate_proxy_config(self) -> bool:
        """Check if proxy configuration is valid."""
        return all([PROXY_HOST, PROXY_PORT, PROXY_USERNAME, PROXY_PASSWORD])

    def is_rotation_enabled(self) -> bool:
        """Check if mobile proxy rotation is enabled."""
        return PROXY_ROTATION_ENABLED and bool(PROXY_ROTATION_URL)

    def get_mobile_proxy(self) -> Optional[str]:
        """Get proxy URL for mobile rotation mode (no session ID needed)."""
        if not all([PROXY_HOST, PROXY_PORT]):
            return None

        if PROXY_USERNAME and PROXY_PASSWORD:
            auth = f"{PROXY_USERNAME}:{PROXY_PASSWORD}@"
        else:
            auth = ""

        protocol = "socks5" if PROXY_TYPE.lower() == "socks5" else "http"
        return f"{protocol}://{auth}{PROXY_HOST}:{PROXY_PORT}"

    def get_current_ip(self) -> Optional[str]:
        """Get current IP address through the proxy."""
        proxy_url = self.get_mobile_proxy()
        if not proxy_url:
            return None

        try:
            proxies = {
                "http": proxy_url,
                "https": proxy_url,
            }
            response = requests.get(
                "https://api.ipify.org",
                proxies=proxies,
                timeout=15,
            )
            if response.status_code == 200:
                return response.text.strip()
        except Exception as e:
            logger.warning(f"Failed to get current IP: {e}")

        return None

    def rotate_ip(self, verify: bool = True) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Trigger IP rotation via URL and optionally verify.

        Returns:
            tuple: (success, old_ip, new_ip)
        """
        if not PROXY_ROTATION_URL:
            return False, None, None

        try:
            # Get current IP before rotation (if verifying)
            old_ip = self.get_current_ip() if verify else None

            # Call rotation URL (direct request, not through proxy)
            response = requests.get(PROXY_ROTATION_URL, timeout=15)

            # Wait for rotation to take effect
            time.sleep(2)

            if verify and old_ip:
                new_ip = self.get_current_ip()

                # If IP didn't change, wait longer and retry
                if new_ip == old_ip:
                    logger.info("IP unchanged, waiting longer...")
                    time.sleep(3)
                    new_ip = self.get_current_ip()

                success = new_ip is not None and new_ip != old_ip
                if success:
                    logger.info(f"IP rotated: {old_ip} -> {new_ip}")
                else:
                    logger.warning(f"IP rotation may have failed: {old_ip} -> {new_ip}")

                return success, old_ip, new_ip

            return response.status_code == 200, old_ip, None

        except Exception as e:
            logger.error(f"IP rotation failed: {e}")
            return False, None, None
