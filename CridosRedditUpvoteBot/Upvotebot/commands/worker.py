import os
import sys
import time
import random
import signal
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from core.database import Database
from core.browser import BrowserManager
from core.proxy_manager import ProxyManager
from config import (
    WORKER_START_HOUR,
    WORKER_END_HOUR,
    WORKER_TIMEZONE,
    WORKER_SKIP_PROBABILITY,
    LOG_DIR,
)

console = Console()
db = Database()
proxy_manager = ProxyManager()

# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    global shutdown_requested
    console.print("\n[yellow]Shutdown requested, finishing current task...[/yellow]")
    shutdown_requested = True


@click.group("worker")
def worker():
    """Background worker for maintaining account activity."""
    pass


@worker.command("start")
@click.option("--foreground", "-f", is_flag=True, help="Run in foreground (don't daemonize)")
def worker_start(foreground: bool):
    """Start the background worker daemon."""

    if not foreground:
        console.print("[cyan]Starting worker in background...[/cyan]")
        console.print(f"[dim]Schedule: {WORKER_START_HOUR}:00 - {WORKER_END_HOUR}:00 {WORKER_TIMEZONE}[/dim]")
        console.print("[dim]Use 'python main.py worker status' to check status[/dim]")
        console.print("[dim]Use 'python main.py worker stop' to stop[/dim]")

        # Create PID file
        pid_file = LOG_DIR / "worker.pid"
        with open(pid_file, "w") as f:
            f.write(str(os.getpid()))

    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create scheduler
    scheduler = BackgroundScheduler(timezone=WORKER_TIMEZONE)

    # Schedule job to run at the start of the worker window
    # The job itself will check if it should run based on current hour
    scheduler.add_job(
        run_worker_cycle,
        CronTrigger(hour=WORKER_START_HOUR, minute=random.randint(0, 30)),
        id="worker_main",
        replace_existing=True,
    )

    scheduler.start()

    console.print(f"[green]Worker started. Next run scheduled.[/green]")

    if foreground:
        console.print("[dim]Running in foreground. Press Ctrl+C to stop.[/dim]")
        try:
            while not shutdown_requested:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            scheduler.shutdown()
            console.print("[yellow]Worker stopped.[/yellow]")
    else:
        # Keep the process running
        while not shutdown_requested:
            time.sleep(60)

        scheduler.shutdown()


@worker.command("stop")
def worker_stop():
    """Stop the background worker."""

    pid_file = LOG_DIR / "worker.pid"

    if not pid_file.exists():
        console.print("[yellow]No worker PID file found. Worker may not be running.[/yellow]")
        return

    try:
        with open(pid_file, "r") as f:
            pid = int(f.read().strip())

        # Send SIGTERM
        os.kill(pid, signal.SIGTERM)
        console.print(f"[green]Sent stop signal to worker (PID: {pid})[/green]")

        # Remove PID file
        pid_file.unlink()

    except ProcessLookupError:
        console.print("[yellow]Worker process not found. Cleaning up PID file.[/yellow]")
        pid_file.unlink()
    except Exception as e:
        console.print(f"[red]Error stopping worker: {e}[/red]")


@worker.command("status")
def worker_status():
    """Check worker status."""

    pid_file = LOG_DIR / "worker.pid"

    if not pid_file.exists():
        console.print("[yellow]Worker is not running (no PID file)[/yellow]")
        return

    try:
        with open(pid_file, "r") as f:
            pid = int(f.read().strip())

        # Check if process is running
        os.kill(pid, 0)  # Signal 0 checks if process exists
        console.print(f"[green]Worker is running (PID: {pid})[/green]")
        console.print(f"[dim]Schedule: {WORKER_START_HOUR}:00 - {WORKER_END_HOUR}:00 {WORKER_TIMEZONE}[/dim]")

        # Show recent worker activity
        accounts = db.get_all_accounts(status="active")
        recent_runs = sum(1 for a in accounts if a.get("last_worker_run"))
        console.print(f"[dim]Accounts with recent worker activity: {recent_runs}/{len(accounts)}[/dim]")

    except ProcessLookupError:
        console.print("[yellow]Worker PID file exists but process is not running[/yellow]")
        console.print("[dim]Run 'python main.py worker start' to start the worker[/dim]")
    except Exception as e:
        console.print(f"[red]Error checking status: {e}[/red]")


@worker.command("run-once")
@click.option("--accounts", "-n", default=None, type=int, help="Limit number of accounts")
def worker_run_once(accounts: int):
    """Run worker cycle once (manual trigger)."""

    console.print("[cyan]Running worker cycle manually...[/cyan]")
    run_worker_cycle(limit=accounts, force=True)


def run_worker_cycle(limit: int = None, force: bool = False):
    """Execute one full worker cycle - browse with each account."""

    global shutdown_requested

    # Check if we should skip this run (randomization)
    if not force and random.random() < WORKER_SKIP_PROBABILITY:
        console.print("[dim]Skipping this worker run (random skip)[/dim]")
        return

    # Check if within working hours
    current_hour = datetime.now().hour
    if not force and not (WORKER_START_HOUR <= current_hour < WORKER_END_HOUR):
        console.print(f"[dim]Outside worker hours ({WORKER_START_HOUR}:00 - {WORKER_END_HOUR}:00)[/dim]")
        return

    # Get active accounts
    accounts = db.get_active_accounts(limit=limit)

    if not accounts:
        console.print("[yellow]No active accounts for worker[/yellow]")
        return

    # Shuffle for randomness
    random.shuffle(accounts)

    console.print(f"[cyan]Worker cycle starting with {len(accounts)} accounts[/cyan]")

    success_count = 0
    fail_count = 0

    for i, account in enumerate(accounts):
        if shutdown_requested:
            console.print("[yellow]Shutdown requested, stopping worker cycle[/yellow]")
            break

        username = account["username"]
        account_id = account["id"]

        console.print(f"[dim][{i+1}/{len(accounts)}] Processing {username}...[/dim]")

        # Rotate IP before worker activity (if rotation enabled)
        if proxy_manager.is_rotation_enabled():
            console.print(f"[dim]{username}: Rotating IP...[/dim]")
            proxy_manager.rotate_ip(verify=False)
            time.sleep(2)
            proxy = proxy_manager.get_mobile_proxy()
        else:
            proxy = account.get("proxy") or proxy_manager.format_proxy_for_provider(account_id)

        try:
            success = browse_with_account(account_id, username, account["password"], proxy)

            if success:
                success_count += 1
                db.update_last_worker_run(username)
                db.log_action(account_id, "worker", None, "success")
                console.print(f"  [green]✓[/green] {username}")
            else:
                fail_count += 1
                db.log_action(account_id, "worker", None, "failed")
                console.print(f"  [red]✗[/red] {username}")

        except Exception as e:
            fail_count += 1
            console.print(f"  [red]✗[/red] {username}: {e}")
            db.log_action(account_id, "worker", None, "failed", str(e))

        # Delay between accounts (5-30 minutes to spread across worker window)
        if i < len(accounts) - 1 and not shutdown_requested:
            # Calculate delay to spread accounts across available time
            remaining_accounts = len(accounts) - i - 1
            remaining_hours = WORKER_END_HOUR - datetime.now().hour
            max_delay = min(30 * 60, (remaining_hours * 3600) / remaining_accounts) if remaining_accounts > 0 else 30 * 60

            delay = random.uniform(5 * 60, max_delay)  # 5 min to max_delay
            console.print(f"[dim]Waiting {delay/60:.1f} minutes before next account...[/dim]")
            time.sleep(delay)

    console.print(f"\n[bold]Worker cycle complete:[/bold] {success_count} success, {fail_count} failed")


def browse_with_account(account_id: int, username: str, password: str, proxy: str) -> bool:
    """Browse Reddit with a single account to simulate activity."""

    browser = BrowserManager()

    try:
        browser.start(profile_path=str(account_id), proxy=proxy, headless=True)

        # Check if logged in
        if not browser.is_logged_in(username):
            console.print(f"  [yellow]{username}: Not logged in, attempting login...[/yellow]")
            if not browser.login(username, password):
                return False

        # Random session duration (2-10 minutes)
        session_duration = random.randint(120, 600)

        # Browse homepage
        browser.browse_homepage(duration_seconds=session_duration)

        return True

    except Exception as e:
        console.print(f"  [red]{username}: Error - {e}[/red]")
        return False
    finally:
        browser.stop()
