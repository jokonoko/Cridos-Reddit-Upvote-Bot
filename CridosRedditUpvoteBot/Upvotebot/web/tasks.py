"""
Redis Queue tasks for background browser automation.
"""

import os
import time
import random
import uuid
from typing import Optional

from datetime import datetime

from redis import Redis
from rq import Queue, get_current_job

# Redis connection
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_conn: Optional[Redis] = None

# Queues
high_queue: Optional[Queue] = None
default_queue: Optional[Queue] = None
low_queue: Optional[Queue] = None


def init_redis():
    """Initialize Redis connection and queues."""
    global redis_conn, high_queue, default_queue, low_queue

    redis_conn = Redis.from_url(REDIS_URL)
    high_queue = Queue("high", connection=redis_conn)
    default_queue = Queue("default", connection=redis_conn)
    low_queue = Queue("low", connection=redis_conn)


def get_queue(priority: str = "default") -> Queue:
    """Get queue by priority."""
    if priority == "high":
        return high_queue
    elif priority == "low":
        return low_queue
    return default_queue


# Task functions (executed by worker)

def update_job_progress(event_type: str, **kwargs):
    """
    Update job progress with a new event.
    Events are stored in job.meta and can be polled by the frontend.
    """
    job = get_current_job()
    if not job:
        return

    # Initialize meta if needed
    if not job.meta:
        job.meta = {
            "events": [],
            "current_account": 0,
            "total_accounts": 0,
            "current_post": 0,
            "total_posts": 0,
            "success_count": 0,
            "failed_count": 0,
        }

    # Create event
    event = {
        "type": event_type,
        "timestamp": datetime.now().isoformat(),
        **kwargs
    }

    # Append event and update counters
    job.meta["events"].append(event)

    # Update counters based on event type
    if event_type == "account_start":
        job.meta["current_account"] = kwargs.get("account_index", 0)
        job.meta["total_accounts"] = kwargs.get("total_accounts", 0)
    elif event_type == "post_start":
        job.meta["current_post"] = kwargs.get("post_index", 0)
        job.meta["total_posts"] = kwargs.get("total_posts", 0)
    elif event_type == "upvote_success":
        job.meta["success_count"] += 1
    elif event_type in ("upvote_failed", "account_login_failed"):
        job.meta["failed_count"] += kwargs.get("failed_count", 1)

    # Save meta to Redis
    job.save_meta()


def task_upvote_posts(post_urls: list[str], account_count: int):
    """
    Task: Upvote multiple posts with randomized accounts.
    Uses account-first loop: each account upvotes all posts before moving to next account.
    This keeps browser open for all posts, reducing overhead significantly.

    Args:
        post_urls: List of Reddit post URLs to upvote
        account_count: Number of accounts to use
    """
    import logging
    from core.database import Database
    from core.browser import BrowserManager
    from core.proxy_manager import ProxyManager
    from config import DELAY_BETWEEN_POSTS_MIN, DELAY_BETWEEN_POSTS_MAX

    logger = logging.getLogger(__name__)
    db = Database()
    proxy_manager = ProxyManager()

    # Check if mobile rotation is enabled
    rotation_enabled = proxy_manager.is_rotation_enabled()

    # Get and shuffle accounts once
    accounts = db.get_active_accounts(limit=account_count)
    random.shuffle(accounts)

    logger.info(f"Starting upvote task: {len(post_urls)} posts × {len(accounts)} accounts")

    # Initialize job meta for progress tracking
    update_job_progress("task_start",
                       total_accounts=len(accounts),
                       total_posts=len(post_urls))

    # Initialize results structure per post
    post_results = {url: {"post_url": url, "success": 0, "failed": 0, "results": []} for url in post_urls}

    for i, account in enumerate(accounts):
        account_id = account["id"]
        username = account["username"]

        logger.info(f"[{i+1}/{len(accounts)}] Processing account: {username}")

        # Emit account start event
        update_job_progress("account_start",
                           account_index=i + 1,
                           total_accounts=len(accounts),
                           username=username)

        # IP rotation (once per account)
        if rotation_enabled:
            success_rotate, old_ip, new_ip = proxy_manager.rotate_ip(verify=True)
            if success_rotate:
                logger.info(f"IP rotated: {old_ip} -> {new_ip}")
                update_job_progress("ip_rotated",
                                   username=username,
                                   old_ip=old_ip or "unknown",
                                   new_ip=new_ip or "unknown")
            else:
                logger.warning(f"IP rotation may have failed for account {username}")
                update_job_progress("ip_rotation_failed", username=username)
            proxy = proxy_manager.get_mobile_proxy()
        else:
            proxy = account.get("proxy") or proxy_manager.format_proxy_for_provider(account_id)

        browser = BrowserManager()
        try:
            # Use unique profile_path to prevent reuse of banned account profiles
            profile_path = account.get("profile_path")
            if not profile_path:
                # Fallback for old accounts without profile_path
                profile_path = str(uuid.uuid4())
                db.set_profile_path(username, profile_path)
                logger.info(f"  Generated new profile for {username}: {profile_path}")

            browser.start(profile_path=profile_path, proxy=proxy, headless=True)

            # Skip login check - assume account is logged in (run login check manually beforehand)
            # This saves ~5-10 seconds per account

            # Upvote all posts with this browser session
            for j, post_url in enumerate(post_urls):
                # Emit post start event
                update_job_progress("post_start",
                                   post_index=j + 1,
                                   total_posts=len(post_urls),
                                   post_url=post_url,
                                   username=username)
                try:
                    success, error_msg = browser.upvote_post(post_url, account_id=account_id)
                    if success:
                        db.log_action(account_id, "upvote", post_url, "success")
                        post_results[post_url]["success"] += 1
                        post_results[post_url]["results"].append({
                            "account_id": account_id,
                            "username": username,
                            "success": True
                        })
                        logger.info(f"  ✓ {username} upvoted post {j+1}/{len(post_urls)}")
                        # Emit success event
                        update_job_progress("upvote_success",
                                           username=username,
                                           post_index=j + 1,
                                           total_posts=len(post_urls),
                                           post_url=post_url)
                    else:
                        db.log_action(account_id, "upvote", post_url, "failed", error_msg)
                        post_results[post_url]["failed"] += 1
                        post_results[post_url]["results"].append({
                            "account_id": account_id,
                            "username": username,
                            "success": False,
                            "error": error_msg
                        })
                        logger.warning(f"  ✗ {username} failed to upvote post {j+1}/{len(post_urls)}: {error_msg}")
                        # Emit failure event
                        update_job_progress("upvote_failed",
                                           username=username,
                                           post_index=j + 1,
                                           total_posts=len(post_urls),
                                           post_url=post_url,
                                           error=error_msg)
                except Exception as e:
                    db.log_action(account_id, "upvote", post_url, "failed", str(e))
                    post_results[post_url]["failed"] += 1
                    post_results[post_url]["results"].append({
                        "account_id": account_id,
                        "username": username,
                        "success": False,
                        "error": str(e)
                    })
                    logger.error(f"  ✗ {username} error on post {j+1}: {e}")
                    # Emit error event
                    update_job_progress("upvote_failed",
                                       username=username,
                                       post_index=j + 1,
                                       total_posts=len(post_urls),
                                       post_url=post_url,
                                       error=str(e)[:200])

                # Small delay between posts (except last post)
                if j < len(post_urls) - 1:
                    delay = random.uniform(DELAY_BETWEEN_POSTS_MIN, DELAY_BETWEEN_POSTS_MAX)
                    time.sleep(delay)

            # Update last action after all posts done
            db.update_last_action(username)

        except Exception as e:
            logger.error(f"Browser error for {username}: {e}")
            # Emit browser error event
            failed_posts = sum(1 for post_url in post_urls
                             if not any(r["account_id"] == account_id for r in post_results[post_url]["results"]))
            update_job_progress("browser_error",
                               username=username,
                               account_index=i + 1,
                               total_accounts=len(accounts),
                               error=str(e)[:200],
                               failed_count=failed_posts)
            # Mark remaining posts as failed if browser crashed
            for post_url in post_urls:
                if not any(r["account_id"] == account_id for r in post_results[post_url]["results"]):
                    post_results[post_url]["failed"] += 1
                    post_results[post_url]["results"].append({
                        "account_id": account_id,
                        "username": username,
                        "success": False,
                        "error": str(e)
                    })
        finally:
            browser.stop()

        # No delay between accounts - IP rotation provides separation
        # (rotation takes ~5s which is enough)

    # Calculate totals
    total_success = sum(r["success"] for r in post_results.values())
    total_failed = sum(r["failed"] for r in post_results.values())

    logger.info(f"Completed: {total_success} success, {total_failed} failed")

    return {
        "post_urls": post_urls,
        "total_posts": len(post_urls),
        "account_count": len(accounts),
        "total_success": total_success,
        "total_failed": total_failed,
        "posts": list(post_results.values()),
    }


def task_check_health(account_ids: list[int], fix: bool = False):
    """
    Task: Check health of accounts using external clean profile.
    Each account is checked from a non-logged-in perspective.
    """
    import logging
    from core.database import Database
    from core.browser import BrowserManager
    from core.proxy_manager import ProxyManager

    logger = logging.getLogger(__name__)
    db = Database()
    proxy_manager = ProxyManager()

    results = []

    # Initialize progress tracking
    update_job_progress("task_start",
                       total_accounts=len(account_ids),
                       message="Starting health check (external validation)")

    # Start ONE browser instance with health checker profile
    # This browser will be reused for all checks
    browser = BrowserManager()

    try:
        # Rotate IP before health checks (if rotation enabled)
        if proxy_manager.is_rotation_enabled():
            success_rotate, old_ip, new_ip = proxy_manager.rotate_ip(verify=True)
            if success_rotate:
                logger.info(f"IP rotated for health check: {old_ip} -> {new_ip}")
            time.sleep(2)
            proxy = proxy_manager.get_mobile_proxy()
        else:
            # For health checks, we can use any proxy or no proxy
            proxy = None

        # Start health checker browser (clean profile)
        logger.info("Starting health checker browser (clean profile)...")
        browser.start_health_checker(proxy=proxy, headless=True)

        # Check each account
        for i, account_id in enumerate(account_ids):
            account = db.get_account_by_id(account_id)
            if not account:
                results.append({"account_id": account_id, "status": "not_found"})
                update_job_progress("account_failed",
                                   account_index=i + 1,
                                   total_accounts=len(account_ids),
                                   account_id=account_id,
                                   error="Account not found in database")
                continue

            username = account["username"]
            logger.info(f"[{i+1}/{len(account_ids)}] Checking: {username}")

            update_job_progress("account_start",
                               account_index=i + 1,
                               total_accounts=len(account_ids),
                               username=username,
                               current_status=account.get("status"))

            try:
                # Perform external health check
                status = browser.check_account_status(username)

                # Update database
                db.update_account_status(username, status)
                db.update_last_health_check(username, datetime.now().isoformat())
                results.append({
                    "account_id": account_id,
                    "username": username,
                    "status": status
                })

                update_job_progress("check_complete",
                                   account_index=i + 1,
                                   total_accounts=len(account_ids),
                                   username=username,
                                   status=status)

            except Exception as e:
                logger.error(f"  Error checking {username}: {e}")
                db.update_account_status(username, "unknown")
                db.update_last_health_check(username, datetime.now().isoformat())
                results.append({
                    "account_id": account_id,
                    "username": username,
                    "status": "unknown",
                    "error": str(e)
                })
                update_job_progress("check_failed",
                                   account_index=i + 1,
                                   total_accounts=len(account_ids),
                                   username=username,
                                   error=str(e)[:200])

            # Small delay between checks to avoid rate limiting
            if i < len(account_ids) - 1:
                time.sleep(random.uniform(2, 5))

    except Exception as e:
        logger.error(f"Health check browser error: {e}")
        # Mark remaining accounts as unknown if browser crashed
        for account_id in account_ids:
            if not any(r["account_id"] == account_id for r in results):
                account = db.get_account_by_id(account_id)
                if account:
                    db.update_account_status(account["username"], "unknown")
                    db.update_last_health_check(account["username"], datetime.now().isoformat())
                    results.append({
                        "account_id": account_id,
                        "username": account["username"],
                        "status": "unknown",
                        "error": f"Browser error: {str(e)}"
                    })
    finally:
        browser.stop()

    logger.info(f"Health check completed: {len(results)} accounts checked")

    return {"results": results, "total": len(results)}


def task_add_account(username: str, password: str, email: str = None, proxy: str = None, notes: str = None):
    """
    Task: Add and verify a new account.
    """
    from core.database import Database
    from core.browser import BrowserManager
    from core.proxy_manager import ProxyManager
    from config import PROFILES_DIR

    db = Database()
    proxy_manager = ProxyManager()

    # Check if exists
    if db.account_exists(username):
        return {"success": False, "error": "Account already exists"}

    # Add to database (profile_path is auto-generated as UUID)
    account_id = db.add_account(
        username=username,
        password=password,
        email=email,
        proxy=proxy,
        notes=notes,
    )

    # Get account to retrieve the auto-generated profile_path
    account = db.get_account_by_id(account_id)
    profile_path = account["profile_path"]

    # Rotate IP before adding account (if rotation enabled)
    if proxy_manager.is_rotation_enabled():
        proxy_manager.rotate_ip(verify=False)
        time.sleep(2)
        account_proxy = proxy_manager.get_mobile_proxy()
    else:
        account_proxy = proxy or proxy_manager.format_proxy_for_provider(account_id)

    # Perform login
    browser = BrowserManager()
    try:
        browser.start(profile_path=profile_path, proxy=account_proxy, headless=True)

        if browser.is_logged_in(username):
            return {"success": True, "account_id": account_id, "message": "Already logged in from previous session"}

        if browser.login(username, password):
            return {"success": True, "account_id": account_id, "message": "Login successful"}
        else:
            db.update_account_status(username, "unknown")
            return {"success": True, "account_id": account_id, "message": "Account added but login failed - may need manual verification"}

    except Exception as e:
        db.update_account_status(username, "unknown")
        return {"success": True, "account_id": account_id, "message": f"Account added but error during login: {e}"}
    finally:
        browser.stop()


def task_retry_login(account_ids: list[int]):
    """
    Task: Retry login for accounts that are not logged in or suspended.
    This task specifically attempts to login to accounts and verify their status.
    """
    import logging
    from datetime import datetime
    from pathlib import Path
    from core.database import Database
    from core.browser import BrowserManager
    from core.proxy_manager import ProxyManager

    logger = logging.getLogger(__name__)
    db = Database()
    proxy_manager = ProxyManager()

    results = []

    # Initialize job meta for progress tracking
    update_job_progress("task_start",
                       total_accounts=len(account_ids),
                       message="Starting login retry for accounts")

    for i, account_id in enumerate(account_ids):
        account = db.get_account_by_id(account_id)
        if not account:
            results.append({
                "account_id": account_id,
                "status": "not_found",
                "success": False,
                "message": "Account not found in database"
            })
            update_job_progress("account_failed",
                               account_index=i + 1,
                               total_accounts=len(account_ids),
                               account_id=account_id,
                               error="Account not found")
            continue

        username = account["username"]
        logger.info(f"[{i+1}/{len(account_ids)}] Retrying login for: {username}")

        update_job_progress("account_start",
                           account_index=i + 1,
                           total_accounts=len(account_ids),
                           username=username,
                           current_status=account.get("status"))

        # Rotate IP before login attempt (if rotation enabled)
        if proxy_manager.is_rotation_enabled():
            success_rotate, old_ip, new_ip = proxy_manager.rotate_ip(verify=True)
            if success_rotate:
                logger.info(f"IP rotated: {old_ip} -> {new_ip}")
                update_job_progress("ip_rotated",
                                   username=username,
                                   old_ip=old_ip or "unknown",
                                   new_ip=new_ip or "unknown")
            time.sleep(2)
            proxy = proxy_manager.get_mobile_proxy()
        else:
            proxy = account.get("proxy") or proxy_manager.format_proxy_for_provider(account_id)

        browser = BrowserManager()
        try:
            # Use unique profile_path to prevent reuse of banned account profiles
            profile_path = account.get("profile_path")
            if not profile_path:
                # Fallback for old accounts without profile_path
                profile_path = str(uuid.uuid4())
                db.set_profile_path(username, profile_path)
                logger.info(f"  Generated new profile for {username}: {profile_path}")

            browser.start(profile_path=profile_path, proxy=proxy, headless=True)

            # Attempt login with retry loop - delete old profile and try with new one until success
            max_retries = 3
            retry_count = 0
            login_success = False

            while not login_success and retry_count < max_retries:
                retry_count += 1
                logger.info(f"  Attempting login for {username}... (attempt {retry_count}/{max_retries})")

                # BEFORE login attempt: check login status with screenshot
                logger.info(f"  Checking login status BEFORE attempt {retry_count}...")
                is_already_logged_in = browser.is_logged_in(username, take_screenshot=True)

                if is_already_logged_in:
                    logger.info(f"  ✓ {username} is already logged in (detected before attempt {retry_count})")
                    db.update_account_status(username, "active")
                    db.update_login_status(username, "logged_in")
                    db.update_last_health_check(username, datetime.now().isoformat())
                    results.append({
                        "account_id": account_id,
                        "username": username,
                        "status": "active",
                        "success": True,
                        "message": f"Already logged in (detected at attempt {retry_count})"
                    })
                    update_job_progress("login_success",
                                       username=username,
                                       account_index=i + 1,
                                       total_accounts=len(account_ids),
                                       status="active",
                                       message="Already logged in")
                    login_success = True
                    break

                # Perform login attempt
                login_result = browser.login(username, account["password"])

                # AFTER login attempt: check login status with screenshot
                logger.info(f"  Checking login status AFTER attempt {retry_count}...")
                is_logged_in_after = browser.is_logged_in(username, take_screenshot=True)

                if is_logged_in_after:
                    db.update_account_status(username, "active")
                    db.update_login_status(username, "logged_in")
                    db.update_last_health_check(username, datetime.now().isoformat())
                    logger.info(f"  ✓ {username} login successful after {retry_count} attempt(s)")
                    results.append({
                        "account_id": account_id,
                        "username": username,
                        "status": "active",
                        "success": True,
                        "message": f"Login successful after {retry_count} attempt(s)"
                    })
                    update_job_progress("login_success",
                                       username=username,
                                       account_index=i + 1,
                                       total_accounts=len(account_ids),
                                       status="active",
                                       message=f"Login successful after {retry_count} attempt(s)")
                    login_success = True
                else:
                    # Login failed (verified by is_logged_in check)
                    logger.warning(f"  ✗ {username} login failed (attempt {retry_count}/{max_retries})")

                    # If we haven't reached max retries, delete old profile and create new one
                    if retry_count < max_retries:
                        logger.info(f"  Deleting old profile and generating new one for retry...")

                        # Stop browser to release profile
                        browser.stop()

                        # Delete old profile directory
                        import shutil
                        from config import PROFILES_DIR
                        old_profile_dir = PROFILES_DIR / profile_path
                        if old_profile_dir.exists():
                            try:
                                shutil.rmtree(old_profile_dir)
                                logger.info(f"  Deleted old profile: {old_profile_dir}")
                            except Exception as del_e:
                                logger.warning(f"  Could not delete old profile: {del_e}")

                        # Generate new profile UUID
                        profile_path = str(uuid.uuid4())
                        db.set_profile_path(username, profile_path)
                        logger.info(f"  Generated new profile for retry: {profile_path}")

                        # Rotate IP before retry (if rotation enabled)
                        if proxy_manager.is_rotation_enabled():
                            success_rotate, old_ip, new_ip = proxy_manager.rotate_ip(verify=True)
                            if success_rotate:
                                logger.info(f"  IP rotated for retry: {old_ip} -> {new_ip}")
                                update_job_progress("ip_rotated",
                                                   username=username,
                                                   old_ip=old_ip or "unknown",
                                                   new_ip=new_ip or "unknown",
                                                   retry_attempt=retry_count + 1)
                            time.sleep(2)
                            proxy = proxy_manager.get_mobile_proxy()
                        else:
                            proxy = account.get("proxy") or proxy_manager.format_proxy_for_provider(account_id)

                        # Restart browser with new profile and (potentially new) proxy
                        browser = BrowserManager()
                        browser.start(profile_path=profile_path, proxy=proxy, headless=True)

                        # Small delay before retry
                        time.sleep(3)
                    else:
                        # Max retries reached, give up
                        # Check account status to determine if banned/suspended
                        account_status = browser.check_account_status(username)
                        db.update_account_status(username, account_status)
                        db.update_login_status(username, "not_logged_in")
                        db.update_last_health_check(username, datetime.now().isoformat())
                        logger.error(f"  ✗ {username} login failed after {max_retries} attempts, status: {account_status}")
                        results.append({
                            "account_id": account_id,
                            "username": username,
                            "status": account_status,
                            "success": False,
                            "message": f"Login failed after {max_retries} attempts - account may be {account_status}"
                        })
                        update_job_progress("login_failed",
                                           username=username,
                                           account_index=i + 1,
                                           total_accounts=len(account_ids),
                                           status=account_status,
                                           error=f"Login failed after {max_retries} attempts - {account_status}")

        except Exception as e:
            # Take screenshot on exception
            try:
                screenshots_dir = Path("/app/screenshots")
                screenshots_dir.mkdir(exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                screenshot_path = screenshots_dir / f"login_error_{username}_{timestamp}.png"
                browser.page.screenshot(path=str(screenshot_path), full_page=False)
                logger.info(f"  Screenshot saved: {screenshot_path}")
            except Exception as ss_e:
                logger.warning(f"  Screenshot failed: {ss_e}")

            logger.error(f"  ✗ Error for {username}: {e}")
            db.update_account_status(username, "unknown")
            db.update_last_health_check(username, datetime.now().isoformat())
            results.append({
                "account_id": account_id,
                "username": username,
                "status": "unknown",
                "success": False,
                "message": str(e),
                "error": str(e)
            })
            update_job_progress("login_failed",
                               username=username,
                               account_index=i + 1,
                               total_accounts=len(account_ids),
                               error=str(e)[:200])
        finally:
            browser.stop()

        # Small delay between attempts to avoid rate limiting
        if i < len(account_ids) - 1:
            time.sleep(random.uniform(5, 15))

    # Calculate summary
    successful = sum(1 for r in results if r["success"])
    failed = len(results) - successful

    logger.info(f"Retry login completed: {successful} successful, {failed} failed")

    return {
        "total_accounts": len(account_ids),
        "successful": successful,
        "failed": failed,
        "results": results
    }


def task_check_login_status(account_ids: list[int]):
    """
    Task: Check login status of accounts (whether we're currently logged in).
    Uses each account's own browser profile.
    """
    import logging
    from core.database import Database
    from core.browser import BrowserManager
    from core.proxy_manager import ProxyManager

    logger = logging.getLogger(__name__)
    db = Database()
    proxy_manager = ProxyManager()

    results = []

    # Initialize progress tracking
    update_job_progress("task_start",
                       total_accounts=len(account_ids),
                       message="Starting login status check")

    for i, account_id in enumerate(account_ids):
        account = db.get_account_by_id(account_id)
        if not account:
            results.append({"account_id": account_id, "login_status": "unknown"})
            update_job_progress("account_failed",
                               account_index=i + 1,
                               total_accounts=len(account_ids),
                               account_id=account_id,
                               error="Account not found in database")
            continue

        username = account["username"]
        logger.info(f"[{i+1}/{len(account_ids)}] Checking login status: {username}")

        update_job_progress("account_start",
                           account_index=i + 1,
                           total_accounts=len(account_ids),
                           username=username)

        # Rotate IP if enabled
        if proxy_manager.is_rotation_enabled():
            proxy_manager.rotate_ip(verify=False)
            time.sleep(2)
            proxy = proxy_manager.get_mobile_proxy()
        else:
            proxy = account.get("proxy") or proxy_manager.format_proxy_for_provider(account_id)

        browser = BrowserManager()
        try:
            # Start browser with account's profile
            browser.start(profile_path=str(account_id), proxy=proxy, headless=True)

            # Check login status (use is_logged_in directly)
            if browser.is_logged_in(username, take_screenshot=True):
                logger.info(f"  ✓ {username} is logged in")
                # Also check account status to update it (same as retry login)
                status = browser.check_account_status(username)
                db.update_account_status(username, status)
                db.update_login_status(username, "logged_in")
                db.update_last_health_check(username, datetime.now().isoformat())
                results.append({
                    "account_id": account_id,
                    "username": username,
                    "login_status": "logged_in",
                    "status": status
                })
            else:
                logger.info(f"  ✗ {username} is NOT logged in")
                db.update_login_status(username, "not_logged_in")
                results.append({
                    "account_id": account_id,
                    "username": username,
                    "login_status": "not_logged_in"
                })

            update_job_progress("check_complete",
                               account_index=i + 1,
                               total_accounts=len(account_ids),
                               username=username,
                               login_status=results[-1]["login_status"])

        except Exception as e:
            logger.error(f"  Error checking {username}: {e}")
            db.update_login_status(username, "unknown")
            results.append({
                "account_id": account_id,
                "username": username,
                "login_status": "unknown",
                "error": str(e)
            })
            update_job_progress("check_failed",
                               account_index=i + 1,
                               total_accounts=len(account_ids),
                               username=username,
                               error=str(e)[:200])
        finally:
            browser.stop()

        # Small delay between checks
        if i < len(account_ids) - 1:
            time.sleep(random.uniform(2, 5))

    logger.info(f"Login status check completed: {len(results)} accounts checked")

    return {"results": results, "total": len(results)}


def task_enable_mature_content(account_ids: list[int]):
    """
    Task: Enable mature content setting for accounts.
    """
    import logging
    from core.database import Database
    from core.browser import BrowserManager
    from core.proxy_manager import ProxyManager

    logger = logging.getLogger(__name__)
    db = Database()
    proxy_manager = ProxyManager()

    results = []

    # Initialize progress tracking
    update_job_progress("task_start",
                       total_accounts=len(account_ids),
                       message="Starting to enable mature content")

    for i, account_id in enumerate(account_ids):
        account = db.get_account_by_id(account_id)
        if not account:
            results.append({"account_id": account_id, "success": False, "error": "Account not found"})
            update_job_progress("account_failed",
                               account_index=i + 1,
                               total_accounts=len(account_ids),
                               account_id=account_id,
                               error="Account not found in database")
            continue

        username = account["username"]
        logger.info(f"[{i+1}/{len(account_ids)}] Enabling mature content for: {username}")

        update_job_progress("account_start",
                           account_index=i + 1,
                           total_accounts=len(account_ids),
                           username=username)

        # Rotate IP if enabled
        if proxy_manager.is_rotation_enabled():
            proxy_manager.rotate_ip(verify=False)
            time.sleep(2)
            proxy = proxy_manager.get_mobile_proxy()
        else:
            proxy = account.get("proxy") or proxy_manager.format_proxy_for_provider(account_id)

        browser = BrowserManager()
        try:
            # Start browser with account's profile
            browser.start(profile_path=str(account_id), proxy=proxy, headless=True)

            # Check if logged in, login if needed
            if not browser.is_logged_in(username):
                logger.info(f"  {username}: Not logged in, attempting login...")
                if not browser.login(username, account["password"]):
                    results.append({
                        "account_id": account_id,
                        "username": username,
                        "success": False,
                        "error": "Login failed"
                    })
                    update_job_progress("account_failed",
                                       account_index=i + 1,
                                       total_accounts=len(account_ids),
                                       username=username,
                                       error="Login failed")
                    continue

            # Enable mature content
            success = browser.enable_mature_content(username)

            results.append({
                "account_id": account_id,
                "username": username,
                "success": success
            })

            if success:
                update_job_progress("setting_updated",
                                   account_index=i + 1,
                                   total_accounts=len(account_ids),
                                   username=username,
                                   message="Mature content enabled")
            else:
                update_job_progress("account_failed",
                                   account_index=i + 1,
                                   total_accounts=len(account_ids),
                                   username=username,
                                   error="Failed to enable mature content")

        except Exception as e:
            logger.error(f"  Error for {username}: {e}")
            results.append({
                "account_id": account_id,
                "username": username,
                "success": False,
                "error": str(e)
            })
            update_job_progress("account_failed",
                               account_index=i + 1,
                               total_accounts=len(account_ids),
                               username=username,
                               error=str(e)[:200])
        finally:
            browser.stop()

        # Small delay between accounts
        if i < len(account_ids) - 1:
            time.sleep(random.uniform(2, 5))

    # Calculate summary
    successful = sum(1 for r in results if r["success"])
    failed = len(results) - successful

    logger.info(f"Mature content update completed: {successful} successful, {failed} failed")

    return {
        "total_accounts": len(account_ids),
        "successful": successful,
        "failed": failed,
        "results": results
    }


def task_worker_browse(account_id: int):
    """
    Task: Browse Reddit with account to simulate activity and build trust.
    Always uses IP rotation for each account.
    Includes personalization (avatar, display name) on first run.
    """
    from core.database import Database
    from core.browser import BrowserManager
    from core.proxy_manager import ProxyManager

    db = Database()
    proxy_manager = ProxyManager()

    account = db.get_account_by_id(account_id)
    if not account:
        return {"success": False, "error": "Account not found"}

    username = account["username"]
    profile_path = account.get("profile_path")

    # Always rotate IP before worker activity
    proxy_manager.rotate_ip(verify=False)
    time.sleep(2)
    proxy = proxy_manager.get_mobile_proxy()

    browser = BrowserManager()
    try:
        # Use profile_path if available, otherwise use account_id
        if profile_path:
            browser.start(profile_path=profile_path, proxy=proxy, headless=True)
        else:
            browser.start(profile_path=str(account_id), proxy=proxy, headless=True)

        if not browser.is_logged_in(username):
            if not browser.login(username, account["password"]):
                db.log_action(account_id, "worker", None, "failed", "Login failed")
                return {"success": False, "error": "Login failed"}

        # Check if account needs personalization (only once)
        needs_personalization = not account.get("is_personalized", False)

        # Shorter session duration to fit 60 accounts in 8 hours (1-5 minutes)
        session_duration = random.randint(60, 300)

        # Run enhanced worker session with randomized actions
        browser.worker_browse_session(
            duration_seconds=session_duration,
            username=username,
            personalize=needs_personalization
        )

        # Mark as personalized if it was attempted
        if needs_personalization:
            db.update_account(username, is_personalized=True)

        db.update_last_worker_run(username)
        db.log_action(account_id, "worker", None, "success")
        return {"success": True, "username": username, "duration": session_duration, "personalized": needs_personalization}

    except Exception as e:
        db.log_action(account_id, "worker", None, "failed", str(e))
        return {"success": False, "error": str(e)}
    finally:
        browser.stop()


def task_worker_batch(account_ids: list[int]):
    """
    Task: Process a batch of accounts for worker browsing.
    Processes accounts sequentially with detailed progress tracking.
    Marks each account as processed after completion.
    Supports cancellation via job stop signal.
    """
    import logging
    import signal
    from core.database import Database
    from core.browser import BrowserManager
    from core.proxy_manager import ProxyManager

    logger = logging.getLogger(__name__)
    db = Database()
    proxy_manager = ProxyManager()

    # Track if we should stop
    should_stop = False

    def handle_stop(signum, frame):
        nonlocal should_stop
        should_stop = True
        logger.info("Stop signal received, will stop after current account")

    # Register signal handler for graceful stop
    original_handler = signal.signal(signal.SIGTERM, handle_stop)

    results = {
        "total": len(account_ids),
        "processed": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "stopped": False,
        "accounts": []
    }

    logger.info(f"Starting worker batch: {len(account_ids)} accounts")

    # Initialize progress tracking
    update_job_progress("task_start",
                       total_accounts=len(account_ids),
                       message="Starting worker batch processing")

    try:
        for i, account_id in enumerate(account_ids):
            # Check if we should stop
            if should_stop:
                logger.info(f"Stopping batch at account {i+1}/{len(account_ids)}")
                results["stopped"] = True
                results["skipped"] = len(account_ids) - i
                update_job_progress("batch_stopped",
                                   account_index=i + 1,
                                   total_accounts=len(account_ids),
                                   message="Batch stopped by user")
                break

            account = db.get_account_by_id(account_id)
            if not account:
                logger.warning(f"[{i+1}/{len(account_ids)}] Account {account_id} not found, skipping")
                results["accounts"].append({
                    "account_id": account_id,
                    "success": False,
                    "error": "Account not found"
                })
                results["failed"] += 1
                continue

            username = account["username"]
            profile_path = account.get("profile_path")

            logger.info(f"[{i+1}/{len(account_ids)}] Processing: {username}")

            # Emit account start event
            update_job_progress("account_start",
                               account_index=i + 1,
                               total_accounts=len(account_ids),
                               username=username,
                               account_id=account_id)

            # Rotate IP before each account
            if proxy_manager.is_rotation_enabled():
                success_rotate, old_ip, new_ip = proxy_manager.rotate_ip(verify=True)
                if success_rotate:
                    logger.info(f"  IP rotated: {old_ip} -> {new_ip}")
                    update_job_progress("ip_rotated",
                                       username=username,
                                       old_ip=old_ip or "unknown",
                                       new_ip=new_ip or "unknown")
                else:
                    logger.warning(f"  IP rotation may have failed")
                    update_job_progress("ip_rotation_failed", username=username)
                time.sleep(2)
                proxy = proxy_manager.get_mobile_proxy()
            else:
                proxy = account.get("proxy") or proxy_manager.format_proxy_for_provider(account_id)

            browser = BrowserManager()
            account_result = {
                "account_id": account_id,
                "username": username,
                "success": False,
                "duration": 0,
                "error": None
            }

            try:
                # Start browser
                update_job_progress("browser_starting",
                                   username=username,
                                   account_index=i + 1,
                                   total_accounts=len(account_ids))

                if profile_path:
                    browser.start(profile_path=profile_path, proxy=proxy, headless=True)
                else:
                    browser.start(profile_path=str(account_id), proxy=proxy, headless=True)

                # Check login
                update_job_progress("checking_login",
                                   username=username,
                                   account_index=i + 1,
                                   total_accounts=len(account_ids))

                if not browser.is_logged_in(username):
                    logger.info(f"  {username}: Not logged in, attempting login...")
                    update_job_progress("login_attempt",
                                       username=username,
                                       account_index=i + 1,
                                       total_accounts=len(account_ids))

                    if not browser.login(username, account["password"]):
                        raise Exception("Login failed")

                    logger.info(f"  {username}: Login successful")
                    update_job_progress("login_success",
                                       username=username,
                                       account_index=i + 1,
                                       total_accounts=len(account_ids))

                # Check if account needs personalization
                needs_personalization = not account.get("is_personalized", False)

                # Session duration (1-5 minutes)
                session_duration = random.randint(60, 300)

                logger.info(f"  {username}: Starting browse session ({session_duration}s)")
                update_job_progress("browsing_started",
                                   username=username,
                                   account_index=i + 1,
                                   total_accounts=len(account_ids),
                                   duration=session_duration,
                                   personalize=needs_personalization)

                # Create callback for action logging
                def on_browser_action(action_type: str, details: str = None):
                    """Callback to report browser actions to job progress."""
                    logger.info(f"    [{username}] {action_type}: {details or ''}")
                    update_job_progress("browser_action",
                                       username=username,
                                       account_index=i + 1,
                                       total_accounts=len(account_ids),
                                       action_type=action_type,
                                       details=details)

                # Run browse session with action callback
                browser.worker_browse_session(
                    duration_seconds=session_duration,
                    username=username,
                    personalize=needs_personalization,
                    on_action=on_browser_action
                )

                # Mark as personalized if attempted
                if needs_personalization:
                    db.update_account(username, is_personalized=True)

                # Update timestamps and log success
                db.update_last_worker_run(username)
                db.mark_account_worker_processed(account_id)
                db.log_action(account_id, "worker", None, "success")

                account_result["success"] = True
                account_result["duration"] = session_duration
                results["success"] += 1

                logger.info(f"  {username}: Completed successfully ({session_duration}s)")
                update_job_progress("account_complete",
                                   username=username,
                                   account_index=i + 1,
                                   total_accounts=len(account_ids),
                                   success=True,
                                   duration=session_duration)

            except Exception as e:
                error_msg = str(e)[:200]
                logger.error(f"  {username}: Error - {error_msg}")

                db.log_action(account_id, "worker", None, "failed", error_msg)
                # Still mark as processed so we don't retry failed accounts endlessly
                db.mark_account_worker_processed(account_id)

                account_result["error"] = error_msg
                results["failed"] += 1

                update_job_progress("account_failed",
                                   username=username,
                                   account_index=i + 1,
                                   total_accounts=len(account_ids),
                                   error=error_msg)

            finally:
                browser.stop()

            results["accounts"].append(account_result)
            results["processed"] += 1

            # Small delay between accounts (beyond IP rotation time)
            if i < len(account_ids) - 1 and not should_stop:
                delay = random.uniform(3, 8)
                time.sleep(delay)

    finally:
        # Restore original signal handler
        signal.signal(signal.SIGTERM, original_handler)

    logger.info(f"Worker batch completed: {results['success']} success, {results['failed']} failed, {results['skipped']} skipped")

    # Final progress update
    update_job_progress("batch_complete",
                       total_accounts=results["total"],
                       processed=results["processed"],
                       success=results["success"],
                       failed=results["failed"],
                       skipped=results["skipped"],
                       stopped=results["stopped"])

    return results


# Enqueue functions (called from web app)

def enqueue_upvote(post_urls: list[str], account_count: int):
    """Enqueue upvote task for multiple posts.

    Args:
        post_urls: List of Reddit post URLs to upvote
        account_count: Number of accounts to use per post
    """
    # Calculate timeout based on number of posts and accounts
    # Assume max 3 minutes per account per post
    estimated_time = len(post_urls) * account_count * 180
    job_timeout = max(3600, estimated_time + 600)  # At least 1 hour, plus buffer

    job = high_queue.enqueue(
        task_upvote_posts,
        post_urls,
        account_count,
        job_timeout=job_timeout,
    )
    return job.id


def enqueue_health_check(account_ids: list[int], fix: bool = False):
    """Enqueue health check task."""
    job = default_queue.enqueue(
        task_check_health,
        account_ids,
        fix,
        job_timeout=1800,  # 30 min timeout
    )
    return job.id


def enqueue_add_account(username: str, password: str, email: str = None, proxy: str = None, notes: str = None):
    """Enqueue add account task."""
    job = high_queue.enqueue(
        task_add_account,
        username,
        password,
        email,
        proxy,
        notes,
        job_timeout=300,  # 5 min timeout
    )
    return job.id


def enqueue_worker_browse(account_id: int):
    """Enqueue worker browse task."""
    job = low_queue.enqueue(
        task_worker_browse,
        account_id,
        job_timeout=900,  # 15 min timeout
    )
    return job.id


def enqueue_worker_batch(account_ids: list[int]):
    """Enqueue worker batch task for processing multiple accounts sequentially."""
    # Calculate timeout: ~10 minutes per account max (browse + IP rotation + delays)
    estimated_time = len(account_ids) * 600
    job_timeout = max(3600, estimated_time + 600)  # At least 1 hour, plus buffer

    job = low_queue.enqueue(
        task_worker_batch,
        account_ids,
        job_timeout=job_timeout,
    )
    return job.id


def get_active_worker_batch_job():
    """Get the currently running worker batch job if any."""
    from rq.job import Job

    # Check low queue for running jobs
    try:
        # Get all jobs in started state from the registry
        from rq.registry import StartedJobRegistry
        registry = StartedJobRegistry(queue=low_queue)
        job_ids = registry.get_job_ids()

        for job_id in job_ids:
            try:
                job = Job.fetch(job_id, connection=redis_conn)
                # Check if it's a worker batch job
                if job.func_name and 'task_worker_batch' in job.func_name:
                    return {
                        "id": job.id,
                        "status": job.get_status(),
                        "meta": job.meta or {},
                        "started_at": job.started_at.isoformat() if job.started_at else None
                    }
            except Exception:
                continue
    except Exception:
        pass

    return None


def enqueue_retry_login(account_ids: list[int]):
    """Enqueue retry login task for accounts."""
    # Calculate timeout based on number of accounts
    # Assume max 2 minutes per account
    estimated_time = len(account_ids) * 120
    job_timeout = max(900, estimated_time + 300)  # At least 15 min, plus buffer

    job = high_queue.enqueue(
        task_retry_login,
        account_ids,
        job_timeout=job_timeout,
    )
    return job.id


def enqueue_check_login_status(account_ids: list[int]):
    """Enqueue login status check task for accounts."""
    # Calculate timeout based on number of accounts
    # Assume max 1 minute per account
    estimated_time = len(account_ids) * 60
    job_timeout = max(600, estimated_time + 300)  # At least 10 min, plus buffer

    job = default_queue.enqueue(
        task_check_login_status,
        account_ids,
        job_timeout=job_timeout,
    )
    return job.id


def enqueue_enable_mature_content(account_ids: list[int]):
    """Enqueue mature content enabling task for accounts."""
    # Calculate timeout based on number of accounts
    # Assume max 2 minutes per account
    estimated_time = len(account_ids) * 120
    job_timeout = max(900, estimated_time + 300)  # At least 15 min, plus buffer

    job = default_queue.enqueue(
        task_enable_mature_content,
        account_ids,
        job_timeout=job_timeout,
    )
    return job.id


def get_job_status(job_id: str) -> dict:
    """Get status of a job including progress meta for in-progress jobs."""
    from rq.job import Job

    try:
        job = Job.fetch(job_id, connection=redis_conn)
        status = job.get_status()

        result = {
            "id": job.id,
            "status": status,
            "result": job.result if job.is_finished else None,
            "error": str(job.exc_info) if job.is_failed else None,
            "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "ended_at": job.ended_at.isoformat() if job.ended_at else None,
        }

        # Include meta data for in-progress jobs (contains live progress events)
        if status == "started" and job.meta:
            result["meta"] = job.meta

        return result
    except Exception as e:
        return {"id": job_id, "status": "not_found", "error": str(e)}


def get_queue_stats() -> dict:
    """Get queue statistics."""
    return {
        "high": {
            "queued": len(high_queue) if high_queue else 0,
        },
        "default": {
            "queued": len(default_queue) if default_queue else 0,
        },
        "low": {
            "queued": len(low_queue) if low_queue else 0,
        },
    }


def cancel_job(job_id: str) -> dict:
    """Cancel a job by ID. Works for queued or running jobs."""
    from rq.job import Job
    from rq.command import send_stop_job_command

    try:
        job = Job.fetch(job_id, connection=redis_conn)
        status = job.get_status()

        if status == "finished":
            return {"success": False, "error": "Job already finished", "status": status}

        if status == "failed":
            return {"success": False, "error": "Job already failed", "status": status}

        if status == "started":
            # Send stop command to worker for running job
            send_stop_job_command(redis_conn, job_id)
            return {"success": True, "message": "Stop signal sent to running job", "status": "cancelling"}

        # For queued jobs, just cancel them
        job.cancel()
        return {"success": True, "message": "Job cancelled", "status": "cancelled"}

    except Exception as e:
        return {"success": False, "error": str(e)}
