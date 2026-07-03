"""
Worker management routes.
"""

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse

from core.database import Database
from web.tasks import (
    get_queue_stats,
    enqueue_worker_browse,
    enqueue_worker_batch,
    get_active_worker_batch_job,
    cancel_job,
    get_job_status,
)
from web.dependencies import verify_credentials, templates

router = APIRouter()

BATCH_SIZE = 60


@router.get("/", response_class=HTMLResponse)
async def worker_dashboard(request: Request, user: str = Depends(verify_credentials)):
    """Show worker dashboard."""
    db = Database()
    queue_stats = get_queue_stats()

    # Get all active accounts ordered by ID
    accounts = db.get_all_accounts_ordered()

    # Get batch stats
    batch_stats = db.get_worker_batch_stats()

    # Check if there's an active worker batch job
    active_job = get_active_worker_batch_job()

    # Get recent worker logs
    worker_logs = db.get_worker_logs(limit=50)

    # Get full job status with meta if there's an active job
    job_status = None
    meta = {}
    if active_job:
        job_status = get_job_status(active_job["id"])
        meta = job_status.get("meta", {})

    return templates.TemplateResponse(
        "worker/dashboard.html",
        {
            "request": request,
            "accounts": accounts,
            "queue_stats": queue_stats,
            "batch_stats": batch_stats,
            "active_job": active_job,
            "job": job_status,  # For progress_active.html template
            "meta": meta,       # For progress_active.html template
            "worker_logs": worker_logs,
            "batch_size": BATCH_SIZE,
            "user": user,
        },
    )


@router.post("/start-batch")
async def start_worker_batch(
    request: Request,
    user: str = Depends(verify_credentials),
):
    """Start processing the next batch of unprocessed accounts."""
    db = Database()

    # Check if there's already an active batch job
    active_job = get_active_worker_batch_job()
    if active_job:
        return templates.TemplateResponse(
            "worker/partials/batch_error.html",
            {
                "request": request,
                "error": "A worker batch is already running",
                "job_id": active_job["id"],
            },
        )

    # Get next batch of unprocessed accounts
    accounts = db.get_next_worker_batch(limit=BATCH_SIZE)

    if not accounts:
        # All accounts have been processed - check if we should auto-reset
        batch_stats = db.get_worker_batch_stats()
        return templates.TemplateResponse(
            "worker/partials/batch_complete_all.html",
            {
                "request": request,
                "batch_stats": batch_stats,
            },
        )

    # Enqueue the batch job
    account_ids = [a["id"] for a in accounts]
    job_id = enqueue_worker_batch(account_ids)

    return templates.TemplateResponse(
        "worker/partials/batch_started.html",
        {
            "request": request,
            "job_id": job_id,
            "account_count": len(accounts),
            "accounts": accounts,
        },
    )


@router.post("/stop")
async def stop_worker_batch(
    request: Request,
    user: str = Depends(verify_credentials),
):
    """Stop the currently running worker batch."""
    active_job = get_active_worker_batch_job()

    if not active_job:
        return templates.TemplateResponse(
            "worker/partials/stop_result.html",
            {
                "request": request,
                "success": False,
                "message": "No active worker batch to stop",
            },
        )

    # Send stop signal to the job
    result = cancel_job(active_job["id"])

    return templates.TemplateResponse(
        "worker/partials/stop_result.html",
        {
            "request": request,
            "success": result.get("success", False),
            "message": result.get("message") or result.get("error", "Unknown error"),
            "job_id": active_job["id"],
        },
    )


@router.post("/reset")
async def reset_worker_batch(
    request: Request,
    user: str = Depends(verify_credentials),
):
    """Reset all accounts' worker_batch_processed status."""
    db = Database()

    # Check if there's an active batch job - don't allow reset while running
    active_job = get_active_worker_batch_job()
    if active_job:
        return templates.TemplateResponse(
            "worker/partials/reset_result.html",
            {
                "request": request,
                "success": False,
                "message": "Cannot reset while a worker batch is running. Stop the batch first.",
            },
        )

    # Reset all accounts
    count = db.reset_worker_batch_processed()

    return templates.TemplateResponse(
        "worker/partials/reset_result.html",
        {
            "request": request,
            "success": True,
            "message": f"Reset {count} accounts. Ready to start from the beginning.",
            "count": count,
        },
    )


@router.post("/run-single")
async def run_worker_single(
    request: Request,
    account_id: int = Form(...),
    user: str = Depends(verify_credentials),
):
    """Run worker for a single account."""
    job_id = enqueue_worker_browse(account_id)

    db = Database()
    account = db.get_account_by_id(account_id)

    return templates.TemplateResponse(
        "worker/partials/job_queued.html",
        {
            "request": request,
            "job_id": job_id,
            "account": account,
        },
    )


# HTMX partial endpoints

@router.get("/partials/queue-stats", response_class=HTMLResponse)
async def queue_stats_partial(
    request: Request,
    user: str = Depends(verify_credentials),
):
    """Partial: queue stats for HTMX updates."""
    queue_stats = get_queue_stats()

    return templates.TemplateResponse(
        "worker/partials/queue_stats.html",
        {"request": request, "queue_stats": queue_stats},
    )


@router.get("/partials/recent-logs", response_class=HTMLResponse)
async def recent_logs_partial(
    request: Request,
    user: str = Depends(verify_credentials),
):
    """Partial: recent worker logs for HTMX updates."""
    db = Database()
    worker_logs = db.get_worker_logs(limit=50)

    return templates.TemplateResponse(
        "worker/partials/recent_logs.html",
        {"request": request, "logs": worker_logs},
    )


@router.get("/partials/batch-stats", response_class=HTMLResponse)
async def batch_stats_partial(
    request: Request,
    user: str = Depends(verify_credentials),
):
    """Partial: batch processing stats for HTMX updates."""
    db = Database()
    batch_stats = db.get_worker_batch_stats()

    return templates.TemplateResponse(
        "worker/partials/batch_stats.html",
        {"request": request, "batch_stats": batch_stats},
    )


@router.get("/partials/progress", response_class=HTMLResponse)
async def progress_partial(
    request: Request,
    user: str = Depends(verify_credentials),
):
    """Partial: current batch progress for HTMX updates."""
    active_job = get_active_worker_batch_job()

    if not active_job:
        return templates.TemplateResponse(
            "worker/partials/progress_idle.html",
            {"request": request},
        )

    # Get full job status with meta
    job_status = get_job_status(active_job["id"])

    return templates.TemplateResponse(
        "worker/partials/progress_active.html",
        {
            "request": request,
            "job": job_status,
            "meta": job_status.get("meta", {}),
        },
    )


@router.get("/partials/account-list", response_class=HTMLResponse)
async def account_list_partial(
    request: Request,
    user: str = Depends(verify_credentials),
):
    """Partial: ordered account list with checkboxes for HTMX updates."""
    db = Database()
    accounts = db.get_all_accounts_ordered()
    batch_stats = db.get_worker_batch_stats()

    return templates.TemplateResponse(
        "worker/partials/account_list.html",
        {
            "request": request,
            "accounts": accounts,
            "batch_stats": batch_stats,
        },
    )


# API endpoints for JSON responses

@router.get("/api/status", response_class=JSONResponse)
async def worker_api_status(user: str = Depends(verify_credentials)):
    """API: Get current worker status."""
    db = Database()
    active_job = get_active_worker_batch_job()
    batch_stats = db.get_worker_batch_stats()
    queue_stats = get_queue_stats()

    return {
        "active_job": active_job,
        "batch_stats": batch_stats,
        "queue_stats": queue_stats,
    }


@router.get("/api/progress/{job_id}", response_class=JSONResponse)
async def worker_api_progress(job_id: str, user: str = Depends(verify_credentials)):
    """API: Get progress for a specific job."""
    job_status = get_job_status(job_id)
    return job_status
