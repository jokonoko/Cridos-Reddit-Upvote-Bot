import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

from config import DATABASE_PATH, ensure_dirs


class Database:
    def __init__(self, db_path: Path = DATABASE_PATH):
        ensure_dirs()
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    email TEXT,
                    proxy TEXT,
                    profile_path TEXT,
                    status TEXT DEFAULT 'active',
                    login_status TEXT DEFAULT 'unknown',
                    last_health_check DATETIME,
                    last_login_check DATETIME,
                    last_action DATETIME,
                    last_worker_run DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT,
                    fingerprint TEXT
                );

                CREATE TABLE IF NOT EXISTS action_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER,
                    action_type TEXT,
                    target_url TEXT,
                    status TEXT,
                    error_message TEXT,
                    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_id) REFERENCES accounts(id)
                );

                CREATE TABLE IF NOT EXISTS proxies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    proxy_url TEXT NOT NULL,
                    type TEXT,
                    provider TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    last_used DATETIME,
                    fail_count INTEGER DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status);
                CREATE INDEX IF NOT EXISTS idx_accounts_last_action ON accounts(last_action);
                CREATE INDEX IF NOT EXISTS idx_action_logs_account ON action_logs(account_id);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS joined_subreddits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    subreddit_name TEXT NOT NULL,
                    joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_id) REFERENCES accounts(id),
                    UNIQUE(account_id, subreddit_name)
                );

                CREATE INDEX IF NOT EXISTS idx_joined_subreddits_account ON joined_subreddits(account_id);
                CREATE INDEX IF NOT EXISTS idx_joined_subreddits_name ON joined_subreddits(subreddit_name);
            """)

            # Migration: Add new columns if they don't exist
            cursor = conn.execute("PRAGMA table_info(accounts)")
            columns = [row[1] for row in cursor.fetchall()]

            if 'login_status' not in columns:
                conn.execute("ALTER TABLE accounts ADD COLUMN login_status TEXT DEFAULT 'unknown'")

            if 'last_login_check' not in columns:
                conn.execute("ALTER TABLE accounts ADD COLUMN last_login_check DATETIME")

            if 'is_personalized' not in columns:
                conn.execute("ALTER TABLE accounts ADD COLUMN is_personalized BOOLEAN DEFAULT 0")

            if 'worker_batch_processed' not in columns:
                conn.execute("ALTER TABLE accounts ADD COLUMN worker_batch_processed BOOLEAN DEFAULT 0")

    # Account operations
    def add_account(
        self,
        username: str,
        password: str,
        email: str = None,
        proxy: str = None,
        notes: str = None,
        fingerprint: str = None,
    ) -> int:
        # Generate unique profile path using UUID to prevent reuse of banned account profiles
        profile_path = str(uuid.uuid4())

        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO accounts (username, password, email, proxy, profile_path, notes, fingerprint)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (username, password, email, proxy, profile_path, notes, fingerprint),
            )
            return cursor.lastrowid

    def get_account(self, username: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE username = ?", (username,)
            ).fetchone()
            return dict(row) if row else None

    def get_account_by_id(self, account_id: int) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_all_accounts(self, status: str = None) -> list[dict]:
        with self._get_conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM accounts WHERE status = ? ORDER BY last_action ASC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM accounts ORDER BY last_action ASC"
                ).fetchall()
            return [dict(row) for row in rows]

    def get_active_accounts(self, limit: int = None) -> list[dict]:
        with self._get_conn() as conn:
            query = """
                SELECT * FROM accounts
                WHERE status = 'active'
                ORDER BY last_action ASC NULLS FIRST
            """
            if limit:
                query += f" LIMIT {limit}"
            rows = conn.execute(query).fetchall()
            return [dict(row) for row in rows]

    def update_account(self, username: str, **kwargs) -> bool:
        if not kwargs:
            return False

        allowed_fields = {
            "password", "email", "proxy", "profile_path", "status", "login_status",
            "last_health_check", "last_login_check", "last_action", "last_worker_run",
            "notes", "fingerprint", "is_personalized", "worker_batch_processed"
        }
        fields = {k: v for k, v in kwargs.items() if k in allowed_fields}

        if not fields:
            return False

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [username]

        with self._get_conn() as conn:
            cursor = conn.execute(
                f"UPDATE accounts SET {set_clause} WHERE username = ?", values
            )
            return cursor.rowcount > 0

    def update_account_status(self, username: str, status: str) -> bool:
        return self.update_account(username, status=status, last_health_check=datetime.now().isoformat())

    def update_last_action(self, username: str) -> bool:
        return self.update_account(username, last_action=datetime.now().isoformat())

    def update_last_worker_run(self, username: str) -> bool:
        return self.update_account(username, last_worker_run=datetime.now().isoformat())

    def update_last_health_check(self, username: str, timestamp: str) -> bool:
        return self.update_account(username, last_health_check=timestamp)

    def update_login_status(self, username: str, login_status: str) -> bool:
        return self.update_account(username, login_status=login_status, last_login_check=datetime.now().isoformat())

    def set_profile_path(self, username: str, profile_path: str) -> bool:
        return self.update_account(username, profile_path=profile_path)

    def remove_account(self, username: str) -> bool:
        with self._get_conn() as conn:
            # First delete associated logs
            account = self.get_account(username)
            if account:
                conn.execute(
                    "DELETE FROM action_logs WHERE account_id = ?", (account["id"],)
                )
            cursor = conn.execute(
                "DELETE FROM accounts WHERE username = ?", (username,)
            )
            return cursor.rowcount > 0

    def account_exists(self, username: str) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM accounts WHERE username = ?", (username,)
            ).fetchone()
            return row is not None

    def count_accounts(self, status: str = None) -> int:
        with self._get_conn() as conn:
            if status:
                row = conn.execute(
                    "SELECT COUNT(*) FROM accounts WHERE status = ?", (status,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()
            return row[0]

    # Action log operations
    def log_action(
        self,
        account_id: int,
        action_type: str,
        target_url: str = None,
        status: str = "success",
        error_message: str = None,
    ) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO action_logs (account_id, action_type, target_url, status, error_message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (account_id, action_type, target_url, status, error_message),
            )
            return cursor.lastrowid

    def get_action_logs(
        self, account_id: int = None, action_type: str = None, limit: int = 50
    ) -> list[dict]:
        with self._get_conn() as conn:
            query = "SELECT * FROM action_logs WHERE 1=1"
            params = []

            if account_id:
                query += " AND account_id = ?"
                params.append(account_id)
            if action_type:
                query += " AND action_type = ?"
                params.append(action_type)

            query += f" ORDER BY executed_at DESC LIMIT {limit}"
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_worker_logs(self, limit: int = 100) -> list[dict]:
        """Get recent worker activity logs with account usernames."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT al.*, a.username
                FROM action_logs al
                JOIN accounts a ON al.account_id = a.id
                WHERE al.action_type = 'worker'
                ORDER BY al.executed_at DESC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    # Proxy operations
    def add_proxy(self, proxy_url: str, proxy_type: str = "residential", provider: str = None) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO proxies (proxy_url, type, provider)
                VALUES (?, ?, ?)
                """,
                (proxy_url, proxy_type, provider),
            )
            return cursor.lastrowid

    def get_available_proxy(self) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM proxies
                WHERE is_active = 1
                ORDER BY last_used ASC NULLS FIRST, fail_count ASC
                LIMIT 1
                """
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE proxies SET last_used = ? WHERE id = ?",
                    (datetime.now().isoformat(), row["id"]),
                )
                return dict(row)
            return None

    def mark_proxy_failed(self, proxy_id: int):
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE proxies SET fail_count = fail_count + 1,
                is_active = CASE WHEN fail_count >= 5 THEN 0 ELSE 1 END
                WHERE id = ?
                """,
                (proxy_id,),
            )

    # Settings operations
    def get_setting(self, key: str, default: str = None) -> Optional[str]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else default

    def set_setting(self, key: str, value: str) -> bool:
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            return True

    def get_worker_offset(self) -> int:
        """Get the current worker offset for sequential account processing."""
        offset = self.get_setting("worker_offset", "0")
        return int(offset)

    def set_worker_offset(self, offset: int) -> bool:
        """Set the worker offset for sequential account processing."""
        return self.set_setting("worker_offset", str(offset))

    def get_accounts_for_worker(self, limit: int = 60) -> tuple[list[dict], int]:
        """
        Get the next batch of accounts for worker, cycling through sequentially.
        Returns (accounts, new_offset).
        """
        with self._get_conn() as conn:
            # Get all active accounts ordered by ID for consistent ordering
            rows = conn.execute(
                """
                SELECT * FROM accounts
                WHERE status = 'active'
                ORDER BY id ASC
                """
            ).fetchall()
            all_accounts = [dict(row) for row in rows]

            if not all_accounts:
                return [], 0

            total = len(all_accounts)
            offset = self.get_worker_offset()

            # If offset is beyond total, reset to 0
            if offset >= total:
                offset = 0

            # Get accounts from offset, wrapping around if needed
            if offset + limit <= total:
                # Simple slice
                selected = all_accounts[offset:offset + limit]
                new_offset = offset + limit
            else:
                # Wrap around
                selected = all_accounts[offset:] + all_accounts[:limit - (total - offset)]
                new_offset = limit - (total - offset)

            # Update offset for next run
            self.set_worker_offset(new_offset)

            return selected, new_offset

    def get_next_worker_batch(self, limit: int = 60) -> list[dict]:
        """
        Get next batch of unprocessed accounts for worker.
        Returns accounts ordered by ID that haven't been processed yet.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM accounts
                WHERE status = 'active' AND (worker_batch_processed = 0 OR worker_batch_processed IS NULL)
                ORDER BY id ASC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_all_accounts_ordered(self) -> list[dict]:
        """
        Get all active accounts ordered by ID for worker display.
        Includes worker_batch_processed status.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM accounts
                WHERE status = 'active'
                ORDER BY id ASC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_account_worker_processed(self, account_id: int) -> bool:
        """Mark a single account as processed by worker batch."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE accounts SET worker_batch_processed = 1 WHERE id = ?",
                (account_id,)
            )
            return cursor.rowcount > 0

    def reset_worker_batch_processed(self) -> int:
        """Reset all accounts' worker_batch_processed status to 0. Returns count of reset accounts."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "UPDATE accounts SET worker_batch_processed = 0 WHERE status = 'active'"
            )
            return cursor.rowcount

    def get_worker_batch_stats(self) -> dict:
        """Get statistics about worker batch processing."""
        with self._get_conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM accounts WHERE status = 'active'"
            ).fetchone()[0]

            processed = conn.execute(
                "SELECT COUNT(*) FROM accounts WHERE status = 'active' AND worker_batch_processed = 1"
            ).fetchone()[0]

            return {
                "total_active": total,
                "processed": processed,
                "remaining": total - processed,
                "progress_percent": round((processed / total * 100) if total > 0 else 0, 1)
            }

    # Joined subreddits operations
    def add_joined_subreddit(self, account_id: int, subreddit_name: str) -> bool:
        """Record that an account has joined a subreddit."""
        # Normalize subreddit name (remove r/ prefix if present, lowercase)
        subreddit_name = subreddit_name.lower().replace("r/", "").strip()

        with self._get_conn() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO joined_subreddits (account_id, subreddit_name)
                    VALUES (?, ?)
                    """,
                    (account_id, subreddit_name),
                )
                return True
            except sqlite3.IntegrityError:
                # Already joined
                return False

    def has_joined_subreddit(self, account_id: int, subreddit_name: str) -> bool:
        """Check if an account has already joined a subreddit."""
        # Normalize subreddit name
        subreddit_name = subreddit_name.lower().replace("r/", "").strip()

        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM joined_subreddits
                WHERE account_id = ? AND subreddit_name = ?
                """,
                (account_id, subreddit_name),
            ).fetchone()
            return row is not None

    def get_joined_subreddits(self, account_id: int) -> list[str]:
        """Get list of subreddits an account has joined."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT subreddit_name FROM joined_subreddits
                WHERE account_id = ?
                ORDER BY joined_at DESC
                """,
                (account_id,),
            ).fetchall()
            return [row[0] for row in rows]

    # Stats
    def get_stats(self) -> dict:
        with self._get_conn() as conn:
            stats = {}

            # Account stats
            row = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()
            stats["total_accounts"] = row[0]

            row = conn.execute(
                "SELECT COUNT(*) FROM accounts WHERE status = 'active'"
            ).fetchone()
            stats["active_accounts"] = row[0]

            row = conn.execute(
                "SELECT COUNT(*) FROM accounts WHERE status IN ('suspended', 'banned')"
            ).fetchone()
            stats["banned_accounts"] = row[0]

            row = conn.execute(
                "SELECT COUNT(*) FROM accounts WHERE status = 'shadowbanned'"
            ).fetchone()
            stats["shadowbanned_accounts"] = row[0]

            # Action stats
            row = conn.execute(
                """
                SELECT COUNT(*) FROM action_logs
                WHERE action_type = 'upvote' AND status = 'success'
                AND executed_at > datetime('now', '-7 days')
                """
            ).fetchone()
            stats["upvotes_last_week"] = row[0]

            row = conn.execute(
                """
                SELECT COUNT(*) FROM action_logs
                WHERE action_type = 'upvote' AND status = 'failed'
                AND executed_at > datetime('now', '-7 days')
                """
            ).fetchone()
            stats["failed_upvotes_last_week"] = row[0]

            return stats
