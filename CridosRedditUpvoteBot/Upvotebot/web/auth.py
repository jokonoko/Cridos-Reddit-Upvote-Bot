"""
Authentication utilities for the web app.
"""

import os
import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials


# Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "changeme-in-production")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

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
