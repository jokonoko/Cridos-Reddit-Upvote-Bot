"""Test script for external health check validation."""
import sys
from core.browser import BrowserManager
from core.proxy_manager import ProxyManager


def test_health_check(username: str, headless: bool = True):
    """Test health check for a specific username."""
    proxy_manager = ProxyManager()
    proxy = None

    # Try to use proxy if configured
    try:
        if proxy_manager.validate_proxy_config():
            proxy = proxy_manager.format_proxy_for_provider(9999)
            print(f"Using proxy: {proxy}")
    except:
        print("No proxy configured, checking without proxy")

    browser = BrowserManager()
    try:
        print(f"\nStarting health checker browser...")
        browser.start_health_checker(proxy=proxy, headless=headless)

        print(f"Checking account: {username}")
        print("-" * 50)

        status = browser.check_account_status(username)

        print("-" * 50)
        print(f"\nResult: {status.upper()}")

        # Interpret the status
        status_descriptions = {
            "active": "Account appears healthy and publicly visible",
            "suspended": "Account has been suspended by Reddit",
            "banned": "Account has been banned by Reddit",
            "not_found": "Profile doesn't exist or returns 404",
            "shadowbanned": "Account appears shadowbanned (profile empty externally)",
            "restricted": "Account has restricted content visibility",
            "unknown": "Unable to determine status"
        }

        if status in status_descriptions:
            print(f"Meaning: {status_descriptions[status]}")

        return status
    except Exception as e:
        print(f"\nError: {e}")
        return "error"
    finally:
        browser.stop()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_health_check.py <username> [--show]")
        print("\nOptions:")
        print("  --show    Show browser window (not headless)")
        print("\nExample:")
        print("  python test_health_check.py spez")
        print("  python test_health_check.py suspendeduser123 --show")
        sys.exit(1)

    username = sys.argv[1]
    headless = "--show" not in sys.argv

    test_health_check(username, headless=headless)
