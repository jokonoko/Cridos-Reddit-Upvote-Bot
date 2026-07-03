# Base Dockerfile for Cridos Reddit Farm
# Used for both web and worker services with different commands

FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/app/browsers

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Playwright dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    # Additional utilities
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt requirements-web.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt -r requirements-web.txt

# Install Playwright browsers
RUN playwright install chromium

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/data /app/profiles /app/logs

# Expose port for web service
EXPOSE 8000

# Default command (overridden in docker-compose)
CMD ["python", "main.py", "--help"]
