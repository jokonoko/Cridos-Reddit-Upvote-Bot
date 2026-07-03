# Cridos Reddit Farm - Setup Guide

## What's Implemented

- [x] Database layer (SQLite) - Account storage, action logs, stats
- [x] Browser manager with stealth (Playwright + playwright-stealth)
- [x] Proxy manager with sticky session support
- [x] Account management commands (add, remove, list, info)
- [x] Health check command (detect bans, suspensions, shadowbans)
- [x] Upvote command with delays and randomization
- [x] Background worker (scheduled browsing activity)
- [x] Logging and statistics
- [x] Backup utility

## What Needs Manual Setup

### 1. Environment Setup (Required)

```bash
# Clone/navigate to project
cd redditfarm

# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Linux/Mac)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### 2. Configuration (Required)

```bash
# Copy example config
cp .env.example .env

# Edit .env with your settings
```

**Minimum required in .env:**
```env
# If using proxies (recommended)
PROXY_PROVIDER=iproyal
PROXY_HOST=geo.iproyal.com
PROXY_PORT=12321
PROXY_USERNAME=your_username
PROXY_PASSWORD=your_password
```

### 3. Initialize Database

```bash
python main.py init-db
```

### 4. Proxy Setup (Recommended)

**Option A: IPRoyal (Recommended - $1.75/GB)**
1. Sign up at https://iproyal.com
2. Purchase residential proxies
3. Get credentials from dashboard
4. Add to .env file

**Option B: Other Providers**
- Smartproxy: https://smartproxy.com
- Bright Data: https://brightdata.com
- Oxylabs: https://oxylabs.io

Proxy format varies by provider - see `core/proxy_manager.py` for supported formats.

### 5. VPS Deployment (For 24/7 Worker)

**Recommended: Hetzner CX22 (~$5/month)**

```bash
# On VPS (Ubuntu)
sudo apt update
sudo apt install python3.11 python3.11-venv git

# Clone project
git clone <your-repo> redditfarm
cd redditfarm

# Setup
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
playwright install-deps  # Install system dependencies

# Configure
cp .env.example .env
nano .env  # Edit with your settings

# Initialize
python main.py init-db
```

**Run Worker as Service:**

Create `/etc/systemd/system/redditfarm-worker.service`:
```ini
[Unit]
Description=Reddit Farm Worker
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/home/your_username/redditfarm
Environment=PATH=/home/your_username/redditfarm/venv/bin
ExecStart=/home/your_username/redditfarm/venv/bin/python main.py worker start --foreground
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable redditfarm-worker
sudo systemctl start redditfarm-worker
sudo systemctl status redditfarm-worker
```

---

## What's NOT Implemented (Future Improvements)

### High Priority

1. **CAPTCHA Handling**
   - Reddit occasionally shows CAPTCHAs
   - Options: 2Captcha integration, manual solving queue
   - Current behavior: Action fails if CAPTCHA appears

2. **2FA Support**
   - Accounts with 2FA enabled need manual intervention
   - Could integrate TOTP library for automated 2FA

3. **Comment/Post Actions**
   - Currently only upvoting is implemented
   - Could add: downvote, comment, post, award

4. **Account Aging Automation**
   - Auto-join subreddits
   - Auto-comment on random posts
   - Build karma before using for upvotes

### Medium Priority

5. **Web Dashboard**
   - Visual interface for monitoring
   - Account management UI
   - Real-time stats

6. **Telegram/Discord Notifications**
   - Alert on account bans
   - Daily status reports
   - Action confirmations

7. **Proxy Health Monitoring**
   - Auto-test proxies periodically
   - Auto-rotate failed proxies
   - Proxy pool management

8. **Rate Limit Intelligence**
   - Detect rate limiting
   - Auto-adjust delays
   - Per-subreddit limits

### Low Priority

9. **Multi-post Queue**
   - Queue multiple posts for upvoting
   - Spread upvotes across posts
   - Scheduling system

10. **Account Purchasing Integration**
    - Auto-import from account marketplaces
    - Quality verification

11. **Analytics Dashboard**
    - Historical charts
    - Ban rate trends
    - ROI calculations

---

## Quick Start After Setup

```bash
# 1. Add your first account
python main.py add-account -u "username" -p "password"

# 2. Test it works
python main.py check-health -u "username"

# 3. Test upvote (use a random post, not yours)
python main.py test-upvote -u "username"

# 4. Add more accounts (CSV format: username,password)
python main.py add-accounts -f accounts.csv

# 5. Start worker for account aging
python main.py worker start

# 6. After aging accounts, upvote your posts
python main.py upvote "https://reddit.com/r/subreddit/comments/xxx/your_post"

# 7. Monitor
python main.py stats
python main.py logs --tail 50
```

---

## Troubleshooting

### "Login failed"
- Check username/password
- Try with `--headless=false` to see what's happening
- Reddit may be showing CAPTCHA

### "Not logged in" after adding account
- Session may have expired
- Run `check-health --fix` to re-login

### Upvote not working
- Use `test-upvote -u username --no-headless` to debug
- Reddit's HTML structure may have changed
- Check browser console for errors

### Proxy not working
- Test with `python main.py test-proxy`
- Check proxy credentials
- Try different proxy provider format

### Worker not running
- Check `python main.py worker status`
- View logs: `tail -f logs/worker.log`
- Check systemd: `journalctl -u redditfarm-worker -f`

---

## Files Structure

```
redditfarm/
├── main.py              # CLI entry point
├── config.py            # Configuration
├── requirements.txt     # Dependencies
├── .env                 # Your config (create from .env.example)
├── .env.example         # Config template
├── PLAN.md              # Full project plan
├── SETUP.md             # This file
│
├── core/
│   ├── __init__.py
│   ├── database.py      # SQLite operations
│   ├── browser.py       # Playwright + stealth
│   └── proxy_manager.py # Proxy handling
│
├── commands/
│   ├── __init__.py
│   ├── account_manager.py  # add/remove/list
│   ├── health_check.py     # check-health
│   ├── upvote.py           # upvote command
│   └── worker.py           # background worker
│
├── data/
│   └── farm.db          # SQLite database (created on init)
│
├── profiles/            # Browser profiles (created per account)
│   └── {account_id}/
│
└── logs/                # Log files
```

---

## Cost Summary

| Item | Provider | Monthly Cost |
|------|----------|--------------|
| VPS | Hetzner CX22 | ~$5 |
| Proxies | IPRoyal Residential (50 accounts, light use) | ~$10-20 |
| **Total** | | **~$15-25** |

---

## Security Notes

- `.env` contains sensitive data - never commit to git
- Add to `.gitignore`: `.env`, `data/`, `profiles/`, `logs/`
- Proxy credentials are stored in plain text
- Consider encrypting passwords in database for production use
