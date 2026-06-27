"""
boltdown -- pure-Python data models (no Django / ORM dependency)
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DownloadTask:
    """
    Represents a single torrent / magnet download task.

    Attributes
    ----------
    id          : Auto-assigned integer primary key (storage layer sets this).
    info_hash   : 40-char hex SHA-1 info hash (or aria2 GID if hash unavailable).
    name        : Human-readable display name.
    status      : One of: queued, downloading, paused, completed, error.
    progress    : Float 0.0–100.0 (percentage).
    download_speed : Bytes per second.
    upload_speed   : Bytes per second.
    total_size     : Total size in bytes (0 until known).
    eta            : Estimated seconds remaining (0 if unknown).
    save_path      : Absolute directory where files are saved.
    added_at       : UTC datetime when the task was created.
    completed_at   : UTC datetime when download finished (None if not yet).
    error_message  : Description of the last error (None if none).
    gid            : aria2 GID string (internal, may be None).
    """

    info_hash: str
    name: str
    save_path: str

    id: int = 0
    status: str = "queued"
    progress: float = 0.0
    download_speed: int = 0
    upload_speed: int = 0
    total_size: int = 0
    eta: int = 0
    added_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    completed_at: Optional[datetime.datetime] = None
    error_message: Optional[str] = None
    gid: Optional[str] = None  # aria2 internal GID

    def __str__(self) -> str:
        return f"<DownloadTask id={self.id} name={self.name!r} status={self.status} progress={self.progress:.1f}%>"

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dictionary of this task."""
        return {
            "id": self.id,
            "info_hash": self.info_hash,
            "name": self.name,
            "status": self.status,
            "progress": round(self.progress, 2),
            "download_speed": self.download_speed,
            "upload_speed": self.upload_speed,
            "total_size": self.total_size,
            "eta": self.eta,
            "save_path": self.save_path,
            "added_at": self.added_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
        }
