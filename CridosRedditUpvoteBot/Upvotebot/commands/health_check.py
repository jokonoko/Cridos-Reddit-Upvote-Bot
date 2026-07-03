import time
import random

import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from core.database import Database
from core.browser import BrowserManager
from core.proxy_manager import ProxyManager
from config import MIN_ACTION_DELAY, MAX_ACTION_DELAY

console = Console()
db = Database()
proxy_manager = ProxyManager()


@click.command("check-health")
@click.option("--username", "-u", default=None, help="Check specific account (default: all)")
@click.option("--report", is_flag=True, help="Generate detailed report")
@click.option("--fix", is_flag=True, help="Attempt to fix issues (re-login)")
def check_health(username: str, report: bool, fix: bool):
    """Check health status of accounts (banned, suspended, shadowbanned)."""

    if username:
        accounts = [db.get_account(username)]
        if not accounts[0]:
            console.print(f"[red]Account '{username}' not found![/red]")
            return
    else:
        accounts = db.get_all_accounts()

    if not accounts:
        console.print("[yellow]No accounts to check[/yellow]")
        return

    console.print(f"[cyan]Checking health of {len(accounts)} account(s)...[/cyan]\n")

    results = {
        "active": [],
        "suspended": [],
        "shadowbanned": [],
        "restricted": [],
        "unknown": [],
        "login_required": [],
    }

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Checking accounts...", total=len(accounts))

        for account in accounts:
            acc_username = account["username"]
            progress.update(task, description=f"Checking {acc_username}...")

            status = check_single_account(account, fix=fix)
            results[status].append(acc_username)

            # Update database
            db.update_account_status(acc_username, status)

            progress.advance(task)

            # Delay between checks (avoid rate limiting)
            if len(accounts) > 1:
                delay = random.uniform(MIN_ACTION_DELAY / 2, MIN_ACTION_DELAY)
                time.sleep(delay)

    # Display results
    console.print("\n[bold]Health Check Results:[/bold]\n")

    table = Table()
    table.add_column("Status", style="bold")
    table.add_column("Count")
    table.add_column("Accounts")

    status_styles = {
        "active": ("green", "Active"),
        "suspended": ("red", "Suspended"),
        "shadowbanned": ("yellow", "Shadowbanned"),
        "restricted": ("yellow", "Restricted"),
        "unknown": ("dim", "Unknown"),
        "login_required": ("cyan", "Login Required"),
    }

    for status, (color, label) in status_styles.items():
        if results[status]:
            accounts_str = ", ".join(results[status][:5])
            if len(results[status]) > 5:
                accounts_str += f" (+{len(results[status]) - 5} more)"
            table.add_row(
                f"[{color}]{label}[/{color}]",
                str(len(results[status])),
                accounts_str,
            )

    console.print(table)

    # Summary
    total_healthy = len(results["active"])
    total_issues = len(results["suspended"]) + len(results["shadowbanned"]) + len(results["restricted"])
    console.print(f"\n[green]Healthy: {total_healthy}[/green] | [red]Issues: {total_issues}[/red] | [dim]Unknown: {len(results['unknown'])}[/dim]")

    if report:
        generate_health_report(results)


def check_single_account(account: dict, fix: bool = False) -> str:
    """Check health of a single account."""

    account_id = account["id"]
    username = account["username"]

    # Rotate IP before checking (if rotation enabled)
    if proxy_manager.is_rotation_enabled():
        console.print(f"[dim]{username}: Rotating IP...[/dim]")
        success, old_ip, new_ip = proxy_manager.rotate_ip(verify=False)
        if success:
            console.print(f"[dim]{username}: IP rotated[/dim]")
        time.sleep(2)  # Wait for rotation to stabilize

    proxy = account.get("proxy") or proxy_manager.format_proxy_for_provider(account_id)

    browser = BrowserManager()

    try:
        browser.start(profile_path=str(account_id), proxy=proxy, headless=True)

        # Check account status (which includes login check)
        # The new check_account_status method checks both login and account health in one go
        status = browser.check_account_status(username)

        # If login required and fix is enabled, attempt login
        if status == "login_required" and fix:
            console.print(f"[yellow]{username}: Not logged in, attempting login...[/yellow]")
            if browser.login(username, account["password"]):
                console.print(f"[green]{username}: Login successful, rechecking status...[/green]")
                # Recheck status after login
                status = browser.check_account_status(username)
            else:
                console.print(f"[red]{username}: Login failed[/red]")
                return "login_required"

        return status

    except Exception as e:
        console.print(f"[red]{username}: Error - {e}[/red]")
        return "unknown"
    finally:
        browser.stop()


def advanced_shadowban_check(browser: BrowserManager, username: str) -> str:
    """
    Advanced shadowban detection.
    Shadowbanned users can see their own content, but others can't.
    """
    try:
        # This is a simplified check - a full check would require
        # logging out and checking if posts are visible
        # For now, we check for common shadowban indicators

        # Go to user's profile
        browser.page.goto(f"https://www.reddit.com/user/{username}", timeout=30000)
        time.sleep(2)

        content = browser.page.content().lower()

        # Check for empty profile indicators
        if "hasn't posted anything" in content and "karma" not in content:
            return "shadowbanned"

        # Check for restricted messages
        if "you've been doing that a lot" in content or "try again" in content:
            return "restricted"

        return "active"

    except Exception:
        return "active"  # Assume active if check fails


def generate_health_report(results: dict):
    """Generate detailed health report."""

    console.print("\n[bold cyan]═══ Detailed Health Report ═══[/bold cyan]\n")

    # Recommendations
    console.print("[bold]Recommendations:[/bold]")

    if results["suspended"]:
        console.print(f"  [red]• {len(results['suspended'])} suspended accounts should be removed or replaced[/red]")

    if results["shadowbanned"]:
        console.print(f"  [yellow]• {len(results['shadowbanned'])} shadowbanned accounts - stop using for upvotes[/yellow]")
        console.print("    Consider using these only for worker activity to appear active")

    if results["login_required"]:
        console.print(f"  [cyan]• {len(results['login_required'])} accounts need manual login[/cyan]")
        console.print("    Run: python main.py add-account --username <name> to re-login")

    if results["restricted"]:
        console.print(f"  [yellow]• {len(results['restricted'])} restricted accounts - reduce activity[/yellow]")
        console.print("    Wait 24-48 hours before using these accounts")

    # Stats
    total = sum(len(v) for v in results.values())
    healthy = len(results["active"])

    if total > 0:
        health_rate = (healthy / total) * 100
        console.print(f"\n[bold]Health Rate: {health_rate:.1f}%[/bold]")

        if health_rate < 80:
            console.print("[yellow]Warning: Health rate below 80% - consider adjusting strategy[/yellow]")
