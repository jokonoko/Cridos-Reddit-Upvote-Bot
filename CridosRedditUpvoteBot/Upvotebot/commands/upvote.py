import time
import random
import re

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from core.database import Database
from core.browser import BrowserManager
from core.proxy_manager import ProxyManager
from config import MIN_ACTION_DELAY, MAX_ACTION_DELAY, DELAY_BETWEEN_POSTS_MIN, DELAY_BETWEEN_POSTS_MAX

console = Console()
db = Database()
proxy_manager = ProxyManager()


def validate_reddit_url(url: str) -> bool:
    """Validate that URL is a Reddit post URL."""
    pattern = r"https?://(www\.|old\.)?reddit\.com/r/\w+/comments/\w+"
    return bool(re.match(pattern, url))


@click.command("upvote")
@click.argument("post_urls", nargs=-1, required=True)
@click.option("--accounts", "-n", default=None, type=int, help="Number of accounts to use (default: all active)")
@click.option("--usernames", "-u", default=None, help="Comma-separated list of specific usernames")
@click.option("--dry-run", is_flag=True, help="Show what would happen without doing it")
def upvote(post_urls: tuple, accounts: int, usernames: str, dry_run: bool):
    """Upvote Reddit post(s) with multiple accounts.

    POST_URLS: One or more Reddit post URLs to upvote

    Uses account-first loop: each account upvotes all posts before moving to next.
    This keeps browser open for all posts, reducing overhead significantly.

    Examples:
        cli upvote https://reddit.com/r/sub/comments/abc
        cli upvote URL1 URL2 URL3 --accounts 50
    """
    post_urls = list(post_urls)

    # Validate all URLs
    invalid_urls = [url for url in post_urls if not validate_reddit_url(url)]
    if invalid_urls:
        console.print("[red]Invalid Reddit post URL(s):[/red]")
        for url in invalid_urls:
            console.print(f"  [red]✗[/red] {url}")
        console.print("[dim]Expected format: https://reddit.com/r/subreddit/comments/id/title[/dim]")
        return

    # Get accounts to use
    if usernames:
        username_list = [u.strip() for u in usernames.split(",")]
        account_list = []
        for uname in username_list:
            acc = db.get_account(uname)
            if acc and acc["status"] == "active":
                account_list.append(acc)
            else:
                console.print(f"[yellow]Skipping {uname}: not found or not active[/yellow]")
    else:
        account_list = db.get_active_accounts(limit=accounts)

    if not account_list:
        console.print("[red]No active accounts available![/red]")
        return

    # Shuffle for randomness
    random.shuffle(account_list)

    # Check if mobile rotation is enabled
    rotation_enabled = proxy_manager.is_rotation_enabled()

    # Display info
    console.print(f"[cyan]Posts to upvote: {len(post_urls)}[/cyan]")
    for i, url in enumerate(post_urls, 1):
        console.print(f"  {i}. {url[:80]}...")
    console.print(f"[cyan]Using {len(account_list)} account(s)[/cyan]")
    if rotation_enabled:
        console.print(f"[green]IP rotation: ENABLED[/green]")
        console.print(f"[dim]Delay between posts: {DELAY_BETWEEN_POSTS_MIN}-{DELAY_BETWEEN_POSTS_MAX}s[/dim]")
        console.print(f"[dim]No delay between accounts (IP rotation provides separation)[/dim]\n")
    else:
        console.print(f"[dim]Delay between posts: {DELAY_BETWEEN_POSTS_MIN}-{DELAY_BETWEEN_POSTS_MAX}s[/dim]\n")

    # Estimate time
    per_account_time = 5 + 6 + (len(post_urls) * 8) + ((len(post_urls) - 1) * 3) + 0.5  # rotation + browser + upvotes + delays + close
    total_time = len(account_list) * per_account_time
    console.print(f"[dim]Estimated time: {total_time / 60:.1f} minutes[/dim]\n")

    if dry_run:
        console.print("[yellow]DRY RUN - No actions will be performed[/yellow]\n")
        for i, acc in enumerate(account_list, 1):
            console.print(f"  {i}. {acc['username']}")
        return

    # Initialize results
    post_results = {url: {"success": 0, "failed": 0} for url in post_urls}
    total_success = 0
    total_failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        task = progress.add_task("Upvoting...", total=len(account_list))

        for i, account in enumerate(account_list):
            username = account["username"]
            account_id = account["id"]

            progress.update(task, description=f"[{i+1}/{len(account_list)}] {username}")

            # Handle IP rotation if enabled (once per account)
            if rotation_enabled:
                progress.update(task, description=f"[{i+1}/{len(account_list)}] Rotating IP...")
                success_rotate, old_ip, new_ip = proxy_manager.rotate_ip(verify=True)
                if success_rotate:
                    console.print(f"  [dim]IP: {old_ip} → {new_ip}[/dim]")
                else:
                    console.print(f"  [yellow]IP rotation may have failed[/yellow]")
                proxy = proxy_manager.get_mobile_proxy()
            else:
                proxy = account.get("proxy") or proxy_manager.format_proxy_for_provider(account_id)

            progress.update(task, description=f"[{i+1}/{len(account_list)}] {username}")

            # Start browser once for all posts
            browser = BrowserManager()
            try:
                browser.start(profile_path=str(account_id), proxy=proxy, headless=True)

                # Check login status once
                if not browser.is_logged_in():
                    console.print(f"  [red]✗[/red] {username}: Not logged in")
                    for url in post_urls:
                        post_results[url]["failed"] += 1
                        total_failed += 1
                        db.log_action(account_id, "upvote", url, "failed", "Not logged in")
                    progress.advance(task)
                    continue

                # Upvote all posts with this browser session
                account_success = 0
                account_failed = 0
                for j, post_url in enumerate(post_urls):
                    try:
                        if browser.upvote_post(post_url):
                            post_results[post_url]["success"] += 1
                            total_success += 1
                            account_success += 1
                            db.log_action(account_id, "upvote", post_url, "success")
                        else:
                            post_results[post_url]["failed"] += 1
                            total_failed += 1
                            account_failed += 1
                            db.log_action(account_id, "upvote", post_url, "failed", "Upvote action failed")
                    except Exception as e:
                        post_results[post_url]["failed"] += 1
                        total_failed += 1
                        account_failed += 1
                        db.log_action(account_id, "upvote", post_url, "failed", str(e))

                    # Small delay between posts (except last)
                    if j < len(post_urls) - 1:
                        time.sleep(random.uniform(DELAY_BETWEEN_POSTS_MIN, DELAY_BETWEEN_POSTS_MAX))

                # Print account result
                if account_failed == 0:
                    console.print(f"  [green]✓[/green] {username}: {account_success}/{len(post_urls)} posts")
                else:
                    console.print(f"  [yellow]~[/yellow] {username}: {account_success}/{len(post_urls)} posts ({account_failed} failed)")

                db.update_last_action(username)

            except Exception as e:
                console.print(f"  [red]✗[/red] {username}: {e}")
                for url in post_urls:
                    if post_results[url]["success"] + post_results[url]["failed"] < i + 1:
                        post_results[url]["failed"] += 1
                        total_failed += 1
                        db.log_action(account_id, "upvote", url, "failed", str(e))
            finally:
                browser.stop()

            progress.advance(task)

            # No delay between accounts - IP rotation provides separation

    # Summary
    console.print(f"\n[bold]Results:[/bold]")
    console.print(f"  [green]Total Success: {total_success}[/green]")
    console.print(f"  [red]Total Failed: {total_failed}[/red]")

    if len(post_urls) > 1:
        console.print(f"\n[bold]Per-post breakdown:[/bold]")
        for url in post_urls:
            s = post_results[url]["success"]
            f = post_results[url]["failed"]
            console.print(f"  {url[:60]}... [green]{s}[/green]/[red]{f}[/red]")


def upvote_with_account(account_id: int, username: str, post_url: str, proxy: str) -> tuple[bool, str]:
    """Perform upvote with a single account."""

    browser = BrowserManager()

    try:
        browser.start(profile_path=str(account_id), proxy=proxy, headless=True)

        # Check if logged in
        if not browser.is_logged_in():
            return False, "Not logged in"

        # Perform upvote
        if browser.upvote_post(post_url):
            return True, None
        else:
            return False, "Upvote action failed"

    except Exception as e:
        return False, str(e)
    finally:
        browser.stop()


@click.command("test-upvote")
@click.option("--username", "-u", required=True, help="Account to test with")
@click.option("--headless/--no-headless", default=False, help="Run headless")
def test_upvote(username: str, headless: bool):
    """Test upvote functionality with a single account (interactive)."""

    account = db.get_account(username)
    if not account:
        console.print(f"[red]Account '{username}' not found![/red]")
        return

    console.print(f"[cyan]Testing upvote with account: {username}[/cyan]")
    console.print("[dim]This will open a browser for you to manually test[/dim]\n")

    account_id = account["id"]
    proxy = account.get("proxy") or proxy_manager.format_proxy_for_provider(account_id)

    browser = BrowserManager()

    try:
        browser.start(profile_path=str(account_id), proxy=proxy, headless=headless)

        # Check login status
        if browser.is_logged_in():
            console.print("[green]✓ Logged in[/green]")
        else:
            console.print("[yellow]Not logged in - attempting login...[/yellow]")
            if browser.login(username, account["password"]):
                console.print("[green]✓ Login successful[/green]")
            else:
                console.print("[red]✗ Login failed[/red]")
                return

        # Interactive test
        console.print("\n[cyan]Browser is ready. Navigate to a post and test upvoting.[/cyan]")
        console.print("[dim]Press Enter when done to close the browser...[/dim]")
        input()

    finally:
        browser.stop()

    console.print("[green]Test complete[/green]")
