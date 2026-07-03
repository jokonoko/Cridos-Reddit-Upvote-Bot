"""
Shared dependencies for the web app.
"""

import os
import secrets
from pathlib import Path
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates


# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "changeme-in-production")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
APP_VERSION = "1.0.9"

# Paths
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"

# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["APP_VERSION"] = APP_VERSION

# Security
security = HTTPBasic()


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify HTTP Basic auth credentials."""
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (credentials.username == "admin" and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
