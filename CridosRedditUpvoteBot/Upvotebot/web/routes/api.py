"""
JSON API routes for programmatic access.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from core.database import Database
from web.tasks import (
    enqueue_upvote,
    enqueue_health_check,
    enqueue_add_account,
    enqueue_worker_browse,
    get_job_status,
    get_queue_stats,
    cancel_job,
)
from web.dependencies import verify_credentials

router = APIRouter()


# Request/Response models

class AddAccountRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    proxy: Optional[str] = None
    notes: Optional[str] = None


class UpvoteRequest(BaseModel):
    post_urls: list[str]  # List of Reddit post URLs
    account_count: int  # Number of accounts to use per post


class HealthCheckRequest(BaseModel):
    account_ids: Optional[list[int]] = None
    fix: bool = False


class WorkerRunRequest(BaseModel):
    account_ids: Optional[list[int]] = None
    limit: Optional[int] = None


# Endpoints

@router.get("/stats")
async def get_stats(user: str = Depends(verify_credentials)):
    """Get overall statistics."""
    db = Database()
    stats = db.get_stats()
    queue = get_queue_stats()

    return {
        "accounts": stats,
        "queues": queue,
    }


@router.get("/accounts")
async def list_accounts(
    status: str = None,
    user: str = Depends(verify_credentials),
):
    """List all accounts."""
    db = Database()
    accounts = db.get_all_accounts(status=status)

    # Remove sensitive data
    for acc in accounts:
        acc.pop("password", None)

    return {"accounts": accounts}


@router.get("/accounts/{username}")
async def get_account(username: str, user: str = Depends(verify_credentials)):
    """Get account details."""
    db = Database()
    account = db.get_account(username)

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Remove sensitive data
    account.pop("password", None)

    logs = db.get_action_logs(account_id=account["id"], limit=10)

    return {"account": account, "recent_logs": logs}


@router.post("/accounts")
async def add_account(
    request: AddAccountRequest,
    user: str = Depends(verify_credentials),
):
    """Add a new account."""
    db = Database()

    if db.account_exists(request.username):
        raise HTTPException(status_code=400, detail="Account already exists")

    job_id = enqueue_add_account(
        request.username,
        request.password,
        request.email,
        request.proxy,
        request.notes,
    )

    return {"job_id": job_id, "message": "Account creation queued"}


@router.delete("/accounts/{username}")
async def delete_account(username: str, user: str = Depends(verify_credentials)):
    """Delete an account."""
    import shutil
    from pathlib import Path

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

    db.remove_account(username)

    return {"message": f"Account '{username}' deleted"}


@router.post("/upvote")
async def create_upvote(
    request: UpvoteRequest,
    user: str = Depends(verify_credentials),
):
    """Queue an upvote job for multiple posts with randomized accounts.

    Posts are processed sequentially. For each post, accounts are randomly shuffled.
    """
    import re

    # Validate all URLs
    pattern = r"https?://(www\.|old\.)?reddit\.com/r/\w+/comments/\w+"
    invalid_urls = [url for url in request.post_urls if not re.match(pattern, url)]
    if invalid_urls:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid Reddit URL(s): {', '.join(invalid_urls[:3])}{'...' if len(invalid_urls) > 3 else ''}"
        )

    if not request.post_urls:
        raise HTTPException(status_code=400, detail="No URLs provided")

    db = Database()

    # Validate account count
    available_accounts = db.count_accounts(status="active")
    if request.account_count > available_accounts:
        raise HTTPException(
            status_code=400,
            detail=f"Requested {request.account_count} accounts but only {available_accounts} active accounts available"
        )

    if request.account_count < 1:
        raise HTTPException(status_code=400, detail="Account count must be at least 1")

    job_id = enqueue_upvote(request.post_urls, request.account_count)

    return {
        "job_id": job_id,
        "post_urls": request.post_urls,
        "post_count": len(request.post_urls),
        "account_count": request.account_count,
    }


@router.post("/health-check")
async def create_health_check(
    request: HealthCheckRequest,
    user: str = Depends(verify_credentials),
):
    """Queue a health check job."""
    db = Database()

    if request.account_ids:
        ids = request.account_ids
    else:
        accounts = db.get_all_accounts()
        ids = [a["id"] for a in accounts]

    if not ids:
        raise HTTPException(status_code=400, detail="No accounts to check")

    job_id = enqueue_health_check(ids, request.fix)

    return {"job_id": job_id, "account_count": len(ids)}


@router.post("/worker/run")
async def run_worker(
    request: WorkerRunRequest,
    user: str = Depends(verify_credentials),
):
    """Queue worker browse jobs."""
    db = Database()

    if request.account_ids:
        ids = request.account_ids
    else:
        accounts = db.get_active_accounts(limit=request.limit)
        ids = [a["id"] for a in accounts]

    if not ids:
        raise HTTPException(status_code=400, detail="No accounts available")

    job_ids = []
    for account_id in ids:
        job_id = enqueue_worker_browse(account_id)
        job_ids.append(job_id)

    return {"job_ids": job_ids, "count": len(ids)}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, user: str = Depends(verify_credentials)):
    """Get job status."""
    status = get_job_status(job_id)
    return status


@router.post("/jobs/{job_id}/cancel")
async def cancel_job_endpoint(job_id: str, user: str = Depends(verify_credentials)):
    """Cancel a job."""
    result = cancel_job(job_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to cancel job"))
    return result


@router.get("/logs")
async def get_logs(
    account_id: int = None,
    action_type: str = None,
    limit: int = 50,
    user: str = Depends(verify_credentials),
):
    """Get action logs."""
    db = Database()
    logs = db.get_action_logs(account_id=account_id, action_type=action_type, limit=limit)
    return {"logs": logs}
