"""
Scheduler service for periodic worker tasks.
Runs as a separate container to schedule account aging.
"""

import os
import time
import random
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from redis import Redis
from rq import Queue

# Configuration - Romanian time (GMT+2), 9pm to 5am = 8 hours for 60 accounts
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
WORKER_START_HOUR = int(os.getenv("WORKER_START_HOUR", 21))  # 9pm
WORKER_END_HOUR = int(os.getenv("WORKER_END_HOUR", 5))       # 5am
WORKER_TIMEZONE = os.getenv("WORKER_TIMEZONE", "Europe/Bucharest")
WORKER_BATCH_SIZE = int(os.getenv("WORKER_BATCH_SIZE", 60))

# Redis connection
redis_conn = Redis.from_url(REDIS_URL)
low_queue = Queue("low", connection=redis_conn)


def is_within_worker_hours(hour: int) -> bool:
    """Check if given hour is within worker hours (handles midnight crossing)."""
    if WORKER_START_HOUR <= WORKER_END_HOUR:
        # Normal range (e.g., 9 to 17)
        return WORKER_START_HOUR <= hour < WORKER_END_HOUR
    else:
        # Crosses midnight (e.g., 19 to 3)
        return hour >= WORKER_START_HOUR or hour < WORKER_END_HOUR


def schedule_worker_cycle():
    """
    Schedule worker browsing for the next batch of accounts.
    Uses sequential selection with offset tracking - cycles through all accounts over multiple nights.
    """
    print(f"[{datetime.now()}] Starting scheduled worker cycle")

    # Import here to avoid circular imports
    from core.database import Database

    db = Database()

    # Get next batch of accounts sequentially (up to WORKER_BATCH_SIZE)
    accounts, new_offset = db.get_accounts_for_worker(limit=WORKER_BATCH_SIZE)

    if not accounts:
        print(f"[{datetime.now()}] No active accounts for worker")
        return

    total_active = db.count_accounts(status="active")
    print(f"[{datetime.now()}] Selected {len(accounts)} accounts (offset now at {new_offset}/{total_active})")

    # Queue jobs for selected accounts
    for account in accounts:
        low_queue.enqueue(
            "web.tasks.task_worker_browse",
            account["id"],
            job_timeout=900,
        )
        print(f"[{datetime.now()}] Queued worker for {account['username']}")

    print(f"[{datetime.now()}] Scheduled {len(accounts)} worker jobs")


def get_worker_hours() -> list[int]:
    """Get list of hours within worker window (handles midnight crossing)."""
    if WORKER_START_HOUR <= WORKER_END_HOUR:
        # Normal range (e.g., 9 to 17)
        return list(range(WORKER_START_HOUR, WORKER_END_HOUR))
    else:
        # Crosses midnight (e.g., 19 to 3)
        # Hours from start to midnight + hours from midnight to end
        return list(range(WORKER_START_HOUR, 24)) + list(range(0, WORKER_END_HOUR))


def main():
    """Main scheduler entry point."""
    print(f"Starting scheduler...")
    print(f"Worker window: {WORKER_START_HOUR}:00 - {WORKER_END_HOUR}:00 {WORKER_TIMEZONE}")
    print(f"Batch size: {WORKER_BATCH_SIZE} accounts per night")

    scheduler = BlockingScheduler(timezone=WORKER_TIMEZONE)

    # Schedule to run once at the start of the worker window
    # Random minute between 0-30 for some variation
    start_minute = random.randint(0, 30)
    scheduler.add_job(
        schedule_worker_cycle,
        CronTrigger(hour=WORKER_START_HOUR, minute=start_minute),
        id="worker_cycle_nightly",
        replace_existing=True,
    )
    print(f"Scheduled nightly worker cycle at {WORKER_START_HOUR}:{start_minute:02d} {WORKER_TIMEZONE}")

    print("Scheduler started. Press Ctrl+C to exit.")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("Scheduler stopped.")


if __name__ == "__main__":
    main()
