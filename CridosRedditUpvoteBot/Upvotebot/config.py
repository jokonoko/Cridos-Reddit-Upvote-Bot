import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
PROFILES_DIR = Path(os.getenv("PROFILES_DIR", BASE_DIR / "profiles"))
LOG_DIR = Path(os.getenv("LOG_DIR", BASE_DIR / "logs"))

# Database
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "farm.db"))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Proxy settings
PROXY_PROVIDER = os.getenv("PROXY_PROVIDER", "")
PROXY_HOST = os.getenv("PROXY_HOST", "")
PROXY_PORT = os.getenv("PROXY_PORT", "")
PROXY_USERNAME = os.getenv("PROXY_USERNAME", "")
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD", "")

# Mobile proxy rotation settings
PROXY_TYPE = os.getenv("PROXY_TYPE", "http")  # "http" or "socks5"
PROXY_ROTATION_URL = os.getenv("PROXY_ROTATION_URL", "")  # URL to trigger IP change
PROXY_ROTATION_ENABLED = os.getenv("PROXY_ROTATION_ENABLED", "false").lower() == "true"
MOBILE_ACTION_DELAY = int(os.getenv("MOBILE_ACTION_DELAY", 11))  # Faster delay with IP rotation

# Worker settings - Romanian time (GMT+2), 9pm to 5am = 8 hours for 60 accounts
WORKER_START_HOUR = int(os.getenv("WORKER_START_HOUR", 21))  # 9pm
WORKER_END_HOUR = int(os.getenv("WORKER_END_HOUR", 5))       # 5am
WORKER_TIMEZONE = os.getenv("WORKER_TIMEZONE", "Europe/Bucharest")
WORKER_SKIP_PROBABILITY = float(os.getenv("WORKER_SKIP_PROBABILITY", 0.2))

# Browser settings
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
SLOW_MO = int(os.getenv("SLOW_MO", 50))

# Anti-detection delays (seconds)
MIN_ACTION_DELAY = int(os.getenv("MIN_ACTION_DELAY", 30))
MAX_ACTION_DELAY = int(os.getenv("MAX_ACTION_DELAY", 180))
MIN_SCROLL_DELAY = float(os.getenv("MIN_SCROLL_DELAY", 1))
MAX_SCROLL_DELAY = float(os.getenv("MAX_SCROLL_DELAY", 4))

# Delay between posts in same session (seconds)
DELAY_BETWEEN_POSTS_MIN = float(os.getenv("DELAY_BETWEEN_POSTS_MIN", 2))
DELAY_BETWEEN_POSTS_MAX = float(os.getenv("DELAY_BETWEEN_POSTS_MAX", 4))

# Reddit URLs
REDDIT_BASE_URL = "https://www.reddit.com"
REDDIT_LOGIN_URL = "https://www.reddit.com/login"
REDDIT_OLD_URL = "https://old.reddit.com"


def get_proxy_url(session_id: str = None) -> str | None:
    """Generate proxy URL for mobile proxy (no sticky session needed)."""
    if not all([PROXY_HOST, PROXY_PORT, PROXY_USERNAME, PROXY_PASSWORD]):
        return None

    # Mobile proxy format - same credentials for all, IP rotation via URL
    auth = f"{PROXY_USERNAME}:{PROXY_PASSWORD}"

    return f"{PROXY_TYPE}://{auth}@{PROXY_HOST}:{PROXY_PORT}"


def get_proxy_config(session_id: str = None) -> dict | None:
    """
    Generate Playwright proxy config dict with separate auth fields.
    Required for SOCKS5 proxies which don't support inline auth in URL.
    Mobile proxy uses same credentials for all accounts, IP rotation via PROXY_ROTATION_URL.
    """
    if not all([PROXY_HOST, PROXY_PORT, PROXY_USERNAME, PROXY_PASSWORD]):
        return None

    # Mobile proxy format - no sticky session suffix needed
    return {
        "server": f"{PROXY_TYPE}://{PROXY_HOST}:{PROXY_PORT}",
        "username": PROXY_USERNAME,
        "password": PROXY_PASSWORD,
    }


def ensure_dirs():
    """Create necessary directories if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
