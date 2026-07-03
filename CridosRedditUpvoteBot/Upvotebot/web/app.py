"""
Cridos Reddit Farm - Web Dashboard
FastAPI application with HTMX frontend
"""

import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse

from web.routes import accounts, upvotes, worker, api
from web.tasks import init_redis
from web.dependencies import verify_credentials, templates, APP_VERSION
from core.database import Database

# Paths
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    init_redis()
    # Ensure database is initialized
    db = Database()
    yield
    # Shutdown
    pass


app = FastAPI(
    title="Cridos Reddit Farm",
    description="Multi-account Reddit automation dashboard",
    version=APP_VERSION,
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Include routers
app.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
app.include_router(upvotes.router, prefix="/upvotes", tags=["upvotes"])
app.include_router(worker.router, prefix="/worker", tags=["worker"])
app.include_router(api.router, prefix="/api", tags=["api"])


@app.get("/health")
async def health_check():
    """Health check endpoint for Docker."""
    return {"status": "healthy"}


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, user: str = Depends(verify_credentials)):
    """Main dashboard page."""
    db = Database()
    stats = db.get_stats()
    accounts = db.get_all_accounts()
    recent_logs = db.get_action_logs(limit=10)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "stats": stats,
            "accounts": accounts,
            "recent_logs": recent_logs,
            "user": user,
        },
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page (redirect to dashboard with auth)."""
    return templates.TemplateResponse("login.html", {"request": request})
