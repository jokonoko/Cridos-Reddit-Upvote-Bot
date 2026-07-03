#!/usr/bin/env python3
"""
Cridos Reddit Farm - Multi-account upvote automation tool

Usage:
    python main.py <command> [options]

Commands:
    add-account      Add a new Reddit account
    add-accounts     Bulk import accounts from CSV
    remove-account   Remove an account
    list-accounts    List all accounts
    account-info     Show detailed account info
    check-health     Check account health status
    upvote           Upvote a Reddit post
    test-upvote      Test upvote with single account
    worker           Background activity worker
    test-proxy       Test proxy connectivity
    init-db          Initialize/reset database
    stats            Show statistics
"""

import click
from rich.console import Console

from config import ensure_dirs, DATABASE_PATH
from core.database import Database
from core.proxy_manager import ProxyManager

from commands.account_manager import (
    add_account,
    add_accounts_bulk,
    remove_account,
    list_accounts,
    account_info,
)
from commands.health_check import check_health
from commands.upvote import upvote, test_upvote
from commands.worker import worker

console = Console()


@click.group()
@click.version_option(version="1.0.9", prog_name="redditfarm")
def cli():
    """Cridos Reddit Farm - Multi-account automation tool for Reddit upvoting."""
    ensure_dirs()


# Register commands
cli.add_command(add_account)
cli.add_command(add_accounts_bulk)
cli.add_command(remove_account)
cli.add_command(list_accounts)
cli.add_command(account_info)
cli.add_command(check_health)
cli.add_command(upvote)
cli.add_command(test_upvote)
cli.add_command(worker)


@cli.command("init-db")
@click.option("--force", "-f", is_flag=True, help="Force reinitialize (deletes existing data)")
def init_db(force: bool):
    """Initialize the database."""
    import os

    if DATABASE_PATH.exists():
        if force:
            os.remove(DATABASE_PATH)
            console.print("[yellow]Existing database deleted[/yellow]")
        else:
            console.print("[yellow]Database already exists. Use --force to reinitialize.[/yellow]")
            return

    db = Database()
    console.print(f"[green]Database initialized at {DATABASE_PATH}[/green]")


@cli.command("stats")
def show_stats():
    """Show statistics and summary."""
    db = Database()
    stats = db.get_stats()

    console.print("\n[bold cyan]═══ Cridos Reddit Farm Statistics ═══[/bold cyan]\n")

    console.print("[bold]Accounts:[/bold]")
    console.print(f"  Total: {stats['total_accounts']}")
    console.print(f"  Active: [green]{stats['active_accounts']}[/green]")
    console.print(f"  Banned/Suspended: [red]{stats['banned_accounts']}[/red]")
    console.print(f"  Shadowbanned: [yellow]{stats['shadowbanned_accounts']}[/yellow]")

    console.print("\n[bold]Activity (Last 7 Days):[/bold]")
    console.print(f"  Successful upvotes: [green]{stats['upvotes_last_week']}[/green]")
    console.print(f"  Failed upvotes: [red]{stats['failed_upvotes_last_week']}[/red]")

    if stats['upvotes_last_week'] + stats['failed_upvotes_last_week'] > 0:
        success_rate = stats['upvotes_last_week'] / (stats['upvotes_last_week'] + stats['failed_upvotes_last_week']) * 100
        console.print(f"  Success rate: {success_rate:.1f}%")


@cli.command("test-proxy")
@click.option("--proxy", "-p", default=None, help="Proxy URL to test (default: use configured proxy)")
def test_proxy(proxy: str):
    """Test proxy connectivity and get IP info."""
    pm = ProxyManager()

    if not proxy:
        proxy = pm.get_rotating_proxy()
        if not proxy:
            console.print("[yellow]No proxy configured. Testing direct connection.[/yellow]")

    console.print(f"[cyan]Testing proxy: {proxy or 'Direct connection'}[/cyan]")

    result = pm.test_proxy(proxy)

    if result["working"]:
        console.print(f"[green]✓ Proxy is working[/green]")
        console.print(f"  IP: {result['ip']}")
        console.print(f"  Country: {result['country']}")
    else:
        console.print(f"[red]✗ Proxy test failed[/red]")
        console.print(f"  Error: {result['error']}")


@cli.command("backup-profiles")
@click.option("--output", "-o", required=True, type=click.Path(), help="Backup destination directory")
def backup_profiles(output: str):
    """Backup all browser profiles and database."""
    import shutil
    from pathlib import Path
    from datetime import datetime
    from config import PROFILES_DIR

    output_path = Path(output)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = output_path / f"backup_{timestamp}"

    try:
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Backup database
        if DATABASE_PATH.exists():
            shutil.copy2(DATABASE_PATH, backup_dir / "farm.db")
            console.print(f"[green]✓[/green] Database backed up")

        # Backup profiles
        if PROFILES_DIR.exists():
            shutil.copytree(PROFILES_DIR, backup_dir / "profiles")
            console.print(f"[green]✓[/green] Profiles backed up")

        console.print(f"\n[green]Backup complete: {backup_dir}[/green]")

    except Exception as e:
        console.print(f"[red]Backup failed: {e}[/red]")


@cli.command("logs")
@click.option("--tail", "-n", default=20, type=int, help="Number of recent logs to show")
@click.option("--username", "-u", default=None, help="Filter by username")
@click.option("--action", "-a", default=None, help="Filter by action type (upvote, worker, health_check)")
def show_logs(tail: int, username: str, action: str):
    """View action logs."""
    db = Database()

    account_id = None
    if username:
        account = db.get_account(username)
        if not account:
            console.print(f"[red]Account '{username}' not found![/red]")
            return
        account_id = account["id"]

    logs = db.get_action_logs(account_id=account_id, action_type=action, limit=tail)

    if not logs:
        console.print("[yellow]No logs found[/yellow]")
        return

    console.print(f"\n[bold]Recent Logs ({len(logs)} entries):[/bold]\n")

    for log in logs:
        status_color = "green" if log["status"] == "success" else "red"
        target = log.get("target_url", "")[:50] if log.get("target_url") else ""

        # Get username for this log
        if not username:
            acc = db.get_account_by_id(log["account_id"])
            acc_name = acc["username"] if acc else f"ID:{log['account_id']}"
        else:
            acc_name = username

        console.print(
            f"[dim]{log['executed_at']}[/dim] "
            f"[{status_color}]{log['status']:7}[/{status_color}] "
            f"[cyan]{log['action_type']:12}[/cyan] "
            f"{acc_name} "
            f"[dim]{target}[/dim]"
        )

        if log.get("error_message"):
            console.print(f"  [red]Error: {log['error_message']}[/red]")


if __name__ == "__main__":
    cli()
