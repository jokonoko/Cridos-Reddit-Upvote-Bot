#!/usr/bin/env python3
"""
Test login script with improved error handling and diagnostics
"""
import sys
import time
from rich.console import Console
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from core.database import Database
from core.browser import BrowserManager
from core.proxy_manager import ProxyManager

console = Console()
db = Database()
proxy_manager = ProxyManager()


def test_login(username: str):
    """Test login with detailed diagnostics."""

    account = db.get_account(username)
    if not account:
        console.print(f"[red]Account '{username}' not found![/red]")
        return

    console.print(f"\n[bold cyan]Testing login for: {username}[/bold cyan]")
    console.print(f"Account ID: {account['id']}")
    console.print(f"Status: {account['status']}")
    console.print(f"Password: {account['password']}")

    account_id = account["id"]
    password = account["password"]
    proxy = account.get("proxy") or proxy_manager.format_proxy_for_provider(account_id)

    console.print(f"Proxy: {proxy or 'None'}")

    browser = BrowserManager()

    try:
        console.print("\n[cyan]Starting browser (non-headless for visibility)...[/cyan]")
        browser.start(profile_path=str(account_id), proxy=proxy, headless=False)

        console.print("[cyan]Checking if already logged in...[/cyan]")
        if browser.is_logged_in():
            console.print("[green]Already logged in![/green]")
            db.update_account_status(username, "active")
            return

        console.print("[yellow]Not logged in. Attempting login...[/yellow]")

        # Navigate to login page
        console.print(f"[dim]Navigating to login page...[/dim]")
        browser.page.goto("https://www.reddit.com/login", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # Take screenshot before login
        screenshot_path = f"login_test_{username}_before.png"
        browser.page.screenshot(path=screenshot_path)
        console.print(f"[dim]Screenshot saved: {screenshot_path}[/dim]")

        # Try to find username field
        console.print("[dim]Looking for username field...[/dim]")
        username_selectors = [
            '#login-username',
            'input[name="username"]',
            'input[id*="username"]',
            'input[autocomplete="username"]',
        ]

        username_field = None
        for selector in username_selectors:
            try:
                username_field = browser.page.wait_for_selector(selector, timeout=5000)
                if username_field:
                    console.print(f"[green]Found username field: {selector}[/green]")
                    break
            except PlaywrightTimeoutError:
                console.print(f"[dim]  × {selector} not found[/dim]")
                continue

        if not username_field:
            console.print("[red]ERROR: Could not find username field![/red]")
            screenshot_path = f"login_test_{username}_no_field.png"
            browser.page.screenshot(path=screenshot_path)
            console.print(f"Screenshot saved: {screenshot_path}")
            return

        # Type username
        console.print(f"[dim]Typing username...[/dim]")
        browser._human_type(username_field, username)
        time.sleep(1)

        # Find password field
        console.print("[dim]Looking for password field...[/dim]")
        password_selectors = [
            '#login-password',
            'input[name="password"]',
            'input[id*="password"]',
            'input[type="password"]',
        ]

        password_field = None
        for selector in password_selectors:
            try:
                password_field = browser.page.query_selector(selector)
                if password_field:
                    console.print(f"[green]Found password field: {selector}[/green]")
                    break
            except:
                continue

        if not password_field:
            console.print("[red]ERROR: Could not find password field![/red]")
            return

        # Type password
        console.print(f"[dim]Typing password...[/dim]")
        browser._human_type(password_field, password)
        time.sleep(1)

        # Take screenshot before submit
        screenshot_path = f"login_test_{username}_filled.png"
        browser.page.screenshot(path=screenshot_path)
        console.print(f"[dim]Screenshot saved: {screenshot_path}[/dim]")

        # Find and click login button
        console.print("[dim]Looking for login button...[/dim]")
        login_btn_selectors = [
            'button[type="submit"]',
            'button:has-text("Log In")',
            'button:has-text("Sign In")',
            'faceplate-tracker button',
            '.login button',
            'button[class*="login"]',
        ]

        login_btn = None
        for selector in login_btn_selectors:
            try:
                login_btn = browser.page.query_selector(selector)
                if login_btn and login_btn.is_visible():
                    console.print(f"[green]Found login button: {selector}[/green]")
                    break
            except:
                continue

        if not login_btn:
            console.print("[yellow]⚠ No login button found, pressing Enter instead[/yellow]")
            password_field.press("Enter")
        else:
            console.print("[dim]Clicking login button...[/dim]")
            browser._human_click(login_btn)

        # Wait for navigation/response
        console.print("[cyan]Waiting for login response...[/cyan]")
        time.sleep(8)

        # Take screenshot after login
        screenshot_path = f"login_test_{username}_after.png"
        browser.page.screenshot(path=screenshot_path)
        console.print(f"[dim]Screenshot saved: {screenshot_path}[/dim]")

        # Check page content for errors
        page_content = browser.page.content().lower()

        if "incorrect username or password" in page_content or "wrong password" in page_content:
            console.print("[red]ERROR: Incorrect credentials![/red]")
            return

        if "suspicious activity" in page_content or "verify" in page_content:
            console.print("[yellow]WARNING: Account requires verification (captcha/email)[/yellow]")
            console.print("[yellow]Browser will stay open - please verify manually[/yellow]")
            input("Press Enter after verification...")

        # Check if logged in
        console.print("[cyan]Verifying login status...[/cyan]")
        if browser.is_logged_in():
            console.print("[green]SUCCESS: Login successful![/green]")
            db.update_account_status(username, "active")
        else:
            console.print("[red]ERROR: Login failed - not logged in after attempt[/red]")
            console.print("[yellow]Check the browser window and screenshots for details[/yellow]")
            input("Press Enter to close browser...")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")

    finally:
        console.print("[dim]Closing browser...[/dim]")
        browser.stop()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        console.print("[yellow]Usage: python test_login.py <username>[/yellow]")
        console.print("\nAccounts needing login:")
        accounts = []
        for status in ['suspended', 'login_required']:
            accs = db.get_all_accounts(status=status)
            accounts.extend(accs)
        for acc in accounts:
            console.print(f"  • {acc['username']} ({acc['status']})")
        sys.exit(1)

    username = sys.argv[1]
    test_login(username)
