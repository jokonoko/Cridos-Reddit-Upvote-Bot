# Cridos Reddit Farm - Docker Deployment Guide

Deploy Cridos Reddit Farm with Docker for 24/7 operation from anywhere.

---

## Architecture

```
                    ┌─────────────────┐
                    │   Your Browser  │
                    └────────┬────────┘
                             │ :8000
                    ┌────────▼────────┐
                    │    Web (API +   │
                    │    Dashboard)   │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼────────┐     │     ┌────────▼────────┐
     │     Redis       │◄────┴────►│   Scheduler     │
     │  (Task Queue)   │           │ (Cron Jobs)     │
     └────────┬────────┘           └─────────────────┘
              │
     ┌────────▼────────┐
     │     Worker      │
     │ (Browser Tasks) │
     └─────────────────┘
              │
     ┌────────▼────────┐
     │    Volumes      │
     │ (Data, Profiles)│
     └─────────────────┘
```

**Services:**
- **web**: FastAPI dashboard + API (port 8000)
- **worker**: RQ worker for browser automation tasks
- **scheduler**: APScheduler for periodic account aging
- **redis**: Task queue backend

---

## Quick Start

### 1. Prerequisites

- Docker & Docker Compose installed
- VPS with at least 2GB RAM
- Residential proxy credentials (recommended)

### 2. Setup

```bash
# Clone the repository
git clone <your-repo> redditfarm
cd redditfarm

# Copy environment file
cp .env.docker .env

# Edit configuration
nano .env
```

### 3. Configure `.env`

```env
# Required - Change these!
SECRET_KEY=your-random-secret-key-here
ADMIN_PASSWORD=your-secure-password

# Proxy (Required for production)
PROXY_PROVIDER=iproyal
PROXY_HOST=geo.iproyal.com
PROXY_PORT=12321
PROXY_USERNAME=your_username
PROXY_PASSWORD=your_password

# Optional
WEB_PORT=8000
WORKER_START_HOUR=0
WORKER_END_HOUR=5
```

### 4. Build & Run

```bash
# Build images
docker compose build

# Start all services
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f
```

### 5. Access Dashboard

Open `http://your-server-ip:8000` in your browser.

Login with:
- Username: `admin`
- Password: (your ADMIN_PASSWORD from .env)

---

## Commands

### Service Management

```bash
# Start all services
docker compose up -d

# Stop all services
docker compose down

# Restart a specific service
docker compose restart web

# View logs
docker compose logs -f web
docker compose logs -f worker

# Scale workers (for more parallel processing)
docker compose up -d --scale worker=2
```

### Database & Data

```bash
# Backup data
docker compose exec web python main.py backup-profiles -o /app/backups

# Access database directly
docker compose exec web sqlite3 /app/data/farm.db

# Initialize fresh database
docker compose exec web python main.py init-db --force
```

### CLI Access

```bash
# Run CLI commands inside container
docker compose exec web python main.py stats
docker compose exec web python main.py list-accounts
docker compose exec web python main.py check-health
```

---

## API Reference

The API is available at `http://your-server:8000/api/`

### Authentication

All API requests require HTTP Basic Auth:
```bash
curl -u admin:your-password http://localhost:8000/api/stats
```

### Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/stats` | Get overall statistics |
| GET | `/api/accounts` | List all accounts |
| GET | `/api/accounts/{username}` | Get account details |
| POST | `/api/accounts` | Add new account |
| DELETE | `/api/accounts/{username}` | Delete account |
| POST | `/api/upvote` | Queue upvote job |
| POST | `/api/health-check` | Queue health check |
| POST | `/api/worker/run` | Queue worker jobs |
| GET | `/api/jobs/{job_id}` | Get job status |
| GET | `/api/logs` | Get action logs |

### Example: Upvote via API (Multi-Post)

Upvote multiple posts with randomized accounts. Posts are processed sequentially, and accounts are **randomly shuffled** for each post.

```bash
curl -X POST http://localhost:8000/api/upvote \
  -u admin:your-password \
  -H "Content-Type: application/json" \
  -d '{
    "post_urls": [
      "https://reddit.com/r/test/comments/abc123/post1",
      "https://reddit.com/r/another/comments/def456/post2",
      "https://reddit.com/r/third/comments/ghi789/post3"
    ],
    "account_count": 5,
    "delay_min": 30,
    "delay_max": 120
  }'
```

**Request Body:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `post_urls` | array | Yes | List of Reddit post URLs to upvote |
| `account_count` | int | Yes | Number of accounts to use **per post** |
| `delay_min` | int | No | Min delay between accounts (default: 30s) |
| `delay_max` | int | No | Max delay between accounts (default: 180s) |

**Response:**
```json
{
  "job_id": "abc123...",
  "post_urls": ["..."],
  "post_count": 3,
  "account_count": 5
}
```

### Example: Add Account via API

```bash
curl -X POST http://localhost:8000/api/accounts \
  -u admin:your-password \
  -H "Content-Type: application/json" \
  -d '{
    "username": "myreddituser",
    "password": "mypassword",
    "notes": "New account"
  }'
```

---

## Production Deployment

### VPS Setup (Ubuntu)

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt install docker-compose-plugin

# Clone and setup
git clone <your-repo> ~/redditfarm
cd ~/redditfarm
cp .env.docker .env
nano .env  # Configure your settings

# Start
docker compose up -d
```

### Enable HTTPS with Caddy

Create `Caddyfile`:
```
your-domain.com {
    reverse_proxy localhost:8000
}
```

Run Caddy:
```bash
docker run -d \
  --name caddy \
  --network host \
  -v $PWD/Caddyfile:/etc/caddy/Caddyfile \
  -v caddy_data:/data \
  caddy:latest
```

### Firewall Setup

```bash
# Allow SSH and HTTP/HTTPS
sudo ufw allow 22
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable

# Or allow direct access to dashboard (not recommended)
sudo ufw allow 8000
```

---

## Monitoring

### Health Check

```bash
# Check if web is healthy
curl http://localhost:8000/health

# Check all containers
docker compose ps
```

### Resource Usage

```bash
# View resource usage
docker stats

# Typical usage per container:
# - web: ~100MB RAM
# - worker: ~200-500MB RAM (during browser tasks)
# - redis: ~50MB RAM
# - scheduler: ~50MB RAM
```

### Logs

```bash
# All logs
docker compose logs -f

# Specific service
docker compose logs -f worker

# Last 100 lines
docker compose logs --tail 100 web
```

---

## Troubleshooting

### Container won't start

```bash
# Check logs for errors
docker compose logs web

# Common issues:
# - Port 8000 already in use: change WEB_PORT in .env
# - Missing .env file: copy from .env.docker
```

### Browser tasks failing

```bash
# Check worker logs
docker compose logs worker

# Common issues:
# - Proxy not configured correctly
# - Proxy bandwidth exhausted
# - Reddit blocking datacenter IPs
```

### Database issues

```bash
# Check database file exists
docker compose exec web ls -la /app/data/

# Reinitialize if corrupted
docker compose exec web python main.py init-db --force
```

### Out of memory

```bash
# Check memory usage
docker stats

# Solutions:
# - Upgrade VPS RAM
# - Reduce concurrent workers
# - Increase swap space
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

---

## Backup & Restore

### Backup

```bash
# Stop services (optional, for consistency)
docker compose stop

# Backup volumes
docker run --rm \
  -v redditfarm_app_data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/data-backup.tar.gz /data

docker run --rm \
  -v redditfarm_browser_profiles:/profiles \
  -v $(pwd):/backup \
  alpine tar czf /backup/profiles-backup.tar.gz /profiles

# Restart
docker compose start
```

### Restore

```bash
# Stop services
docker compose down

# Restore volumes
docker run --rm \
  -v redditfarm_app_data:/data \
  -v $(pwd):/backup \
  alpine tar xzf /backup/data-backup.tar.gz -C /

docker run --rm \
  -v redditfarm_browser_profiles:/profiles \
  -v $(pwd):/backup \
  alpine tar xzf /backup/profiles-backup.tar.gz -C /

# Start
docker compose up -d
```

---

## Updating

```bash
# Pull latest code
git pull

# Rebuild and restart
docker compose down
docker compose build
docker compose up -d
```

---

## Resource Requirements

| Accounts | RAM | CPU | Storage |
|----------|-----|-----|---------|
| 10-20 | 2GB | 1 vCPU | 20GB |
| 20-50 | 4GB | 2 vCPU | 40GB |
| 50-100 | 8GB | 4 vCPU | 80GB |

**Recommended VPS Providers:**
- Hetzner Cloud (CX21/CX31) - ~$5-10/month
- Contabo Cloud VPS - ~$7/month
- DigitalOcean Droplets - ~$6-12/month

---

## Security Notes

1. **Change default credentials** - Update ADMIN_PASSWORD and SECRET_KEY
2. **Use HTTPS** - Deploy behind Caddy/Nginx with SSL
3. **Firewall** - Only expose necessary ports
4. **Updates** - Keep Docker and system updated
5. **Backups** - Regular backups of data and profiles
