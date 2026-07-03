import sqlite3
from pathlib import Path


class Database:
    def __init__(self, db_path: Path = Path("pr_triage.db")):
        self.db_path = db_path
        self.conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        raise NotImplementedError("Phase 1")

    def close(self) -> None:
        raise NotImplementedError("Phase 1")
