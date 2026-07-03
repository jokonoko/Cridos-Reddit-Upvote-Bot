import json
import random
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page, BrowserContext
from playwright_stealth import Stealth

import config
from config import (
    PROFILES_DIR,
    HEADLESS,
    SLOW_MO,
    MIN_SCROLL_DELAY,
    MAX_SCROLL_DELAY,
    REDDIT_BASE_URL,
    REDDIT_LOGIN_URL,
)


class BrowserManager:
    """Manages browser instances with anti-detection measures."""

    # Common viewport sizes (realistic)
    VIEWPORTS = [
        {"width": 1920, "height": 1080},
        {"width": 1366, "height": 768},
        {"width": 1536, "height": 864},
        {"width": 1440, "height": 900},
        {"width": 1280, "height": 720},
    ]

    # Common user agents
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    ]

    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    def _get_profile_path(self, profile_id: str) -> Path:
        """Get the profile directory path for an account using unique profile ID."""
        # Ensure profile_id is a string (prevents PosixPath / int error)
        profile_path = PROFILES_DIR / str(profile_id)
        profile_path.mkdir(parents=True, exist_ok=True)
        return profile_path

    def _load_fingerprint(self, profile_id: str) -> dict:
        """Load or generate fingerprint for account."""
        fingerprint_file = self._get_profile_path(profile_id) / "fingerprint.json"

        if fingerprint_file.exists():
            with open(fingerprint_file, "r") as f:
                return json.load(f)

        # Generate new fingerprint
        fingerprint = {
            "viewport": random.choice(self.VIEWPORTS),
            "user_agent": random.choice(self.USER_AGENTS),
            "timezone": random.choice(["America/New_York", "America/Los_Angeles", "America/Chicago", "Europe/London"]),
            "locale": "en-US",
        }

        with open(fingerprint_file, "w") as f:
            json.dump(fingerprint, f)

        return fingerprint

    def _get_health_checker_profile_path(self) -> Path:
        """Get the profile directory path for the health checker."""
        profile_path = PROFILES_DIR / "health_checker"
        profile_path.mkdir(parents=True, exist_ok=True)
        return profile_path

    def _load_health_checker_fingerprint(self) -> dict:
        """Load or generate fingerprint for health checker."""
        fingerprint_file = self._get_health_checker_profile_path() / "fingerprint.json"

        if fingerprint_file.exists():
            with open(fingerprint_file, "r") as f:
                return json.load(f)

        # Generate stable fingerprint for health checker
        fingerprint = {
            "viewport": {"width": 1920, "height": 1080},  # Most common resolution
            "user_agent": self.USER_AGENTS[0],  # Use consistent UA
            "timezone": "America/New_York",
            "locale": "en-US",
        }

        with open(fingerprint_file, "w") as f:
            json.dump(fingerprint, f)

        return fingerprint

    def start(
        self,
        profile_path: str,
        proxy: str = None,
        headless: bool = None,
    ) -> Page:
        """Start browser with persistent profile and stealth measures.

        Args:
            profile_path: Unique profile identifier (UUID string) from database
            proxy: Proxy URL or dict
            headless: Whether to run in headless mode
        """
        if headless is None:
            headless = HEADLESS

        # Ensure profile_path is a string (handles int account_id passed by mistake)
        profile_path = str(profile_path)

        profile_dir = self._get_profile_path(profile_path)
        fingerprint = self._load_fingerprint(profile_path)

        self.playwright = sync_playwright().start()

        # Browser launch args for stealth
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
        ]

        # Proxy configuration - parse URL to extract auth for SOCKS5 compatibility
        proxy_config = None
        if proxy:
            # Check if proxy is a dict (new format) or string (URL format)
            if isinstance(proxy, dict):
                proxy_config = proxy
            else:
                # Parse URL format: protocol://user:pass@host:port
                from urllib.parse import urlparse
                parsed = urlparse(proxy)
                if parsed.username and parsed.password:
                    proxy_config = {
                        "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
                        "username": parsed.username,
                        "password": parsed.password,
                    }
                else:
                    proxy_config = {"server": proxy}

        # Launch persistent context (keeps cookies/localStorage)
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            slow_mo=SLOW_MO,
            viewport=fingerprint["viewport"],
            user_agent=fingerprint["user_agent"],
            locale=fingerprint["locale"],
            timezone_id=fingerprint["timezone"],
            proxy=proxy_config,
            args=launch_args,
            ignore_https_errors=True,
            # Disable WebRTC to prevent IP leak
            permissions=["geolocation"],
        )

        # Get or create page
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = self.context.new_page()

        # Apply stealth patches
        Stealth().apply_stealth_sync(self.page)

        # Additional stealth: comprehensive anti-detection
        self.page.add_init_script("""
            // Hide webdriver
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Realistic plugins array
            Object.defineProperty(navigator, 'plugins', {
                get: () => {
                    const plugins = [
                        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                        { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' }
                    ];
                    plugins.length = 3;
                    return plugins;
                }
            });

            // Override languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });

            // Hide automation flags
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;

            // Override permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );

            // Chrome runtime
            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {}
            };

            // Disable WebRTC IP leak
            const originalRTCPeerConnection = window.RTCPeerConnection;
            if (originalRTCPeerConnection) {
                window.RTCPeerConnection = function(...args) {
                    const pc = new originalRTCPeerConnection(...args);
                    pc.createDataChannel = () => {};
                    return pc;
                };
            }

            // Override hardware concurrency to common value
            Object.defineProperty(navigator, 'hardwareConcurrency', {
                get: () => 4
            });

            // Override device memory
            Object.defineProperty(navigator, 'deviceMemory', {
                get: () => 8
            });
        """)

        return self.page

    def start_health_checker(
        self,
        proxy: str = None,
        headless: bool = None,
    ) -> Page:
        """
        Start browser with clean health checker profile (never logged in).
        This profile is used to check account status from an external perspective.
        """
        if headless is None:
            headless = HEADLESS

        profile_path = self._get_health_checker_profile_path()
        fingerprint = self._load_health_checker_fingerprint()

        self.playwright = sync_playwright().start()

        # Same stealth args as regular browser
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
        ]

        # Proxy configuration - same logic as start()
        proxy_config = None
        if proxy:
            if isinstance(proxy, dict):
                proxy_config = proxy
            else:
                from urllib.parse import urlparse
                parsed = urlparse(proxy)
                if parsed.username and parsed.password:
                    proxy_config = {
                        "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
                        "username": parsed.username,
                        "password": parsed.password,
                    }
                else:
                    proxy_config = {"server": proxy}

        # Launch persistent context with health checker profile
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            headless=headless,
            slow_mo=SLOW_MO,
            viewport=fingerprint["viewport"],
            user_agent=fingerprint["user_agent"],
            locale=fingerprint["locale"],
            timezone_id=fingerprint["timezone"],
            proxy=proxy_config,
            args=launch_args,
            ignore_https_errors=True,
            permissions=["geolocation"],
        )

        # Get or create page
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = self.context.new_page()

        # Apply stealth patches
        Stealth().apply_stealth_sync(self.page)
        self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
        """)

        return self.page

    def stop(self):
        """Close browser and cleanup."""
        if self.context:
            self.context.close()
            self.context = None
        if self.playwright:
            self.playwright.stop()
            self.playwright = None
        self.page = None

    def is_logged_in(self, username: str = None, take_screenshot: bool = False) -> bool:
        """
        Check if currently logged in to Reddit.
        Uses settings page redirect - unauthenticated users get redirected to /login.

        Args:
            username: Optional username for screenshot naming
            take_screenshot: If True, saves screenshots for both success and failure
        """
        try:
            # Navigate to settings page (requires authentication)
            settings_url = f"{REDDIT_BASE_URL}/settings"
            print(f"[DEBUG] Navigating to {settings_url} to check login status...")
            self.page.goto(settings_url, wait_until="domcontentloaded", timeout=30000)

            # Wait for potential redirect to complete
            time.sleep(3)

            # Check current URL
            current_url = self.page.url
            print(f"[DEBUG] Current URL after navigation: {current_url}")

            # Determine login status based on URL
            is_logged = "/login" not in current_url and "/register" not in current_url

            status = "logged_in" if is_logged else "not_logged_in"
            print(f"[DEBUG] ====== FINAL RESULT: {status.upper().replace('_', ' ')} ======")

            # Take screenshot for verification
            if take_screenshot:
                self._save_login_check_screenshot(username, status)

            return is_logged

        except Exception as e:
            print(f"is_logged_in check failed: {e}")
            if take_screenshot:
                self._save_login_check_screenshot(username, "error")
            return False

    def _save_login_check_screenshot(self, username: str, status: str) -> None:
        """Save a screenshot for login check verification."""
        try:
            from datetime import datetime
            from pathlib import Path
            screenshots_dir = Path("/app/screenshots")
            screenshots_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_username = username or "unknown"
            screenshot_path = screenshots_dir / f"login_check_{status}_{safe_username}_{timestamp}.png"
            self.page.screenshot(path=str(screenshot_path), full_page=False)
            print(f"Login check screenshot saved: {screenshot_path}")
        except Exception as e:
            print(f"Screenshot failed: {e}")

    def _warmup_browse(self):
        """Browse Reddit briefly before login to appear more human."""
        try:
            print("[DEBUG] Warming up browser with pre-login browsing...")

            # Visit Reddit homepage first
            self.page.goto(REDDIT_BASE_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(2, 4))

            # Handle cookie popup
            try:
                cookie_accept = self.page.query_selector('button:has-text("Accept All")')
                if cookie_accept and cookie_accept.is_visible():
                    self._human_click(cookie_accept)
                    time.sleep(random.uniform(0.5, 1))
            except:
                pass

            # Random mouse movements on page (looking around)
            viewport = self.page.viewport_size
            for _ in range(random.randint(2, 4)):
                x = random.uniform(100, viewport["width"] - 100)
                y = random.uniform(100, viewport["height"] - 100)
                self.page.mouse.move(x, y)
                time.sleep(random.uniform(0.3, 0.8))

            # Maybe scroll a bit
            if random.random() < 0.6:
                scroll_amount = random.randint(200, 500)
                self.page.mouse.wheel(0, scroll_amount)
                time.sleep(random.uniform(1, 2))

                # Maybe scroll back up slightly
                if random.random() < 0.3:
                    self.page.mouse.wheel(0, -random.randint(50, 150))
                    time.sleep(random.uniform(0.5, 1))

            # Brief pause like reading
            time.sleep(random.uniform(1, 3))

            print("[DEBUG] Warmup complete, proceeding to login...")

        except Exception as e:
            print(f"[DEBUG] Warmup browsing failed (continuing anyway): {e}")

    def login(self, username: str, password: str) -> bool:
        """Perform Reddit login with human-like warmup behavior."""
        try:
            # Warmup: browse Reddit briefly before going to login
            self._warmup_browse()

            # Now navigate to login page
            self.page.goto(REDDIT_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(2, 4))

            # Handle cookie popup if it appears (might show again on login page)
            try:
                cookie_accept = self.page.query_selector('button:has-text("Accept All")')
                if cookie_accept and cookie_accept.is_visible():
                    self._human_click(cookie_accept)
                    time.sleep(1)
            except:
                pass  # Cookie popup not present or already dismissed

            # Username field selectors (new Reddit uses #login-username, old used name="username")
            username_selectors = [
                '#login-username',
                'input[name="username"]',
                'input[id*="username"]',
                'input[autocomplete="username"]',
            ]

            username_field = None
            for selector in username_selectors:
                try:
                    username_field = self.page.wait_for_selector(selector, timeout=5000)
                    if username_field:
                        break
                except:
                    continue

            if not username_field:
                print("Could not find username field")
                return False

            self._human_type(username_field, username)
            time.sleep(random.uniform(0.5, 1.5))

            # Password field selectors
            password_selectors = [
                '#login-password',
                'input[name="password"]',
                'input[id*="password"]',
                'input[type="password"]',
            ]

            password_field = None
            for selector in password_selectors:
                try:
                    password_field = self.page.query_selector(selector)
                    if password_field:
                        break
                except:
                    continue

            if not password_field:
                print("Could not find password field")
                return False

            self._human_type(password_field, password)
            time.sleep(random.uniform(0.5, 1.5))

            # Login button selectors (Reddit uses custom components now)
            login_btn_selectors = [
                'button[type="submit"]',
                'button:has-text("Log In")',
                'button:has-text("Sign In")',
                'faceplate-tracker button',
                '.login button',
                'button[class*="login"]',
                'input[type="submit"]',
            ]

            login_btn = None
            for selector in login_btn_selectors:
                try:
                    login_btn = self.page.query_selector(selector)
                    if login_btn and login_btn.is_visible():
                        break
                except:
                    continue

            if not login_btn:
                # Try pressing Enter as fallback
                print("Could not find login button, trying Enter key")
                password_field.press("Enter")
            else:
                self._human_click(login_btn)

            # Wait for navigation/response (longer to handle rate limiting)
            time.sleep(8)

            # Check for error messages
            page_content = self.page.content().lower()

            if "something went wrong" in page_content or "please try again" in page_content:
                print("Login failed: Reddit showing 'Something went wrong' - likely bot detection or rate limit")
                # Take screenshot for debugging
                try:
                    self.page.screenshot(path=f"login_error_{username}_{int(time.time())}.png")
                except:
                    pass
                return False

            if "incorrect username" in page_content or "wrong password" in page_content:
                print("Login failed: Incorrect credentials")
                return False

            if "verify" in page_content or "suspicious" in page_content:
                print("Login failed: Account requires verification (captcha/email)")
                return False

            # Check if login successful by verifying profile page
            return self.is_logged_in(username)

        except Exception as e:
            print(f"Login failed: {e}")
            return False

    def _human_type(self, element, text: str):
        """Type text with realistic human-like delays and variations."""
        # Move mouse to element first
        self._move_mouse_to_element(element)
        time.sleep(random.uniform(0.1, 0.25))

        element.click()
        time.sleep(random.uniform(0.2, 0.5))

        # Simulate different typing speeds - some people type faster, some slower
        base_speed = random.uniform(0.7, 1.3)  # Speed multiplier for this session

        for i, char in enumerate(text):
            # Variable delay per character (faster for common letters, slower for special chars)
            if char in 'etaoinshrdlu':  # Common letters - faster
                delay = random.uniform(40, 100) * base_speed
            elif char in '0123456789':  # Numbers - slower (reaching for numrow)
                delay = random.uniform(80, 180) * base_speed
            elif char in '!@#$%^&*()_+-=':  # Special chars - even slower
                delay = random.uniform(120, 250) * base_speed
            else:
                delay = random.uniform(60, 140) * base_speed

            element.type(char, delay=delay)

            # Occasional pauses (thinking, looking at keyboard)
            if random.random() < 0.08:
                time.sleep(random.uniform(0.15, 0.4))

            # Rare longer pause (distraction, double-checking)
            if random.random() < 0.02:
                time.sleep(random.uniform(0.4, 0.8))

    def _move_mouse_to_element(self, element):
        """Move mouse to element with human-like curved path."""
        box = element.bounding_box()
        if not box:
            return

        # Target position (randomized within element)
        target_x = box["x"] + random.uniform(box["width"] * 0.3, box["width"] * 0.7)
        target_y = box["y"] + random.uniform(box["height"] * 0.3, box["height"] * 0.7)

        # Get current mouse position (approximate from viewport center if unknown)
        viewport = self.page.viewport_size
        current_x = viewport["width"] / 2 + random.uniform(-100, 100)
        current_y = viewport["height"] / 2 + random.uniform(-100, 100)

        # Generate curved path using bezier-like movement
        steps = random.randint(15, 30)
        for i in range(steps):
            t = (i + 1) / steps
            # Add slight curve using easing
            ease_t = t * t * (3 - 2 * t)  # Smoothstep easing

            # Add small random deviations for natural movement
            deviation_x = random.uniform(-3, 3) if i < steps - 1 else 0
            deviation_y = random.uniform(-3, 3) if i < steps - 1 else 0

            x = current_x + (target_x - current_x) * ease_t + deviation_x
            y = current_y + (target_y - current_y) * ease_t + deviation_y

            self.page.mouse.move(x, y)
            time.sleep(random.uniform(0.005, 0.02))

    def _human_click(self, element):
        """Click element with mouse movement and randomized position."""
        if not element:
            raise ValueError("Cannot click on None element")

        # Move mouse to element first
        self._move_mouse_to_element(element)

        # Small pause before clicking (human reaction time)
        time.sleep(random.uniform(0.05, 0.15))

        box = element.bounding_box()
        if box:
            # Randomize click position within element
            x = box["x"] + random.uniform(box["width"] * 0.25, box["width"] * 0.75)
            y = box["y"] + random.uniform(box["height"] * 0.25, box["height"] * 0.75)
            self.page.mouse.click(x, y)
        else:
            element.click()

        # Small pause after clicking
        time.sleep(random.uniform(0.1, 0.25))

    def scroll_page(self, min_scrolls: int = 3, max_scrolls: int = 8):
        """Scroll page with human-like behavior."""
        num_scrolls = random.randint(min_scrolls, max_scrolls)

        for _ in range(num_scrolls):
            # Random scroll distance
            scroll_distance = random.randint(200, 600)

            # Scroll with variable speed
            self.page.mouse.wheel(0, scroll_distance)

            # Random delay between scrolls
            time.sleep(random.uniform(MIN_SCROLL_DELAY, MAX_SCROLL_DELAY))

            # Occasionally scroll up a bit (like a human)
            if random.random() < 0.2:
                self.page.mouse.wheel(0, -random.randint(50, 150))
                time.sleep(random.uniform(0.5, 1))

    def _extract_subreddit_from_url(self, post_url: str) -> str:
        """Extract subreddit name from a Reddit post URL."""
        import re
        # Match patterns like /r/subreddit/ or reddit.com/r/subreddit/
        match = re.search(r'/r/([^/]+)', post_url)
        if match:
            return match.group(1)
        return None

    def join_subreddit(self, subreddit_name: str, account_id: int = None) -> bool:
        """
        Join a subreddit if not already a member.
        If account_id is provided, checks database first and records the join.

        Args:
            subreddit_name: Name of the subreddit (without r/ prefix)
            account_id: Optional account ID for database tracking

        Returns True if joined or already a member.
        """
        try:
            # Normalize subreddit name
            subreddit_name = subreddit_name.lower().replace("r/", "").strip()

            # Check database first if account_id provided
            if account_id:
                from core.database import Database
                db = Database()
                if db.has_joined_subreddit(account_id, subreddit_name):
                    print(f"[DEBUG] Already joined r/{subreddit_name} (from database)")
                    return True

            print(f"[DEBUG] Visiting subreddit: r/{subreddit_name}")
            self.page.goto(f"{REDDIT_BASE_URL}/r/{subreddit_name}", wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(2, 4))

            # Handle cookie popup if present
            try:
                cookie_accept = self.page.query_selector('button:has-text("Accept All")')
                if cookie_accept and cookie_accept.is_visible():
                    self._human_click(cookie_accept)
                    time.sleep(random.uniform(0.5, 1))
            except:
                pass

            # Check if already joined (look for "Joined" or "Leave" button)
            already_joined_selectors = [
                'button:has-text("Joined")',
                'button:has-text("Leave")',
                'button[aria-label*="leave"]',
            ]

            for selector in already_joined_selectors:
                try:
                    element = self.page.query_selector(selector)
                    if element and element.is_visible():
                        print(f"[DEBUG] Already a member of r/{subreddit_name}")
                        # Record in database if account_id provided
                        if account_id:
                            db.add_joined_subreddit(account_id, subreddit_name)
                        return True
                except:
                    continue

            # Look for Join button
            join_selectors = [
                'button:has-text("Join")',
                'button[aria-label*="Join"]',
            ]

            for selector in join_selectors:
                try:
                    join_btn = self.page.query_selector(selector)
                    if join_btn and join_btn.is_visible():
                        print(f"[DEBUG] Joining r/{subreddit_name}...")
                        self._human_click(join_btn)
                        time.sleep(random.uniform(1, 2))
                        print(f"[DEBUG] Joined r/{subreddit_name}")
                        # Record in database if account_id provided
                        if account_id:
                            db.add_joined_subreddit(account_id, subreddit_name)
                        return True
                except:
                    continue

            # If no join button found, might already be joined or error
            print(f"[DEBUG] Could not find join button for r/{subreddit_name}, continuing anyway")
            # Record as joined anyway (benefit of doubt)
            if account_id:
                db.add_joined_subreddit(account_id, subreddit_name)
            return True

        except Exception as e:
            print(f"[DEBUG] Error joining subreddit r/{subreddit_name}: {e}")
            return False

    def _read_comments(self):
        """Scroll through comments section before upvoting to appear human."""
        try:
            print("[DEBUG] Reading comments...")

            # Scroll down to comments section (2-4 scrolls)
            num_scrolls = random.randint(2, 4)
            for i in range(num_scrolls):
                scroll_distance = random.randint(300, 500)
                self.page.mouse.wheel(0, scroll_distance)
                time.sleep(random.uniform(1, 3))

            # 30% chance to expand a collapsed comment
            if random.random() < 0.3:
                try:
                    expand_selectors = [
                        'button:has-text("more replies")',
                        'button:has-text("View more")',
                        '[data-click-id="expando"]',
                    ]
                    for selector in expand_selectors:
                        try:
                            expand_btn = self.page.query_selector(selector)
                            if expand_btn and expand_btn.is_visible():
                                print("[DEBUG] Expanding collapsed comment...")
                                self._human_click(expand_btn)
                                time.sleep(random.uniform(1, 2))
                                break
                        except:
                            continue
                except:
                    pass

            # Scroll back up a bit to see the post and upvote button
            self.page.mouse.wheel(0, -random.randint(200, 400))
            time.sleep(random.uniform(0.5, 1))

            print("[DEBUG] Done reading comments")

        except Exception as e:
            print(f"[DEBUG] Error reading comments: {e}")

    def upvote_post(self, post_url: str, account_id: int = None) -> tuple[bool, str]:
        """
        Navigate to post and upvote it with human-like behavior.
        Flow: Join subreddit → Visit post → Upvote (efficient but natural)

        Args:
            post_url: Reddit post URL to upvote
            account_id: Optional account ID for tracking joined subreddits

        Returns (success: bool, error_message: str or None)
        """
        try:
            # Step 1: Extract and join subreddit first (checks database if account_id provided)
            subreddit = self._extract_subreddit_from_url(post_url)
            if subreddit:
                self.join_subreddit(subreddit, account_id=account_id)
                time.sleep(random.uniform(0.5, 1.5))

            # Step 2: Navigate to the post
            print(f"Navigating to: {post_url}")
            self.page.goto(post_url, wait_until="load", timeout=30000)

            # Step 3: Brief natural pause before upvoting (human reaction time)
            time.sleep(random.uniform(1, 2))

            # Use Playwright's locator API with text/role matching (pierces shadow DOM automatically)
            upvote_btn = None
            matched_method = None

            # Method 1: Try role-based locator (recommended for accessibility)
            try:
                upvote_locator = self.page.get_by_role("button", name="Upvote")
                if upvote_locator.count() > 0:
                    upvote_btn = upvote_locator.first
                    matched_method = "get_by_role('button', name='Upvote')"
                    print(f"Found upvote button with: {matched_method}")
            except Exception as e:
                print(f"Role locator failed: {e}")

            # Method 2: Try case-insensitive upvote
            if not upvote_btn:
                try:
                    upvote_locator = self.page.get_by_role("button", name="upvote")
                    if upvote_locator.count() > 0:
                        upvote_btn = upvote_locator.first
                        matched_method = "get_by_role('button', name='upvote')"
                        print(f"Found upvote button with: {matched_method}")
                except Exception as e:
                    print(f"Role locator (lowercase) failed: {e}")

            # Method 3: Deep CSS selector with shadow DOM piercing
            if not upvote_btn:
                shadow_selectors = [
                    'shreddit-post >>> button[aria-label="Upvote"]',
                    'shreddit-post >>> button[aria-label="upvote"]',
                    '>>> button[aria-label="Upvote"]',
                    '>>> button[aria-label="upvote"]',
                    'button[aria-label="Upvote"]',
                    'button[aria-label="upvote"]',
                    '[data-click-id="upvote"]',
                ]
                for selector in shadow_selectors:
                    try:
                        locator = self.page.locator(selector)
                        if locator.count() > 0:
                            upvote_btn = locator.first
                            matched_method = f"locator('{selector}')"
                            print(f"Found upvote button with: {matched_method}")
                            break
                    except:
                        continue

            # Method 4: JavaScript evaluation to find in shadow DOM
            if not upvote_btn:
                try:
                    upvote_handle = self.page.evaluate_handle('''() => {
                        // Look for upvote button in regular DOM
                        let btn = document.querySelector('button[aria-label="Upvote"], button[aria-label="upvote"]');
                        if (btn) return btn;

                        // Look inside shadow roots
                        const allElements = document.querySelectorAll('*');
                        for (const el of allElements) {
                            if (el.shadowRoot) {
                                btn = el.shadowRoot.querySelector('button[aria-label="Upvote"], button[aria-label="upvote"]');
                                if (btn) return btn;
                            }
                        }
                        return null;
                    }''')
                    if upvote_handle:
                        upvote_btn = upvote_handle.as_element()
                        if upvote_btn:
                            matched_method = "JavaScript shadow DOM search"
                            print(f"Found upvote button with: {matched_method}")
                except Exception as e:
                    print(f"JavaScript evaluation failed: {e}")

            if not upvote_btn:
                page_title = self.page.title()
                current_url = self.page.url
                print(f"ERROR: Could not find upvote button. URL: {post_url}")
                print(f"Page title: {page_title}")
                print(f"Current URL: {current_url}")

                # Take screenshot for debugging
                try:
                    from datetime import datetime
                    from pathlib import Path
                    screenshots_dir = Path("/app/screenshots")
                    screenshots_dir.mkdir(exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    # Extract post ID from URL for filename
                    post_id = post_url.split("/")[-2] if "/comments/" in post_url else "unknown"
                    screenshot_path = screenshots_dir / f"upvote_fail_{timestamp}_{post_id}.png"
                    self.page.screenshot(path=str(screenshot_path), full_page=True)
                    print(f"Screenshot saved: {screenshot_path}")
                except Exception as ss_e:
                    print(f"Screenshot failed: {ss_e}")

                # Debug: log page structure
                try:
                    debug_info = self.page.evaluate('''() => {
                        const info = { buttons: [], shredditPosts: 0, shadowRoots: 0 };
                        info.shredditPosts = document.querySelectorAll('shreddit-post').length;
                        document.querySelectorAll('*').forEach(el => {
                            if (el.shadowRoot) info.shadowRoots++;
                        });
                        document.querySelectorAll('button').forEach((btn, i) => {
                            if (i < 15) {
                                info.buttons.push({
                                    aria: btn.getAttribute('aria-label') || 'none',
                                    text: btn.textContent?.slice(0, 30) || 'none'
                                });
                            }
                        });
                        return info;
                    }''')
                    print(f"DEBUG: shreddit-posts={debug_info['shredditPosts']}, shadowRoots={debug_info['shadowRoots']}")
                    print(f"DEBUG: buttons found: {debug_info['buttons']}")
                except Exception as debug_e:
                    print(f"DEBUG failed: {debug_e}")
                return False, f"Upvote button not found (page: {page_title[:50]})"

            # Check if already upvoted
            try:
                aria_pressed = upvote_btn.get_attribute("aria-pressed")
                print(f"Initial aria-pressed state: {aria_pressed}")
                if aria_pressed == "true":
                    print("Already upvoted - skipping")
                    return True, None
            except:
                print("Could not check aria-pressed, proceeding with click")

            # Click upvote
            print("Clicking upvote button...")
            upvote_btn.click()
            time.sleep(1)

            # Verify upvote by re-checking button state
            try:
                # Try to get the button again using role-based locator
                upvote_locator = self.page.get_by_role("button", name="Upvote")
                if upvote_locator.count() == 0:
                    upvote_locator = self.page.get_by_role("button", name="upvote")

                if upvote_locator.count() > 0:
                    aria_pressed_after = upvote_locator.first.get_attribute("aria-pressed")
                    print(f"After click aria-pressed state: {aria_pressed_after}")

                    if aria_pressed_after == "true":
                        print("Upvote successful!")
                        return True, None
                    else:
                        error_reason = "Click did not register"
                        print(f"ERROR: Upvote did not register. aria-pressed={aria_pressed_after}")
                        return False, error_reason
                else:
                    # Button not found after click - assume success if no error
                    print("Could not re-find button to verify, assuming success")
                    return True, None
            except Exception as verify_e:
                print(f"Verification failed: {verify_e}, assuming success")
                return True, None

        except Exception as e:
            print(f"ERROR: Upvote exception: {type(e).__name__}: {e}")
            return False, f"Exception: {type(e).__name__}: {str(e)[:100]}"

    def browse_homepage(self, duration_seconds: int = None):
        """Browse Reddit homepage like a human."""
        if duration_seconds is None:
            duration_seconds = random.randint(120, 600)  # 2-10 minutes

        start_time = time.time()

        try:
            self.page.goto(REDDIT_BASE_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(2, 4))

            while time.time() - start_time < duration_seconds:
                # Scroll
                self.scroll_page(min_scrolls=2, max_scrolls=5)

                # Maybe click a post
                if random.random() < 0.3:
                    posts = self.page.query_selector_all('a[data-click-id="body"]')
                    if posts:
                        post = random.choice(posts[:10])  # Pick from top 10 visible
                        self._human_click(post)
                        time.sleep(random.uniform(5, 15))  # "Read" the post

                        # Randomly vote on posts (organic behavior)
                        vote_chance = random.random()
                        try:
                            if vote_chance < 0.2:
                                # 20% chance to upvote
                                upvote = self.page.query_selector('button[aria-label="upvote"]')
                                if upvote:
                                    self._human_click(upvote)
                            elif vote_chance < 0.35:
                                # 15% chance to downvote (0.2 to 0.35 range)
                                downvote = self.page.query_selector('button[aria-label="downvote"]')
                                if downvote:
                                    self._human_click(downvote)
                        except:
                            pass

                        # Go back
                        self.page.go_back()
                        time.sleep(random.uniform(2, 4))

                # Random pause
                time.sleep(random.uniform(3, 8))

        except Exception as e:
            print(f"Browse error: {e}")

    # Popular subreddits for organic browsing
    POPULAR_SUBREDDITS = [
        "funny", "pics", "gaming", "aww", "music", "movies", "todayilearned",
        "worldnews", "videos", "askreddit", "science", "books", "food",
        "sports", "memes", "interestingasfuck", "nextfuckinglevel"
    ]

    def personalize_account(self, username: str) -> bool:
        """
        Set up avatar and display name if not already personalized.
        This should only run once per account.

        Returns True if personalized or already done.
        """
        try:
            print(f"[DEBUG] Checking if {username} needs personalization...")

            # Navigate to profile settings
            self.page.goto(f"{REDDIT_BASE_URL}/settings/profile", wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(2, 4))

            # Handle cookie popup if present
            try:
                cookie_accept = self.page.query_selector('button:has-text("Accept All")')
                if cookie_accept and cookie_accept.is_visible():
                    self._human_click(cookie_accept)
                    time.sleep(random.uniform(0.5, 1))
            except:
                pass

            personalized = False

            # Check for and set display name if empty
            try:
                display_name_input = self.page.query_selector('input[name="displayName"], input[id*="displayName"]')
                if display_name_input:
                    current_name = display_name_input.input_value()
                    if not current_name or current_name.strip() == "":
                        # Set display name to a variation of username
                        display_name = username.replace("_", " ").title()
                        print(f"[DEBUG] Setting display name: {display_name}")
                        display_name_input.click()
                        display_name_input.fill("")
                        self._human_type(display_name_input, display_name)
                        personalized = True
                        time.sleep(random.uniform(1, 2))
            except Exception as e:
                print(f"[DEBUG] Display name setup failed: {e}")

            # Try to open avatar customization
            try:
                avatar_selectors = [
                    'button:has-text("Style Avatar")',
                    'button:has-text("Create Avatar")',
                    'a[href*="/avatar"]',
                    'button:has-text("avatar")',
                ]

                for selector in avatar_selectors:
                    try:
                        avatar_btn = self.page.query_selector(selector)
                        if avatar_btn and avatar_btn.is_visible():
                            print("[DEBUG] Opening avatar customization...")
                            self._human_click(avatar_btn)
                            time.sleep(random.uniform(3, 5))

                            # Click random customization options (limited interaction)
                            # Just clicking a few options to set up basic avatar
                            for _ in range(random.randint(2, 4)):
                                try:
                                    # Look for clickable avatar options
                                    options = self.page.query_selector_all('button[class*="avatar"], div[role="button"]')
                                    if options:
                                        option = random.choice(options[:20])
                                        if option.is_visible():
                                            self._human_click(option)
                                            time.sleep(random.uniform(0.5, 1.5))
                                except:
                                    pass

                            # Save avatar if there's a save button
                            try:
                                save_btn = self.page.query_selector('button:has-text("Save"), button:has-text("Done")')
                                if save_btn and save_btn.is_visible():
                                    self._human_click(save_btn)
                                    time.sleep(random.uniform(1, 2))
                                    personalized = True
                            except:
                                pass

                            break
                    except:
                        continue
            except Exception as e:
                print(f"[DEBUG] Avatar setup failed: {e}")

            # Try to save profile changes if there's a save button
            try:
                save_selectors = ['button:has-text("Save")', 'button[type="submit"]']
                for selector in save_selectors:
                    save_btn = self.page.query_selector(selector)
                    if save_btn and save_btn.is_visible():
                        self._human_click(save_btn)
                        time.sleep(random.uniform(1, 2))
                        break
            except:
                pass

            print(f"[DEBUG] Personalization {'completed' if personalized else 'skipped (already done or failed)'}")
            return True  # Return True even if nothing changed to avoid retrying

        except Exception as e:
            print(f"[DEBUG] Personalization error: {e}")
            return False

    def worker_browse_session(self, duration_seconds: int, username: str = None, personalize: bool = False, on_action: callable = None):
        """
        Enhanced worker browsing session with randomized human-like behavior.

        Args:
            duration_seconds: Max session duration (1-5 minutes recommended)
            username: Username for logging purposes
            personalize: If True, attempt account personalization first
            on_action: Optional callback function(action_type, details) for progress reporting
        """
        def log_action(action_type: str, details: str = None):
            """Log action to console and call callback if provided."""
            msg = f"[{username}] {action_type}"
            if details:
                msg += f": {details}"
            print(msg)
            if on_action:
                try:
                    on_action(action_type, details)
                except:
                    pass

        try:
            log_action("SESSION_START", f"duration={duration_seconds}s")

            # Step 1: Personalize account if requested (only once per account)
            if personalize and username:
                log_action("PERSONALIZING", "Setting up account profile")
                self.personalize_account(username)
                time.sleep(random.uniform(1, 2))

            # Step 2: Go to homepage
            log_action("NAVIGATING", "Going to Reddit homepage")
            self.page.goto(REDDIT_BASE_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(2, 4))

            # Handle cookie popup
            try:
                cookie_accept = self.page.query_selector('button:has-text("Accept All")')
                if cookie_accept and cookie_accept.is_visible():
                    self._human_click(cookie_accept)
                    time.sleep(random.uniform(0.5, 1))
            except:
                pass

            start_time = time.time()
            action_count = 0

            # Step 3: Execute random actions until time runs out
            while time.time() - start_time < duration_seconds:
                action_count += 1
                elapsed = int(time.time() - start_time)

                # Weighted random action selection
                action_roll = random.random()

                if action_roll < 0.35:
                    # 35% - Just scroll the feed
                    log_action("SCROLL_FEED", f"Action {action_count} ({elapsed}s)")
                    self.scroll_page(min_scrolls=2, max_scrolls=4)

                elif action_roll < 0.65:
                    # 30% - Click and view a post
                    log_action("VIEW_POST", f"Action {action_count} ({elapsed}s)")
                    try:
                        posts = self.page.query_selector_all('a[data-click-id="body"], article a[href*="/comments/"]')
                        if posts:
                            post = random.choice(posts[:10])
                            self._human_click(post)
                            time.sleep(random.uniform(5, 15))  # "Read" the post

                            # Random voting while viewing post
                            vote_roll = random.random()
                            try:
                                if vote_roll < 0.25:
                                    # 25% upvote
                                    upvote = self.page.query_selector('button[aria-label*="upvote"], button[aria-label*="Upvote"]')
                                    if upvote:
                                        self._human_click(upvote)
                                        log_action("UPVOTE", "Upvoted post")
                                elif vote_roll < 0.35:
                                    # 10% downvote
                                    downvote = self.page.query_selector('button[aria-label*="downvote"], button[aria-label*="Downvote"]')
                                    if downvote:
                                        self._human_click(downvote)
                                        log_action("DOWNVOTE", "Downvoted post")
                            except:
                                pass

                            # Maybe scroll comments
                            if random.random() < 0.4:
                                self.scroll_page(min_scrolls=1, max_scrolls=3)

                            self.page.go_back()
                            time.sleep(random.uniform(2, 4))
                    except Exception as e:
                        log_action("ERROR", f"Post view failed: {e}")

                elif action_roll < 0.85:
                    # 20% - Visit a random popular subreddit
                    subreddit = random.choice(self.POPULAR_SUBREDDITS)
                    log_action("VISIT_SUBREDDIT", f"r/{subreddit} (Action {action_count}, {elapsed}s)")
                    try:
                        self.page.goto(f"{REDDIT_BASE_URL}/r/{subreddit}", wait_until="domcontentloaded", timeout=30000)
                        time.sleep(random.uniform(2, 4))
                        self.scroll_page(min_scrolls=2, max_scrolls=4)

                        # Maybe join the subreddit (10% chance)
                        if random.random() < 0.1:
                            try:
                                join_btn = self.page.query_selector('button:has-text("Join")')
                                if join_btn and join_btn.is_visible():
                                    self._human_click(join_btn)
                                    log_action("JOIN_SUBREDDIT", f"Joined r/{subreddit}")
                                    time.sleep(random.uniform(1, 2))
                            except:
                                pass

                        # Go back to homepage
                        self.page.goto(REDDIT_BASE_URL, wait_until="domcontentloaded", timeout=30000)
                        time.sleep(random.uniform(2, 3))
                    except Exception as e:
                        log_action("ERROR", f"Subreddit visit failed: {e}")

                elif action_roll < 0.95:
                    # 10% - Check notifications
                    log_action("CHECK_NOTIFICATIONS", f"Action {action_count} ({elapsed}s)")
                    try:
                        notif_selectors = [
                            'button[aria-label*="notification"]',
                            'a[aria-label*="Inbox"]',
                            'button[aria-label*="Open inbox"]',
                        ]
                        for selector in notif_selectors:
                            notif_btn = self.page.query_selector(selector)
                            if notif_btn and notif_btn.is_visible():
                                self._human_click(notif_btn)
                                time.sleep(random.uniform(3, 6))
                                # Close or go back
                                self.page.keyboard.press("Escape")
                                time.sleep(random.uniform(1, 2))
                                break
                    except Exception as e:
                        log_action("ERROR", f"Notification check failed: {e}")

                else:
                    # 5% - Just idle (simulates reading)
                    log_action("IDLE", f"Reading content (Action {action_count}, {elapsed}s)")
                    time.sleep(random.uniform(3, 8))

                # Random pause between actions
                time.sleep(random.uniform(2, 6))

            total_duration = int(time.time() - start_time)
            log_action("SESSION_COMPLETE", f"Actions: {action_count}, Duration: {total_duration}s")
            return {"actions": action_count, "duration": total_duration}

        except Exception as e:
            log_action("SESSION_ERROR", str(e))
            return {"actions": 0, "duration": 0, "error": str(e)}

    def check_account_status(self, username: str) -> str:
        """
        Check if account is banned/suspended by viewing profile from an external,
        non-logged-in perspective.

        This method should be called with a browser started via start_health_checker().

        Returns:
            str: 'active' or 'banned'
        """
        try:
            # Navigate to profile page (not logged in)
            response = self.page.goto(
                f"{REDDIT_BASE_URL}/user/{username}",
                wait_until="domcontentloaded",
                timeout=30000
            )
            time.sleep(3)  # Allow page to fully render

            # Get page content
            page_content = self.page.content().lower()

            # Check for any ban/suspension indicators
            ban_indicators = [
                "this account has been suspended",
                "account has been suspended",
                "this account has been banned",
                "account has been banned",
                "suspended user",
            ]

            if any(indicator in page_content for indicator in ban_indicators):
                print(f"{username}: Account is BANNED/SUSPENDED")
                return "banned"

            # If no ban indicators found, account is active
            print(f"{username}: Account appears active")
            return "active"

        except Exception as e:
            print(f"Health check error for {username}: {e}")
            # On error, assume active (benefit of doubt)
            return "active"

    def check_login_status(self, username: str, take_screenshot: bool = False) -> str:
        """
        Check if we're currently logged into this account.
        Delegates to is_logged_in() to ensure consistent detection logic.

        This method should be called with a browser started via start(account_id).

        Args:
            username: Username for logging purposes
            take_screenshot: If True, saves a screenshot for debugging

        Returns:
            str: 'logged_in' or 'not_logged_in'
        """
        is_logged = self.is_logged_in(username=username, take_screenshot=take_screenshot)
        result = "logged_in" if is_logged else "not_logged_in"
        print(f"{username}: {result}")
        return result

    def enable_mature_content(self, username: str) -> bool:
        """
        Enable "Show mature content (I'm over 18)" on new Reddit preferences.

        This method should be called with a browser started via start(account_id).

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            print(f"{username}: Enabling mature content setting...")

            # Navigate to new Reddit preferences
            self.page.goto("https://www.reddit.com/settings/preferences", wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            # Find the "Show mature content" toggle
            # New Reddit uses various toggle elements
            toggle_selectors = [
                # Text-based selectors
                'text="Show mature content (I\'m over 18)" >> xpath=ancestor::*[contains(@class, "setting")]//button',
                'text="Show mature content" >> xpath=../.. >> button',
                'text="Show mature content" >> xpath=../.. >> [role="switch"]',
                # Attribute-based selectors
                '[aria-label*="mature content"]',
                '[aria-label*="Show mature"]',
                'faceplate-switch-input',
                # Generic toggle near the text
                'button[role="switch"]',
            ]

            toggle = None
            for selector in toggle_selectors:
                try:
                    toggle = self.page.query_selector(selector)
                    if toggle:
                        break
                except Exception:
                    continue

            if not toggle:
                print(f"{username}: Could not find mature content toggle")
                return False

            # Check current state via aria-checked or similar
            is_enabled = toggle.get_attribute("aria-checked") == "true"

            if is_enabled:
                print(f"{username}: Mature content already enabled")
                return True

            # Click toggle to enable
            print(f"{username}: Clicking mature content toggle...")
            self._human_click(toggle)
            time.sleep(2)

            # Handle confirmation popup - "Yes, I'm Over 18"
            confirmation_selectors = [
                'button:has-text("Yes, I\'m Over 18")',
                'button:has-text("Yes, I\'m over 18")',
                'button:has-text("over 18")',
                '[data-testid="nsfw-interstitial-accept"]',
            ]

            print(f"{username}: Looking for age confirmation popup...")
            for selector in confirmation_selectors:
                try:
                    confirm_btn = self.page.wait_for_selector(selector, timeout=5000)
                    if confirm_btn and confirm_btn.is_visible():
                        print(f"{username}: Clicking confirmation button...")
                        self._human_click(confirm_btn)
                        time.sleep(2)
                        break
                except Exception:
                    continue

            # Verify toggle is now ON
            time.sleep(2)
            for selector in toggle_selectors:
                try:
                    toggle = self.page.query_selector(selector)
                    if toggle:
                        is_enabled = toggle.get_attribute("aria-checked") == "true"
                        if is_enabled:
                            print(f"{username}: Mature content enabled successfully")
                            return True
                except Exception:
                    continue

            print(f"{username}: Could not verify mature content was enabled")
            return False

        except Exception as e:
            print(f"{username}: Error enabling mature content: {e}")
            return False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
