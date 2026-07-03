"""
Upvote management routes.
"""

import re
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from core.database import Database
from web.tasks import enqueue_upvote, get_job_status
from web.dependencies import verify_credentials, templates

router = APIRouter()


def validate_reddit_url(url: str) -> bool:
    """Validate that URL is a Reddit post URL."""
    pattern = r"https?://(www\.|old\.)?reddit\.com/r/\w+/comments/\w+"
    return bool(re.match(pattern, url))


@router.get("/", response_class=HTMLResponse)
async def upvote_form(request: Request, user: str = Depends(verify_credentials)):
    """Show upvote form."""
    db = Database()
    accounts = db.get_active_accounts()
    stats = db.get_stats()

    # Get recent upvote jobs from logs
    recent_logs = db.get_action_logs(action_type="upvote", limit=20)

    return templates.TemplateResponse(
        "upvotes/form.html",
        {
            "request": request,
            "accounts": accounts,
            "stats": stats,
            "recent_logs": recent_logs,
            "user": user,
        },
    )


@router.post("/execute")
async def execute_upvote(
    request: Request,
    post_urls: str = Form(...),  # Multiple URLs, one per line
    account_count: int = Form(...),  # Required number of accounts
    user: str = Depends(verify_credentials),
):
    """Execute upvote with randomized accounts on multiple posts."""
    db = Database()

    # Parse URLs (one per line, filter empty lines)
    urls = [url.strip() for url in post_urls.strip().split("\n") if url.strip()]

    # Validate all URLs
    invalid_urls = [url for url in urls if not validate_reddit_url(url)]
    if invalid_urls:
        accounts = db.get_active_accounts()
        stats = db.get_stats()
        return templates.TemplateResponse(
            "upvotes/form.html",
            {
                "request": request,
                "accounts": accounts,
                "stats": stats,
                "user": user,
                "error": f"Invalid Reddit URL(s): {', '.join(invalid_urls[:3])}{'...' if len(invalid_urls) > 3 else ''}. Expected format: https://reddit.com/r/subreddit/comments/id/title",
            },
        )

    if not urls:
        accounts = db.get_active_accounts()
        stats = db.get_stats()
        return templates.TemplateResponse(
            "upvotes/form.html",
            {
                "request": request,
                "accounts": accounts,
                "stats": stats,
                "user": user,
                "error": "No valid URLs provided",
            },
        )

    # Validate account count
    available_accounts = db.count_accounts(status="active")
    if account_count > available_accounts:
        accounts = db.get_active_accounts()
        stats = db.get_stats()
        return templates.TemplateResponse(
            "upvotes/form.html",
            {
                "request": request,
                "accounts": accounts,
                "stats": stats,
                "user": user,
                "error": f"Requested {account_count} accounts but only {available_accounts} active accounts available",
            },
        )

    if account_count < 1:
        accounts = db.get_active_accounts()
        stats = db.get_stats()
        return templates.TemplateResponse(
            "upvotes/form.html",
            {
                "request": request,
                "accounts": accounts,
                "stats": stats,
                "user": user,
                "error": "Account count must be at least 1",
            },
        )

    # Enqueue upvote task
    job_id = enqueue_upvote(urls, account_count)

    return templates.TemplateResponse(
        "upvotes/progress.html",
        {
            "request": request,
            "user": user,
            "job_id": job_id,
            "post_urls": urls,
            "post_count": len(urls),
            "account_count": account_count,
        },
    )


@router.get("/job/{job_id}", response_class=HTMLResponse)
async def job_status_page(
    request: Request,
    job_id: str,
    user: str = Depends(verify_credentials),
):
    """Show job status page."""
    status = get_job_status(job_id)

    return templates.TemplateResponse(
        "upvotes/job_status.html",
        {
            "request": request,
            "user": user,
            "job": status,
        },
    )


# HTMX partial endpoints

@router.get("/partials/job/{job_id}", response_class=HTMLResponse)
async def job_status_partial(
    request: Request,
    job_id: str,
    user: str = Depends(verify_credentials),
):
    """Partial: job status for HTMX polling."""
    status = get_job_status(job_id)

    return templates.TemplateResponse(
        "upvotes/partials/job_status.html",
        {"request": request, "job": status},
    )


@router.get("/partials/recent", response_class=HTMLResponse)
async def recent_upvotes_partial(
    request: Request,
    user: str = Depends(verify_credentials),
):
    """Partial: recent upvotes for HTMX updates."""
    db = Database()
    recent_logs = db.get_action_logs(action_type="upvote", limit=20)

    return templates.TemplateResponse(
        "upvotes/partials/recent.html",
        {"request": request, "logs": recent_logs},
    )
