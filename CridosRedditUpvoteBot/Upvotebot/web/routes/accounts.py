"""
Account management routes.
"""

import csv
import io
from fastapi import APIRouter, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from core.database import Database
from web.tasks import enqueue_add_account, enqueue_health_check, enqueue_retry_login, enqueue_check_login_status, enqueue_enable_mature_content, get_job_status
from web.dependencies import verify_credentials, templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def list_accounts(
    request: Request,
    status: str = None,
    user: str = Depends(verify_credentials),
):
    """List all accounts."""
    db = Database()
    accounts = db.get_all_accounts(status=status)
    stats = db.get_stats()

    return templates.TemplateResponse(
        "accounts/list.html",
        {
            "request": request,
            "accounts": accounts,
            "stats": stats,
            "filter_status": status,
            "user": user,
        },
    )


@router.get("/add", response_class=HTMLResponse)
async def add_account_form(request: Request, user: str = Depends(verify_credentials)):
    """Show add account form."""
    return templates.TemplateResponse(
        "accounts/add.html",
        {"request": request, "user": user},
    )


@router.post("/add")
async def add_account(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    email: str = Form(None),
    proxy: str = Form(None),
    notes: str = Form(None),
    user: str = Depends(verify_credentials),
):
    """Add a new account."""
    db = Database()

    if db.account_exists(username):
        return templates.TemplateResponse(
            "accounts/add.html",
            {
                "request": request,
                "user": user,
                "error": f"Account '{username}' already exists",
            },
        )

    # Enqueue add account task
    job_id = enqueue_add_account(username, password, email or None, proxy or None, notes or None)

    return templates.TemplateResponse(
        "accounts/adding.html",
        {
            "request": request,
            "user": user,
            "username": username,
            "job_id": job_id,
        },
    )


@router.get("/bulk-import", response_class=HTMLResponse)
async def bulk_import_form(request: Request, user: str = Depends(verify_credentials)):
    """Show bulk import form."""
    return templates.TemplateResponse(
        "accounts/bulk_import.html",
        {"request": request, "user": user},
    )


@router.post("/bulk-import")
async def bulk_import(
    request: Request,
    csv_file: UploadFile = File(...),
    user: str = Depends(verify_credentials),
):
    """Bulk import accounts from CSV file."""
    db = Database()

    # Read and parse CSV
    content = await csv_file.read()
    try:
        text = content.decode('utf-8')
    except UnicodeDecodeError:
        text = content.decode('latin-1')

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)

    added = 0
    skipped = 0
    errors = []
    results = []

    for i, row in enumerate(rows):
        username = row.get('username', '').strip()
        password = row.get('password', '').strip()
        email = row.get('email', '').strip()
        proxy = row.get('proxy', '').strip()
        notes = row.get('notes', '').strip()

        if not username or not password:
            errors.append(f"Row {i+1}: missing username or password")
            results.append({"row": i+1, "username": "-", "status": "error", "message": "Missing username or password"})
            continue

        if db.account_exists(username):
            skipped += 1
            results.append({"row": i+1, "username": username, "status": "skipped", "message": "Already exists"})
            continue

        try:
            db.add_account(username, password, email or None, proxy or None, notes or None)
            added += 1
            results.append({"row": i+1, "username": username, "status": "added", "message": "Successfully added"})
        except Exception as e:
            errors.append(f"Error adding {username}: {str(e)}")
            results.append({"row": i+1, "username": username, "status": "error", "message": str(e)})

    return templates.TemplateResponse(
        "accounts/bulk_import_result.html",
        {
            "request": request,
            "user": user,
            "added": added,
            "skipped": skipped,
            "errors": errors,
            "results": results,
            "total": len(rows),
        },
    )


@router.get("/{username}", response_class=HTMLResponse)
async def account_detail(
    request: Request,
    username: str,
    user: str = Depends(verify_credentials),
):
    """Show account details."""
    db = Database()
    account = db.get_account(username)

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    logs = db.get_action_logs(account_id=account["id"], limit=20)

    return templates.TemplateResponse(
        "accounts/detail.html",
        {
            "request": request,
            "account": account,
            "logs": logs,
            "user": user,
        },
    )


@router.post("/{username}/delete")
async def delete_account(
    username: str,
    user: str = Depends(verify_credentials),
):
    """Delete an account."""
    import shutil
    from config import PROFILES_DIR

    db = Database()
    account = db.get_account(username)

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Remove browser profile
    profile_path = account.get("profile_path")
    if profile_path:
        profile_dir = Path(profile_path)
        if profile_dir.exists():
            shutil.rmtree(profile_dir, ignore_errors=True)

    # Remove from database
    db.remove_account(username)

    return RedirectResponse(url="/accounts", status_code=303)


@router.post("/bulk-delete")
async def bulk_delete(
    request: Request,
    account_ids: str = Form(None),  # Comma-separated IDs
    user: str = Depends(verify_credentials),
):
    """Delete multiple accounts."""
    import shutil

    if not account_ids:
        return RedirectResponse(url="/accounts", status_code=303)

    ids = [int(id.strip()) for id in account_ids.split(",") if id.strip()]

    if not ids:
        return RedirectResponse(url="/accounts", status_code=303)

    db = Database()
    deleted = 0

    for account_id in ids:
        # Get account by ID
        account = db.get_account_by_id(account_id)
        if account:
            # Remove browser profile
            profile_path = account.get("profile_path")
            if profile_path:
                profile_dir = Path(profile_path)
                if profile_dir.exists():
                    shutil.rmtree(profile_dir, ignore_errors=True)

            # Remove from database
            db.remove_account(account["username"])
            deleted += 1

    return RedirectResponse(url="/accounts", status_code=303)


@router.post("/check-health")
async def check_health(
    request: Request,
    account_ids: str = Form(None),  # Comma-separated IDs or "all"
    fix: bool = Form(False),
    user: str = Depends(verify_credentials),
):
    """Check health of accounts."""
    db = Database()

    if account_ids == "all" or not account_ids:
        accounts = db.get_all_accounts()
        ids = [a["id"] for a in accounts]
    else:
        ids = [int(id.strip()) for id in account_ids.split(",") if id.strip()]

    if not ids:
        return RedirectResponse(url="/accounts", status_code=303)

    job_id = enqueue_health_check(ids, fix=fix)

    return templates.TemplateResponse(
        "accounts/checking.html",
        {
            "request": request,
            "user": user,
            "job_id": job_id,
            "count": len(ids),
        },
    )


@router.post("/retry-login")
async def retry_login(
    request: Request,
    account_ids: str = Form(None),  # Comma-separated IDs or "all" or "not_logged_in"
    user: str = Depends(verify_credentials),
):
    """Retry login for accounts that are not logged in."""
    db = Database()

    if account_ids == "all":
        accounts = db.get_all_accounts()
        ids = [a["id"] for a in accounts]
    elif account_ids == "not_logged_in":
        # Get accounts that are not logged in (login_status != 'logged_in')
        all_accounts = db.get_all_accounts()
        ids = [a["id"] for a in all_accounts if a.get("login_status") != "logged_in"]
    elif account_ids:
        ids = [int(id.strip()) for id in account_ids.split(",") if id.strip()]
    else:
        return RedirectResponse(url="/accounts", status_code=303)

    if not ids:
        return RedirectResponse(url="/accounts", status_code=303)

    job_id = enqueue_retry_login(ids)

    return templates.TemplateResponse(
        "accounts/retry_login.html",
        {
            "request": request,
            "user": user,
            "job_id": job_id,
            "count": len(ids),
        },
    )


@router.post("/check-login-status")
async def check_login_status(
    request: Request,
    account_ids: str = Form(None),  # Comma-separated IDs or "all" or "active"
    user: str = Depends(verify_credentials),
):
    """Check login status of accounts."""
    db = Database()

    if account_ids == "all":
        accounts = db.get_all_accounts()
        ids = [a["id"] for a in accounts]
    elif account_ids == "active":
        # Get only active accounts
        accounts = db.get_active_accounts()
        ids = [a["id"] for a in accounts]
    elif account_ids:
        ids = [int(id.strip()) for id in account_ids.split(",") if id.strip()]
    else:
        return RedirectResponse(url="/accounts", status_code=303)

    if not ids:
        return RedirectResponse(url="/accounts", status_code=303)

    job_id = enqueue_check_login_status(ids)

    return templates.TemplateResponse(
        "accounts/checking_login.html",
        {
            "request": request,
            "user": user,
            "job_id": job_id,
            "count": len(ids),
        },
    )


@router.post("/enable-mature-content")
async def enable_mature_content(
    request: Request,
    account_ids: str = Form(None),  # Comma-separated IDs or "all" or "active"
    user: str = Depends(verify_credentials),
):
    """Enable mature content setting for accounts."""
    db = Database()

    if account_ids == "all":
        accounts = db.get_all_accounts()
        ids = [a["id"] for a in accounts]
    elif account_ids == "active":
        # Get only active accounts
        accounts = db.get_active_accounts()
        ids = [a["id"] for a in accounts]
    elif account_ids:
        ids = [int(id.strip()) for id in account_ids.split(",") if id.strip()]
    else:
        return RedirectResponse(url="/accounts", status_code=303)

    if not ids:
        return RedirectResponse(url="/accounts", status_code=303)

    job_id = enqueue_enable_mature_content(ids)

    return templates.TemplateResponse(
        "accounts/enabling_mature.html",
        {
            "request": request,
            "user": user,
            "job_id": job_id,
            "count": len(ids),
        },
    )


# HTMX partial endpoints

@router.get("/partials/table", response_class=HTMLResponse)
async def accounts_table_partial(
    request: Request,
    status: str = None,
    user: str = Depends(verify_credentials),
):
    """Partial: accounts table for HTMX updates."""
    db = Database()
    accounts = db.get_all_accounts(status=status)

    return templates.TemplateResponse(
        "accounts/partials/table.html",
        {"request": request, "accounts": accounts},
    )


@router.get("/partials/stats", response_class=HTMLResponse)
async def accounts_stats_partial(
    request: Request,
    user: str = Depends(verify_credentials),
):
    """Partial: account stats for HTMX updates."""
    db = Database()
    stats = db.get_stats()

    return templates.TemplateResponse(
        "accounts/partials/stats.html",
        {"request": request, "stats": stats},
    )
