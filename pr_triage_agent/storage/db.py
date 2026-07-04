import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class Database:
    def __init__(self, db_path: Path = Path("pr_triage.db")):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def _create_tables(self) -> None:
        cur = self.conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS cost_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS review_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pr_url TEXT NOT NULL,
                risk_rating TEXT,
                confidence REAL,
                review_text TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        self.conn.commit()

    def log_cost(
        self,
        model: str,
        endpoint: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        estimated_cost_usd: float,
    ) -> None:
        if not self.conn:
            raise RuntimeError("Database not connected")
        self.conn.execute(
            """
            INSERT INTO cost_log
                (model, endpoint, prompt_tokens, completion_tokens,
                 total_tokens, estimated_cost_usd, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model,
                endpoint,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                estimated_cost_usd,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()
