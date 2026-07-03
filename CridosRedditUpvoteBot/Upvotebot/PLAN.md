# Reddit Upvote Farm - Implementation Plan

## Project Context

**Purpose**: Experimental automation project for upvoting personal Reddit posts using multiple accounts.

**Disclaimer**: This violates Reddit's Terms of Service. Accounts may be banned. This is an educational/experimental project to learn browser automation, anti-detection techniques, and distributed system patterns.

**Acceptance**: Account bans are acceptable - the goal is to minimize detection while learning.

---

## Overview

A Python-based browser automation system to manage multiple Reddit accounts, perform upvote actions on target posts, check account health/ban status, and run scheduled background activity to maintain account legitimacy and reduce detection risk.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         VPS (Ubuntu)                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   CLI Tool   │    │   Scheduler  │    │   Worker     │      │
│  │  (commands)  │    │   (APScheduler)│  │  (12am-5am)  │      │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘      │
│         │                   │                   │               │
│         └───────────────────┼───────────────────┘               │
│                             ▼                                   │
│                    ┌──────────────┐                             │
│                    │    Core      │                             │
│                    │   Engine     │                             │
│                    └──────┬───────┘                             │
│                           │                                     │
│         ┌─────────────────┼─────────────────┐                   │
│         ▼                 ▼                 ▼                   │
│  ┌────────────┐   ┌────────────┐   ┌────────────┐              │
│  │  SQLite DB │   │ Playwright │   │   Proxy    │              │
│  │ (accounts) │   │  Browser   │   │  Manager   │              │
│  └────────────┘   └────────────┘   └────────────┘              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Commands / Features

### 1. `upvote` - Upvote a Reddit Post
- Input: Reddit post URL (e.g., `https://reddit.com/r/subreddit/comments/abc123/title`)
- Load account from database (prioritize accounts that haven't voted recently)
- Launch browser with persistent profile (already logged in)
- Navigate to post URL
- Locate and click the upvote button
- Verify upvote registered (button turns orange)
- Add random delay (30s - 3min between accounts)
- Rotate to next account with different proxy/fingerprint
- Repeat for N accounts (default: all active accounts)
- Log success/failure per account

### 2. `check-health` - Verify Account Status
- Iterate through all accounts (or specific account)
- Navigate to `reddit.com/user/{username}` or account settings
- Detect ban/suspension indicators:
  - "This account has been suspended" page
  - "Account suspended" banner
  - Redirect to `/account/suspended`
  - 403/404 on profile page
  - Shadowban detection: post something, check if visible logged out
  - Rate limit messages ("you're doing that too much")
- Status categories:
  - `active` - Account works normally
  - `suspended` - Permanent suspension
  - `shadowbanned` - Actions don't register publicly
  - `restricted` - Rate limited / temporarily restricted
  - `unknown` - Could not determine status
- Update account status in database
- Generate health report with summary stats

### 3. `add-account` - Add New Account
- Interactive or CLI arguments
- Required: username, password
- Optional: proxy, email (for recovery), notes
- Process:
  1. Launch browser with new profile directory
  2. Navigate to reddit.com/login
  3. Perform login with provided credentials
  4. Handle 2FA if enabled (prompt user or skip)
  5. Verify login successful (check for username in header)
  6. Save browser profile (cookies, localStorage persist)
  7. Store account in database
- Bulk import option: `add-accounts --file accounts.csv`

### 4. `remove-account` - Remove Account
- Delete from database
- Clean up browser profile directory
- Remove associated cookies/session data

### 5. `worker` - Background Activity Worker (12am-5am)
- Scheduled daemon that runs automatically during configured hours
- **Purpose**: Make accounts look like real users, not dormant vote-bots
- For each account (randomized order):
  1. Open browser with account's profile
  2. Navigate to reddit.com homepage
  3. Scroll through feed (random distance, random speed)
  4. Click on 1-3 random posts (read them)
  5. Maybe upvote 1-2 posts organically (not target posts)
  6. Visit 1-2 subreddits the account is "interested in"
  7. Occasionally check notifications/inbox
  8. Random session length (2-10 minutes)
  9. Close browser
  10. Wait random interval (5-30 min) before next account
- Spreads 50 accounts across 5 hours naturally
- Logs all activity for analysis
- Graceful shutdown on SIGTERM

### 6. `list-accounts` - View All Accounts
- Display table of all accounts with:
  - Username
  - Status (active/banned/shadowbanned)
  - Last action date
  - Last health check
  - Assigned proxy
- Filter options: `--status active`, `--status banned`
- Sort options: `--sort last-action`, `--sort created`

---

## Cost Analysis

### VPS Options (Low Cost)

| Provider | Plan | Specs | Price/Month | Notes |
|----------|------|-------|-------------|-------|
| **Hetzner** (Recommended) | CX22 | 2 vCPU, 4GB RAM, 40GB SSD | €4.35 (~$4.70) | Best value, EU datacenter |
| **Netcup** | VPS 500 G10s | 2 vCPU, 4GB RAM, 128GB SSD | €4.25 (~$4.60) | German hosting |
| **Contabo** | Cloud VPS S | 4 vCPU, 8GB RAM, 50GB SSD | $6.99 | More RAM for parallelism |
| **RackNerd** | KVM VPS | 2 vCPU, 4GB RAM, 80GB SSD | $23.88/year (~$2/mo) | Annual deal |
| **DigitalOcean** | Basic Droplet | 1 vCPU, 2GB RAM, 50GB SSD | $12 | More expensive but reliable |

**Recommendation**: Hetzner CX22 or Contabo - best balance of cost and specs.

### Proxy Options (Low Detection)

| Provider | Type | Price | Detection Risk | Best For |
|----------|------|-------|----------------|----------|
| **IPRoyal** | Residential | $1.75/GB | Very Low | Budget residential |
| **Smartproxy** | Residential | $2.20/GB | Very Low | Reliable, good rotation |
| **Bright Data** | Residential | $3.00/GB | Very Low | Enterprise, most reliable |
| **Proxy-Cheap** | Residential | $3.49/GB | Low | Good middle ground |
| **Webshare** | Datacenter | $0.05/proxy/mo | Medium | Testing only |
| **ProxyScrape** | Rotating DC | $5/mo | Medium-High | Budget option |

**Recommendation**:
- **Primary**: IPRoyal Residential ($1.75/GB) - Best price/quality ratio
- **Budget Alternative**: Webshare rotating datacenter for testing

### Proxy Strategy for 50+ Accounts

Option A: **Sticky Residential Sessions**
- Each account gets a sticky session (same IP for X minutes)
- Cost: ~$10-20/month for moderate usage
- Best for maintaining consistent identity per account

Option B: **Rotating Residential**
- IP rotates per request or per session
- Cost: ~$5-15/month
- Good for actions, less ideal for maintaining sessions

**Estimated Monthly Costs:**

| Component | Low Estimate | High Estimate |
|-----------|--------------|---------------|
| VPS | $4.70 | $12.00 |
| Proxies (50 accounts, light use) | $10.00 | $30.00 |
| **Total** | **$14.70** | **$42.00** |

---

## Technical Stack

```
Python 3.11+
├── playwright          # Browser automation (faster than Selenium)
├── playwright-stealth  # Anti-detection patches
├── sqlite3             # Database (built-in)
├── apscheduler         # Task scheduling for worker
├── click               # CLI framework
├── rich                # Pretty terminal output
└── python-dotenv       # Environment configuration
```

---

## Database Schema

```sql
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    proxy TEXT,                          -- Optional dedicated proxy
    profile_path TEXT,                   -- Browser profile directory
    status TEXT DEFAULT 'active',        -- active, banned, suspended, unknown
    last_health_check DATETIME,
    last_action DATETIME,
    last_worker_run DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

CREATE TABLE action_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER,
    action_type TEXT,                    -- 'action', 'health_check', 'worker'
    target_url TEXT,
    status TEXT,                         -- success, failed, error
    error_message TEXT,
    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE proxies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proxy_url TEXT NOT NULL,             -- http://user:pass@ip:port
    type TEXT,                           -- residential, datacenter
    provider TEXT,
    is_active BOOLEAN DEFAULT 1,
    last_used DATETIME,
    fail_count INTEGER DEFAULT 0
);

CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

---

## Project Structure

```
redditfarm/
├── main.py                 # CLI entry point
├── config.py               # Configuration management
├── .env                    # Environment variables (secrets)
├── .env.example            # Template for .env
│
├── core/
│   ├── __init__.py
│   ├── browser.py          # Playwright browser management
│   ├── database.py         # SQLite operations
│   ├── proxy_manager.py    # Proxy rotation logic
│   └── actions.py          # Page-specific actions
│
├── commands/
│   ├── __init__.py
│   ├── run_action.py       # run-action command
│   ├── health_check.py     # check-health command
│   ├── account_manager.py  # add/remove account commands
│   └── worker.py           # Background worker
│
├── profiles/               # Browser profiles (persistent sessions)
│   └── {account_id}/
│
├── logs/                   # Application logs
│
├── data/
│   └── farm.db             # SQLite database
│
└── requirements.txt
```

---

## Anti-Detection Measures (Reddit-Specific)

### 1. Browser Fingerprint Management
- Use `playwright-stealth` to patch detection vectors:
  - `navigator.webdriver` = false
  - Consistent WebGL renderer per account
  - Realistic `navigator.plugins` array
  - Proper `chrome.runtime` object
- **Per-account fingerprint persistence**:
  - Generate fingerprint on account creation
  - Store: viewport, user-agent, timezone, language
  - Reuse same fingerprint every session (consistency matters)
- Disable WebRTC to prevent IP leak through STUN
- Canvas fingerprint: slight randomization but consistent per account

### 2. Behavioral Anti-Detection
- **Mouse movements**: Bezier curves, not linear teleportation
- **Scrolling**: Variable speed, occasional pauses, overshoot and correct
- **Typing**: Random delays between keystrokes (50-150ms)
- **Click patterns**: Don't click center of elements, randomize within bounds
- **Session timing**:
  - Upvote action: 30s - 3min between accounts
  - Worker sessions: 2-10 minutes each
  - Never instant actions

### 3. Reddit-Specific Detection Vectors
Reddit tracks:
- **Vote timing patterns**: 50 upvotes in 5 minutes = obvious bot
- **Account age + karma ratio**: New accounts voting suspiciously
- **IP correlation**: Multiple accounts from same IP voting same post
- **Browser fingerprint correlation**: Same fingerprint = same person
- **Behavioral similarity**: All accounts do exact same actions

Mitigations:
- Spread upvotes over hours, not minutes
- Use accounts with some age/karma (or age them with worker)
- One residential IP per account (sticky sessions)
- Unique fingerprint per account
- Randomize all behavior with variance

### 4. Session & Cookie Management
- **Persistent profiles**: Never clear cookies
- **Session age**: Old sessions look more legitimate
- **Cookie consistency**: Same cookies = same "browser" to Reddit
- Store profiles in `./profiles/{account_id}/`
- Backup profiles (they're valuable)

### 5. Proxy Strategy for Reddit
- **Critical**: Reddit detects datacenter IPs aggressively
- **Required**: Residential proxies only
- **Ideal**: Static residential (same IP per account always)
- **Acceptable**: Rotating residential with sticky sessions (10+ min)
- **Configuration**:
  ```
  Account 1 → Proxy session "acc1_session" → Same IP every time
  Account 2 → Proxy session "acc2_session" → Different same IP
  ```
- **Geo-targeting**: Match account's supposed location

### 6. Timing & Rate Limits
- **Upvote command**:
  - Max 10-15 accounts per hour on same post
  - Random delays: 30s minimum, 3min average
  - Never upvote at exact intervals
- **Worker schedule**:
  - 12am-5am (when real users are less active, but still exist)
  - Randomize start time each night (±30 min)
  - Don't run every night (skip 1-2 days randomly)
- **Health checks**:
  - Run weekly, not daily
  - Spread across hours, not all at once

---

## Implementation Phases

### Phase 1: Core Infrastructure
- [ ] Set up project structure
- [ ] Implement database layer
- [ ] Create browser manager with stealth
- [ ] Proxy manager with rotation

### Phase 2: Account Management
- [ ] `add-account` command with initial login
- [ ] `remove-account` command with cleanup
- [ ] `list-accounts` command for overview

### Phase 3: Health Check System
- [ ] Implement health check logic
- [ ] Detect various ban/suspension states
- [ ] Update account status in DB
- [ ] Generate health report

### Phase 4: Action Execution
- [ ] `run-action` command framework
- [ ] Configurable action definitions
- [ ] Error handling and retry logic
- [ ] Logging and reporting

### Phase 5: Background Worker
- [ ] APScheduler integration
- [ ] Worker browsing logic (scroll, random pages)
- [ ] Time-based scheduling (12am-5am)
- [ ] Graceful shutdown handling

### Phase 6: Deployment
- [ ] VPS setup guide
- [ ] Systemd service for worker
- [ ] Monitoring and alerting
- [ ] Backup strategy for DB and profiles

---

## Configuration Example

```env
# .env file
DATABASE_PATH=./data/farm.db
PROFILES_DIR=./profiles
LOG_LEVEL=INFO

# Proxy configuration
PROXY_PROVIDER=iproyal
PROXY_USERNAME=your_username
PROXY_PASSWORD=your_password
PROXY_ENDPOINT=geo.iproyal.com:12321

# Worker settings
WORKER_START_HOUR=0
WORKER_END_HOUR=5
WORKER_TIMEZONE=UTC

# Browser settings
HEADLESS=true
SLOW_MO=100
```

---

## CLI Usage Examples

```bash
# === Account Management ===

# Add a single account (interactive login)
python main.py add-account --username "throwaway_2024" --password "securepass123"

# Add account with dedicated proxy
python main.py add-account --username "alt_account_1" --password "pass456" \
  --proxy "http://user:pass@geo.iproyal.com:12321:session-alt1"

# Bulk import from CSV
python main.py add-accounts --file accounts.csv
# CSV format: username,password,proxy(optional)

# Remove an account (deletes profile too)
python main.py remove-account --username "banned_user"

# List all accounts
python main.py list-accounts

# List only active accounts
python main.py list-accounts --status active

# View detailed account info
python main.py account-info --username "throwaway_2024"

# === Health Checks ===

# Check health of all accounts
python main.py check-health

# Check specific account
python main.py check-health --username "alt_account_1"

# Generate health report
python main.py check-health --report

# === Upvoting ===

# Upvote a post with all active accounts
python main.py upvote "https://reddit.com/r/subreddit/comments/abc123/my_post"

# Upvote with specific number of accounts
python main.py upvote "https://reddit.com/r/subreddit/comments/abc123/my_post" --accounts 10

# Upvote with specific accounts only
python main.py upvote "https://reddit.com/r/subreddit/comments/abc123/my_post" \
  --usernames "user1,user2,user3"

# Dry run (see what would happen without doing it)
python main.py upvote "https://reddit.com/r/subreddit/comments/abc123/my_post" --dry-run

# === Background Worker ===

# Start the worker daemon
python main.py worker start

# Start in foreground (for testing)
python main.py worker start --foreground

# Check worker status
python main.py worker status

# Stop the worker
python main.py worker stop

# Run worker once manually (outside schedule)
python main.py worker run-once

# === Utilities ===

# Test proxy connectivity
python main.py test-proxy --proxy "http://user:pass@ip:port"

# Backup all profiles
python main.py backup-profiles --output ./backups/

# View action logs
python main.py logs --tail 50

# View logs for specific account
python main.py logs --username "throwaway_2024"
```

---

## Monitoring & Logging

### Log Files
- `logs/app.log` - General application logs
- `logs/actions.log` - Action execution logs
- `logs/worker.log` - Worker activity logs
- `logs/errors.log` - Error-only logs

### Metrics to Track
- Account health status distribution
- Action success/failure rates
- Proxy performance
- Worker completion rates

---

## Risk Mitigation

1. **Account Bans** (Expected, minimize impact)
   - Start with 3-5 accounts, scale to 10, then 20, then 50
   - Use high-quality residential proxies
   - Implement realistic delays (err on side of slower)
   - Don't upvote same post more than once per day
   - Age accounts with worker before using for upvotes
   - Accept some losses - budget for ~20% ban rate

2. **Proxy Detection**
   - Residential only (no datacenter)
   - Test proxies before assigning to accounts
   - If account gets banned, rotate its proxy
   - Monitor proxy provider reputation

3. **VPS IP Flagged**
   - VPS IP never touches Reddit directly
   - All traffic goes through residential proxies
   - VPS is just the orchestration layer

4. **Data Loss**
   - Daily DB backup (cron job)
   - Weekly profile directory backup
   - Store backups off-VPS (S3, rsync to local)
   - Git for code versioning

5. **Detection Patterns**
   - Never upvote same post with all accounts
   - Vary which accounts upvote which posts
   - Don't upvote only your posts (mix in organic activity)
   - Some accounts should never upvote your posts (decoys)

---

## Experiment Tracking

Track these metrics to measure detection risk:

| Metric | Target | Alert Threshold |
|--------|--------|-----------------|
| Account ban rate (weekly) | <5% | >15% |
| Upvote success rate | >95% | <85% |
| Shadowban detection | 0% | >5% |
| Worker completion rate | >90% | <80% |

### A/B Testing Ideas
- Compare ban rates: 1min vs 3min delays between upvotes
- Compare ban rates: worker active vs worker disabled
- Compare ban rates: sticky IP vs rotating IP
- Compare ban rates: new accounts vs aged accounts

---

## Quick Start (After Implementation)

```bash
# 1. Clone and setup
git clone <repo>
cd redditfarm
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
playwright install chromium

# 2. Configure
cp .env.example .env
# Edit .env with your proxy credentials

# 3. Initialize database
python main.py init-db

# 4. Add your first account (test with 1)
python main.py add-account --username "test_account" --password "password"

# 5. Verify it works
python main.py check-health --username "test_account"

# 6. Test upvote on a random post (not yours)
python main.py upvote "https://reddit.com/r/test/comments/xxx/test" --accounts 1

# 7. If working, add more accounts
python main.py add-accounts --file my_accounts.csv

# 8. Start worker for account aging
python main.py worker start

# 9. After a few days, use for real upvotes
python main.py upvote "https://reddit.com/r/mysubreddit/comments/abc/mypost"
```

---

## Next Steps

1. ~~Confirm target website/service~~ **Reddit - confirmed**
2. Set up development environment
3. Start Phase 1 implementation
4. Test locally with 1-2 accounts (no proxy)
5. Purchase VPS (Hetzner CX22 ~$5/mo)
6. Purchase residential proxies (IPRoyal ~$10-20/mo)
7. Deploy to VPS
8. Add 5 accounts, run worker for 1 week
9. Test upvoting, monitor ban rates
10. Scale based on results
