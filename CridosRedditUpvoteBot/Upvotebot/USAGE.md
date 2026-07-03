# Cridos Reddit Farm - Usage Guide

A comprehensive guide to using the Cridos Reddit Farm CLI tool and Web Dashboard.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Web Dashboard](#web-dashboard)
3. [Command Reference](#command-reference)
   - [Account Management](#account-management)
   - [Health Checks](#health-checks)
   - [Upvoting](#upvoting)
   - [Background Worker](#background-worker)
   - [Utilities](#utilities)
4. [Configuration](#configuration)
5. [Workflows](#workflows)
6. [Troubleshooting](#troubleshooting)

---

## Quick Start

### CLI Quick Start

```bash
# 1. Initialize the database
python main.py init-db

# 2. Test your proxy connection (optional but recommended)
python main.py test-proxy

# 3. Add your first account
python main.py add-account -u "your_username" -p "your_password"

# 4. Verify the account is working
python main.py check-health -u "your_username"

# 5. View your accounts
python main.py list-accounts

# 6. Upvote a post
python main.py upvote "https://reddit.com/r/subreddit/comments/abc123/post_title"
```

### Docker Quick Start

```bash
# 1. Configure environment
cp .env.docker .env
# Edit .env with your settings

# 2. Build and start
docker compose up -d

# 3. Access dashboard
# Open http://localhost:8000
# Login: admin / [your ADMIN_PASSWORD]
```

---

## Web Dashboard

The web dashboard provides a visual interface for managing your Reddit farm.

### Accessing the Dashboard

- **URL:** `http://localhost:8000` (or your server IP)
- **Login:** HTTP Basic Auth
  - Username: `admin`
  - Password: Your `ADMIN_PASSWORD` from `.env`

### Dashboard Features

#### Home Dashboard
- Overview statistics (total accounts, active, banned, shadowbanned)
- Quick action buttons
- Recent activity feed
- Account list preview

#### Accounts Page (`/accounts`)
- View all accounts with status indicators
- Filter by status (active, suspended, shadowbanned, unknown)
- Add new accounts
- Check health of individual or all accounts
- Delete accounts

#### Upvotes Page (`/upvotes`)
- **Multi-post support:** Enter multiple Reddit URLs (one per line)
- **Randomized accounts:** Accounts are shuffled for each post
- Specify number of accounts per post
- Configure delays between accounts
- Real-time progress tracking
- Detailed results per post

#### Worker Page (`/worker`)
- View queue statistics
- Trigger worker runs for individual or multiple accounts
- View recent worker activity logs

### Upvoting via Dashboard

1. Go to **Upvotes** page
2. Enter Reddit post URLs (one per line):
   ```
   https://reddit.com/r/subreddit/comments/abc123/post1
   https://reddit.com/r/another/comments/def456/post2
   https://reddit.com/r/third/comments/ghi789/post3
   ```
3. Set **Accounts per Post** (e.g., 5)
4. Adjust delays if needed (default: 30-180 seconds)
5. Click **Start Upvoting**

**How it works:**
- Posts are processed one at a time, in order
- For each post, accounts are **randomly shuffled**
- Same accounts can upvote multiple posts (different order each time)
- Progress updates in real-time

---

## Command Reference

### Account Management

#### `add-account` - Add a single account

Add a new Reddit account with interactive login verification.

```bash
python main.py add-account -u <username> -p <password> [options]
```

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--username` | `-u` | Reddit username (required) |
| `--password` | `-p` | Reddit password (required) |
| `--email` | `-e` | Recovery email (optional) |
| `--proxy` | | Custom proxy URL for this account |
| `--notes` | | Notes about this account |
| `--skip-login` | | Skip initial login verification |

**Examples:**
```bash
# Basic usage - opens browser to verify login
python main.py add-account -u "myaccount" -p "mypassword"

# With email and notes
python main.py add-account -u "myaccount" -p "mypassword" -e "email@example.com" --notes "Aged account, 500 karma"

# With custom proxy
python main.py add-account -u "myaccount" -p "mypassword" --proxy "http://user:pass@proxy.com:8080"

# Skip login verification (add to DB only)
python main.py add-account -u "myaccount" -p "mypassword" --skip-login
```

---

#### `add-accounts` - Bulk import from CSV

Import multiple accounts from a CSV file.

```bash
python main.py add-accounts -f <csv_file> [options]
```

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--file` | `-f` | Path to CSV file (required) |
| `--skip-login` | | Skip login verification for all |

**CSV Format:**
```csv
username,password,email,proxy,notes
user1,pass1,email1@mail.com,,Account 1
user2,pass2,,,Account 2
user3,pass3,email3@mail.com,http://proxy:8080,Has custom proxy
```

Required columns: `username`, `password`
Optional columns: `email`, `proxy`, `notes`

**Examples:**
```bash
# Import accounts and skip login
python main.py add-accounts -f accounts.csv --skip-login

# Import with login verification (slower but validates accounts)
python main.py add-accounts -f accounts.csv
```

---

#### `remove-account` - Delete an account

Remove an account and its browser profile.

```bash
python main.py remove-account -u <username> [options]
```

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--username` | `-u` | Reddit username to remove (required) |
| `--force` | `-f` | Skip confirmation prompt |

**Examples:**
```bash
# Remove with confirmation
python main.py remove-account -u "oldaccount"

# Force remove without confirmation
python main.py remove-account -u "oldaccount" -f
```

---

#### `list-accounts` - View all accounts

Display all accounts in a formatted table.

```bash
python main.py list-accounts [options]
```

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--status` | `-s` | Filter by status: `active`, `suspended`, `shadowbanned`, `unknown` |
| `--sort` | | Sort by: `created`, `last-action`, `username` |

**Examples:**
```bash
# List all accounts
python main.py list-accounts

# List only active accounts
python main.py list-accounts -s active

# List banned accounts sorted by username
python main.py list-accounts -s suspended --sort username

# List accounts sorted by last action
python main.py list-accounts --sort last-action
```

---

#### `account-info` - Detailed account information

Show detailed info for a specific account including recent activity.

```bash
python main.py account-info -u <username>
```

**Example:**
```bash
python main.py account-info -u "myaccount"
```

**Output includes:**
- Account ID, status, email
- Proxy configuration
- Profile path
- Created date
- Last action, health check, and worker run timestamps
- Notes
- 5 most recent actions

---

### Health Checks

#### `check-health` - Check account status

Verify accounts for bans, suspensions, and shadowbans.

```bash
python main.py check-health [options]
```

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--username` | `-u` | Check specific account (default: all) |
| `--report` | | Generate detailed report with recommendations |
| `--fix` | | Attempt to fix issues by re-logging in |

**Status Types:**
| Status | Description |
|--------|-------------|
| `active` | Account is working normally |
| `suspended` | Account has been suspended by Reddit |
| `shadowbanned` | Account is shadowbanned (posts invisible to others) |
| `restricted` | Account has rate limiting or restrictions |
| `login_required` | Session expired, needs re-login |
| `unknown` | Could not determine status |

**Examples:**
```bash
# Check all accounts
python main.py check-health

# Check specific account
python main.py check-health -u "myaccount"

# Check all with detailed report
python main.py check-health --report

# Check and attempt to fix login issues
python main.py check-health --fix

# Check specific account and fix if needed
python main.py check-health -u "myaccount" --fix
```

---

### Upvoting

#### `upvote` - Upvote a post (CLI)

Upvote a Reddit post using multiple accounts.

```bash
python main.py upvote <post_url> [options]
```

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--accounts` | `-n` | Number of accounts to use (default: all active) |
| `--usernames` | `-u` | Comma-separated list of specific usernames |
| `--dry-run` | | Preview without executing |
| `--delay-min` | | Minimum delay between accounts in seconds (default: 30) |
| `--delay-max` | | Maximum delay between accounts in seconds (default: 180) |

**Valid URL Formats:**
```
https://reddit.com/r/subreddit/comments/abc123/post_title
https://www.reddit.com/r/subreddit/comments/abc123/post_title
https://old.reddit.com/r/subreddit/comments/abc123/post_title
```

**Examples:**
```bash
# Upvote with all active accounts
python main.py upvote "https://reddit.com/r/test/comments/abc123/my_post"

# Upvote with 5 accounts
python main.py upvote "https://reddit.com/r/test/comments/abc123/my_post" -n 5

# Upvote with specific accounts
python main.py upvote "https://reddit.com/r/test/comments/abc123/my_post" -u "account1,account2,account3"

# Preview what would happen (dry run)
python main.py upvote "https://reddit.com/r/test/comments/abc123/my_post" --dry-run

# Custom delays (faster)
python main.py upvote "https://reddit.com/r/test/comments/abc123/my_post" --delay-min 10 --delay-max 30

# Custom delays (slower, more cautious)
python main.py upvote "https://reddit.com/r/test/comments/abc123/my_post" --delay-min 120 --delay-max 300
```

---

#### `test-upvote` - Interactive upvote testing

Test upvote functionality with a single account in interactive mode.

```bash
python main.py test-upvote -u <username> [options]
```

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--username` | `-u` | Account to test with (required) |
| `--headless/--no-headless` | | Run with or without visible browser (default: visible) |

**Examples:**
```bash
# Test with visible browser (recommended for debugging)
python main.py test-upvote -u "myaccount"

# Test headless
python main.py test-upvote -u "myaccount" --headless
```

This opens a browser where you can manually navigate and test the upvote functionality. Press Enter to close when done.

---

### Background Worker

The worker simulates organic browsing activity to age accounts and avoid detection.

#### `worker start` - Start the worker daemon

```bash
python main.py worker start [options]
```

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--foreground` | `-f` | Run in foreground (don't daemonize) |

**Examples:**
```bash
# Start in background
python main.py worker start

# Start in foreground (see output, Ctrl+C to stop)
python main.py worker start -f
```

---

#### `worker stop` - Stop the worker

```bash
python main.py worker stop
```

---

#### `worker status` - Check worker status

```bash
python main.py worker status
```

Shows:
- Whether worker is running
- Worker PID
- Schedule hours
- Number of accounts with recent activity

---

#### `worker run-once` - Manual worker run

Run a single worker cycle immediately.

```bash
python main.py worker run-once [options]
```

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--accounts` | `-n` | Limit number of accounts to process |

**Examples:**
```bash
# Run worker cycle for all accounts
python main.py worker run-once

# Run worker cycle for 5 accounts only
python main.py worker run-once -n 5
```

---

### Utilities

#### `init-db` - Initialize database

Create or reset the database.

```bash
python main.py init-db [options]
```

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--force` | `-f` | Delete existing database and recreate |

**Examples:**
```bash
# Initialize (fails if exists)
python main.py init-db

# Force reinitialize (deletes all data!)
python main.py init-db --force
```

---

#### `stats` - View statistics

Display overall farm statistics.

```bash
python main.py stats
```

**Shows:**
- Total accounts
- Active accounts
- Banned/suspended accounts
- Shadowbanned accounts
- Successful upvotes (last 7 days)
- Failed upvotes (last 7 days)
- Success rate

---

#### `test-proxy` - Test proxy connectivity

Test proxy connection and get IP information.

```bash
python main.py test-proxy [options]
```

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--proxy` | `-p` | Specific proxy URL to test (default: configured proxy) |

**Examples:**
```bash
# Test configured proxy
python main.py test-proxy

# Test specific proxy
python main.py test-proxy -p "http://user:pass@proxy.com:8080"
```

---

#### `backup-profiles` - Backup data

Backup database and browser profiles.

```bash
python main.py backup-profiles -o <output_directory>
```

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--output` | `-o` | Backup destination directory (required) |

**Example:**
```bash
python main.py backup-profiles -o ./backups
```

Creates a timestamped folder with `farm.db` and `profiles/` directory.

---

#### `logs` - View action logs

View recent action logs.

```bash
python main.py logs [options]
```

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--tail` | `-n` | Number of logs to show (default: 20) |
| `--username` | `-u` | Filter by username |
| `--action` | `-a` | Filter by action type: `upvote`, `worker`, `health_check` |

**Examples:**
```bash
# View last 20 logs
python main.py logs

# View last 50 logs
python main.py logs -n 50

# View logs for specific account
python main.py logs -u "myaccount"

# View only upvote logs
python main.py logs -a upvote

# Combine filters
python main.py logs -u "myaccount" -a upvote -n 10
```

---

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and configure:

```env
# Database
DATABASE_PATH=./data/farm.db

# Browser profiles directory
PROFILES_DIR=./profiles

# Logging
LOG_LEVEL=INFO
LOG_DIR=./logs

# Proxy configuration
PROXY_PROVIDER=iproyal
PROXY_HOST=geo.iproyal.com
PROXY_PORT=12321
PROXY_USERNAME=your_username
PROXY_PASSWORD=your_password

# Worker settings
WORKER_START_HOUR=0          # Start hour (24h format)
WORKER_END_HOUR=5            # End hour
WORKER_TIMEZONE=UTC          # Timezone
WORKER_SKIP_PROBABILITY=0.2  # 20% chance to skip a run

# Browser settings
HEADLESS=true                # Run browsers headless
SLOW_MO=50                   # Slow down actions (ms)

# Anti-detection delays (seconds)
MIN_ACTION_DELAY=30          # Min delay between accounts
MAX_ACTION_DELAY=180         # Max delay between accounts
MIN_SCROLL_DELAY=1           # Min scroll delay
MAX_SCROLL_DELAY=4           # Max scroll delay

# Web Dashboard (Docker only)
SECRET_KEY=your-secret-key   # Change in production
ADMIN_PASSWORD=admin         # Dashboard login password
```

### Proxy Providers

Supported providers and their formats:

| Provider | Format |
|----------|--------|
| IPRoyal | `http://user:pass@geo.iproyal.com:12321` |
| Smartproxy | `http://user:pass@gate.smartproxy.com:7000` |
| Bright Data | `http://user:pass@zproxy.lum-superproxy.io:22225` |
| Oxylabs | `http://user:pass@pr.oxylabs.io:7777` |

---

## Workflows

### New Account Setup Flow

1. **Add accounts:**
   ```bash
   python main.py add-account -u "newaccount" -p "password"
   ```

2. **Verify health:**
   ```bash
   python main.py check-health -u "newaccount"
   ```

3. **Age accounts with worker (recommended 1-2 weeks):**
   ```bash
   python main.py worker start
   ```

4. **Ready to use for upvoting**

### Daily Operation

```bash
# Morning: Check health of all accounts
python main.py check-health --report

# Review stats
python main.py stats

# Upvote posts as needed
python main.py upvote "https://reddit.com/..." -n 10

# Check results
python main.py logs -a upvote -n 20
```

### Multi-Post Upvoting (Web Dashboard)

1. Open dashboard at `http://localhost:8000/upvotes`
2. Enter multiple URLs:
   ```
   https://reddit.com/r/sub1/comments/abc/post1
   https://reddit.com/r/sub2/comments/def/post2
   https://reddit.com/r/sub3/comments/ghi/post3
   ```
3. Set accounts per post (e.g., 10)
4. Click "Start Upvoting"
5. Monitor progress in real-time

### Handling Banned Accounts

```bash
# Find banned accounts
python main.py list-accounts -s suspended

# Remove them
python main.py remove-account -u "bannedaccount" -f

# Or review each one
python main.py account-info -u "bannedaccount"
```

### Backup Routine

```bash
# Weekly backup
python main.py backup-profiles -o /path/to/backups/

# Verify backup exists
ls /path/to/backups/
```

---

## Troubleshooting

### Login Issues

**Problem:** "Login failed" or "Not logged in"

**Solutions:**
1. Test manually with visible browser:
   ```bash
   python main.py test-upvote -u "account" --no-headless
   ```
2. Check for CAPTCHA (requires manual solving)
3. Verify credentials are correct
4. Try re-adding the account:
   ```bash
   python main.py remove-account -u "account" -f
   python main.py add-account -u "account" -p "password"
   ```

### Proxy Issues

**Problem:** Proxy connection failed

**Solutions:**
1. Test proxy:
   ```bash
   python main.py test-proxy
   ```
2. Verify credentials in `.env`
3. Check proxy provider dashboard for usage limits
4. Try a different proxy endpoint

### Upvote Not Working

**Problem:** Upvotes fail or don't register

**Solutions:**
1. Check account health first:
   ```bash
   python main.py check-health -u "account" --fix
   ```
2. Test interactively:
   ```bash
   python main.py test-upvote -u "account" --no-headless
   ```
3. Check if Reddit UI has changed (may need code updates)
4. View error logs:
   ```bash
   python main.py logs -u "account" -a upvote
   ```

### Worker Not Running

**Problem:** Worker stops or doesn't run

**Solutions:**
1. Check status:
   ```bash
   python main.py worker status
   ```
2. Check logs:
   ```bash
   # Linux/Mac
   tail -f logs/worker.log

   # Windows
   type logs\worker.log
   ```
3. Try running manually:
   ```bash
   python main.py worker run-once -n 1
   ```
4. Run in foreground to see errors:
   ```bash
   python main.py worker start -f
   ```

### Database Issues

**Problem:** Database errors or corruption

**Solutions:**
1. Backup current data if possible
2. Reinitialize database:
   ```bash
   python main.py init-db --force
   ```
   Note: This deletes all account data!

### Docker Issues

**Problem:** Containers not starting

**Solutions:**
1. Check logs:
   ```bash
   docker compose logs web
   docker compose logs worker
   ```
2. Verify `.env` file exists and is configured
3. Check port conflicts:
   ```bash
   # Change WEB_PORT in .env if 8000 is in use
   ```
4. Rebuild containers:
   ```bash
   docker compose down
   docker compose build --no-cache
   docker compose up -d
   ```

---

## Best Practices

1. **Age accounts before using** - Run the worker for 1-2 weeks before upvoting
2. **Use residential proxies** - Datacenter IPs are instantly flagged
3. **Spread upvotes over time** - Don't upvote many accounts at once
4. **Monitor health regularly** - Check for bans daily
5. **Backup frequently** - Browser profiles contain valuable session data
6. **Use reasonable delays** - Faster is not better; it increases detection risk
7. **Don't upvote the same post too quickly** - Space out batches by hours/days
8. **Use multi-post feature** - Randomized account order per post reduces patterns
9. **Secure your dashboard** - Use strong ADMIN_PASSWORD and consider HTTPS
