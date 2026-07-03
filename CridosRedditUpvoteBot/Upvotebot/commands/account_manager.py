import csv
import shutil
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm

from core.database import Database
from core.browser import BrowserManager
from core.proxy_manager import ProxyManager
from config import PROFILES_DIR

console = Console()
db = Database()
proxy_manager = ProxyManager()


@click.command("add-account")
@click.option("--username", "-u", required=True, help="Reddit username")
@click.option("--password", "-p", required=True, help="Reddit password")
@click.option("--email", "-e", default=None, help="Recovery email (optional)")
@click.option("--proxy", default=None, help="Custom proxy URL (optional)")
@click.option("--notes", default=None, help="Notes about this account")
@click.option("--skip-login", is_flag=True, help="Skip initial login verification")
def add_account(username: str, password: str, email: str, proxy: str, notes: str, skip_login: bool):
    """Add a new Reddit account to the database."""

    # Check if account already exists
    if db.account_exists(username):
        console.print(f"[red]Account '{username}' already exists![/red]")
        return

    console.print(f"[cyan]Adding account: {username}[/cyan]")

    # Add to database first to get ID
    account_id = db.add_account(
        username=username,
        password=password,
        email=email,
        proxy=proxy,
        notes=notes,
    )

    # Set profile path
    profile_path = str(PROFILES_DIR / str(account_id))
    db.set_profile_path(username, profile_path)

    if skip_login:
        console.print(f"[yellow]Skipped login verification[/yellow]")
        console.print(f"[green]Account '{username}' added successfully (ID: {account_id})[/green]")
        return

    # Perform initial login to create session
    console.print("[cyan]Performing initial login...[/cyan]")

    # Rotate IP before adding account (if rotation enabled)
    if proxy_manager.is_rotation_enabled():
        console.print("[dim]Rotating IP...[/dim]")
        proxy_manager.rotate_ip(verify=False)
        import time
        time.sleep(2)
        account_proxy = proxy_manager.get_mobile_proxy()
    else:
        account_proxy = proxy or proxy_manager.format_proxy_for_provider(account_id)

    browser = BrowserManager()
    try:
        browser.start(profile_path=str(account_id), proxy=account_proxy, headless=False)

        # Check if already logged in (from previous session)
        if browser.is_logged_in(username):
            console.print("[green]Already logged in from previous session![/green]")
        else:
            # Perform login
            if browser.login(username, password):
                console.print("[green]Login successful![/green]")
            else:
                console.print("[red]Login failed! Account added but may need manual login.[/red]")
                db.update_account_status(username, "unknown")

    except Exception as e:
        console.print(f"[red]Error during login: {e}[/red]")
        db.update_account_status(username, "unknown")
    finally:
        browser.stop()

    console.print(f"[green]Account '{username}' added successfully (ID: {account_id})[/green]")


@click.command("add-accounts")
@click.option("--file", "-f", "file_path", required=True, type=click.Path(exists=True), help="CSV file with accounts")
@click.option("--skip-login", is_flag=True, help="Skip initial login verification")
def add_accounts_bulk(file_path: str, skip_login: bool):
    """Bulk import accounts from CSV file.

    CSV format: username,password,email(optional),proxy(optional),notes(optional)
    """
    added = 0
    failed = 0

    with open(file_path, "r") as f:
        reader = csv.DictReader(f)

        for row in reader:
            username = row.get("username", "").strip()
            password = row.get("password", "").strip()

            if not username or not password:
                console.print(f"[yellow]Skipping row with missing username/password[/yellow]")
                failed += 1
                continue

            if db.account_exists(username):
                console.print(f"[yellow]Account '{username}' already exists, skipping[/yellow]")
                failed += 1
                continue

            try:
                account_id = db.add_account(
                    username=username,
                    password=password,
                    email=row.get("email", "").strip() or None,
                    proxy=row.get("proxy", "").strip() or None,
                    notes=row.get("notes", "").strip() or None,
                )
                profile_path = str(PROFILES_DIR / str(account_id))
                db.set_profile_path(username, profile_path)
                console.print(f"[green]Added: {username}[/green]")
                added += 1
            except Exception as e:
                console.print(f"[red]Failed to add {username}: {e}[/red]")
                failed += 1

    console.print(f"\n[cyan]Import complete: {added} added, {failed} failed[/cyan]")

    if not skip_login:
        console.print("[yellow]Run 'check-health' to verify accounts and perform initial logins[/yellow]")


@click.command("remove-account")
@click.option("--username", "-u", required=True, help="Reddit username to remove")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
def remove_account(username: str, force: bool):
    """Remove an account and its browser profile."""

    account = db.get_account(username)
    if not account:
        console.print(f"[red]Account '{username}' not found![/red]")
        return

    if not force:
        if not Confirm.ask(f"Remove account '{username}' and all its data?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    # Remove browser profile
    profile_path = account.get("profile_path")
    if profile_path:
        profile_dir = Path(profile_path)
        if profile_dir.exists():
            try:
                shutil.rmtree(profile_dir)
                console.print(f"[dim]Removed profile directory: {profile_path}[/dim]")
            except Exception as e:
                console.print(f"[yellow]Could not remove profile: {e}[/yellow]")

    # Remove from database
    if db.remove_account(username):
        console.print(f"[green]Account '{username}' removed successfully[/green]")
    else:
        console.print(f"[red]Failed to remove account from database[/red]")


@click.command("list-accounts")
@click.option("--status", "-s", default=None, help="Filter by status (active, suspended, shadowbanned, unknown)")
@click.option("--sort", "sort_by", default="created", type=click.Choice(["created", "last-action", "username"]))
def list_accounts(status: str, sort_by: str):
    """List all accounts with their status."""

    accounts = db.get_all_accounts(status=status)

    if not accounts:
        console.print("[yellow]No accounts found[/yellow]")
        return

    table = Table(title="Reddit Accounts")
    table.add_column("ID", style="dim")
    table.add_column("Username", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Last Action")
    table.add_column("Last Health Check")
    table.add_column("Proxy", style="dim")

    # Sort
    if sort_by == "last-action":
        accounts.sort(key=lambda x: x.get("last_action") or "", reverse=True)
    elif sort_by == "username":
        accounts.sort(key=lambda x: x.get("username", ""))

    for acc in accounts:
        status_color = {
            "active": "green",
            "suspended": "red",
            "shadowbanned": "yellow",
            "restricted": "yellow",
            "unknown": "dim",
        }.get(acc["status"], "white")

        proxy_display = "Yes" if acc.get("proxy") else "Default"

        table.add_row(
            str(acc["id"]),
            acc["username"],
            f"[{status_color}]{acc['status']}[/{status_color}]",
            acc.get("last_action", "Never") or "Never",
            acc.get("last_health_check", "Never") or "Never",
            proxy_display,
        )

    console.print(table)

    # Summary
    stats = db.get_stats()
    console.print(f"\n[dim]Total: {stats['total_accounts']} | Active: {stats['active_accounts']} | Banned: {stats['banned_accounts']} | Shadowbanned: {stats['shadowbanned_accounts']}[/dim]")


@click.command("account-info")
@click.option("--username", "-u", required=True, help="Reddit username")
def account_info(username: str):
    """Show detailed info for an account."""

    account = db.get_account(username)
    if not account:
        console.print(f"[red]Account '{username}' not found![/red]")
        return

    console.print(f"\n[bold cyan]Account: {account['username']}[/bold cyan]")
    console.print(f"  ID: {account['id']}")
    console.print(f"  Status: {account['status']}")
    console.print(f"  Email: {account.get('email') or 'Not set'}")
    console.print(f"  Proxy: {account.get('proxy') or 'Using default'}")
    console.print(f"  Profile Path: {account.get('profile_path') or 'Not set'}")
    console.print(f"  Created: {account.get('created_at')}")
    console.print(f"  Last Action: {account.get('last_action') or 'Never'}")
    console.print(f"  Last Health Check: {account.get('last_health_check') or 'Never'}")
    console.print(f"  Last Worker Run: {account.get('last_worker_run') or 'Never'}")
    console.print(f"  Notes: {account.get('notes') or 'None'}")

    # Recent actions
    logs = db.get_action_logs(account_id=account["id"], limit=5)
    if logs:
        console.print(f"\n[bold]Recent Actions:[/bold]")
        for log in logs:
            status_color = "green" if log["status"] == "success" else "red"
            console.print(f"  [{status_color}]{log['action_type']}[/{status_color}] - {log['executed_at']} - {log.get('target_url', '')[:50]}")
