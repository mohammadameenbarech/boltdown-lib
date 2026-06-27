"""
boltdown -- SQLite state persistence layer (stdlib only, no Django / ORM)
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from .exceptions import StorageError, TaskNotFoundError
from .models import DownloadTask

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS download_tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    info_hash       TEXT    NOT NULL UNIQUE,
    name            TEXT    NOT NULL DEFAULT '',
    status          TEXT    NOT NULL DEFAULT 'queued',
    progress        REAL    NOT NULL DEFAULT 0.0,
    download_speed  INTEGER NOT NULL DEFAULT 0,
    upload_speed    INTEGER NOT NULL DEFAULT 0,
    total_size      INTEGER NOT NULL DEFAULT 0,
    eta             INTEGER NOT NULL DEFAULT 0,
    save_path       TEXT    NOT NULL DEFAULT '',
    added_at        TEXT    NOT NULL,
    completed_at    TEXT,
    error_message   TEXT,
    gid             TEXT
);
"""


class Storage:
    """
    Thread-safe SQLite storage for :class:`~boltdown.models.DownloadTask` objects.

    Parameters
    ----------
    db_path : str | Path
        Path to the SQLite database file.
        Pass ``':memory:'`` for an in-process, ephemeral store (useful for testing).
    """

    def __init__(self, db_path: str | Path = "boltdown.db") -> None:
        self._db_path = str(db_path)
        self._local = threading.local()  # per-thread Connection
        self._lock = threading.Lock()
        self._init_schema()

    # -- Connection management ─────────────────────────────────────────────────

    @property
    def _conn(self) -> sqlite3.Connection:
        """Return a thread-local SQLite connection, creating it if needed."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            self._local.conn = conn
        return conn

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception as exc:
                self._conn.rollback()
                raise StorageError(f"Database error: {exc}") from exc

    def _init_schema(self) -> None:
        with self._transaction() as cur:
            cur.executescript(_SCHEMA)

    # -- CRUD ──────────────────────────────────────────────────────────────────

    def insert(self, task: DownloadTask) -> DownloadTask:
        """Persist a new task and return it with ``id`` set."""
        with self._transaction() as cur:
            cur.execute(
                """
                INSERT INTO download_tasks
                    (info_hash, name, status, progress, download_speed, upload_speed,
                     total_size, eta, save_path, added_at, completed_at, error_message, gid)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(info_hash) DO NOTHING
                """,
                (
                    task.info_hash, task.name, task.status, task.progress,
                    task.download_speed, task.upload_speed, task.total_size,
                    task.eta, task.save_path,
                    _dt_to_str(task.added_at),
                    _dt_to_str(task.completed_at),
                    task.error_message,
                    task.gid,
                ),
            )
            if cur.lastrowid:
                task.id = cur.lastrowid
            else:
                # Conflict -- fetch existing row id
                row = cur.execute(
                    "SELECT id FROM download_tasks WHERE info_hash = ?", (task.info_hash,)
                ).fetchone()
                if row:
                    task.id = row["id"]
        return task

    def update(self, task: DownloadTask) -> None:
        """Update all mutable fields for an existing task."""
        with self._transaction() as cur:
            cur.execute(
                """
                UPDATE download_tasks
                SET  name = ?, status = ?, progress = ?, download_speed = ?,
                     upload_speed = ?, total_size = ?, eta = ?,
                     completed_at = ?, error_message = ?, gid = ?
                WHERE id = ?
                """,
                (
                    task.name, task.status, task.progress, task.download_speed,
                    task.upload_speed, task.total_size, task.eta,
                    _dt_to_str(task.completed_at), task.error_message, task.gid,
                    task.id,
                ),
            )

    def get_by_id(self, task_id: int) -> DownloadTask:
        row = self._conn.execute(
            "SELECT * FROM download_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            raise TaskNotFoundError(f"No task with id={task_id}.")
        return _row_to_task(row)

    def get_by_hash(self, info_hash: str) -> Optional[DownloadTask]:
        row = self._conn.execute(
            "SELECT * FROM download_tasks WHERE info_hash = ?", (info_hash.lower(),)
        ).fetchone()
        return _row_to_task(row) if row else None

    def list_all(self) -> list[DownloadTask]:
        rows = self._conn.execute(
            "SELECT * FROM download_tasks ORDER BY id ASC"
        ).fetchall()
        return [_row_to_task(r) for r in rows]

    def delete(self, task_id: int) -> None:
        with self._transaction() as cur:
            cur.execute("DELETE FROM download_tasks WHERE id = ?", (task_id,))

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn:
            conn.close()
            self._local.conn = None


# -- Helpers ───────────────────────────────────────────────────────────────────

def _dt_to_str(dt: Optional[datetime.datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _str_to_dt(s: Optional[str]) -> Optional[datetime.datetime]:
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s)
    except ValueError:
        return None


def _row_to_task(row: sqlite3.Row) -> DownloadTask:
    return DownloadTask(
        id=row["id"],
        info_hash=row["info_hash"],
        name=row["name"],
        status=row["status"],
        progress=row["progress"],
        download_speed=row["download_speed"],
        upload_speed=row["upload_speed"],
        total_size=row["total_size"],
        eta=row["eta"],
        save_path=row["save_path"],
        added_at=_str_to_dt(row["added_at"]) or datetime.datetime.now(datetime.timezone.utc),
        completed_at=_str_to_dt(row["completed_at"]),
        error_message=row["error_message"],
        gid=row["gid"],
    )
