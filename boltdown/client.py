"""
boltdown -- BoltdownClient
Main entry point for the library. No Django / ORM / external HTTP dependencies.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

from . import magnet as _magnet
from .aria2 import Aria2Process, Aria2Rpc, find_aria2c
from .exceptions import (
    Aria2NotFoundError,
    Aria2RpcError,
    InvalidMagnetError,
    TaskNotFoundError,
)
from .models import DownloadTask
from .storage import Storage

logger = logging.getLogger(__name__)


class BoltdownClient:
    """
    High-level torrent download manager.

    Manages the aria2c daemon, persists state to SQLite, and provides a clean
    Python API for adding, pausing, resuming, and removing downloads.

    Parameters
    ----------
    download_dir : Directory where files will be saved. Created if absent.
    db_path      : Path to the SQLite database. Defaults to ``boltdown.db``
                   inside *download_dir*.
    aria2c_path  : Explicit path to the aria2c binary. If ``None``, the
                   library searches common locations automatically.
    aria2_secret : RPC secret token. Defaults to empty (no auth).
    rpc_port     : aria2c RPC port. Defaults to 6800.
    auto_start   : If ``True`` (default), launches aria2c automatically on
                   instantiation.
    monitor_interval : Seconds between status-sync polls. Defaults to 2.
    extra_aria2_args : Additional CLI arguments forwarded to aria2c.

    Examples
    --------
    >>> from boltdown import BoltdownClient
    >>> client = BoltdownClient(download_dir="./downloads")
    >>> task = client.add_magnet("magnet:?xt=urn:btih:...")
    >>> print(task.status)
    'downloading'
    >>> client.shutdown()
    """

    def __init__(
        self,
        download_dir: str | Path = "./downloads",
        db_path: str | Path | None = None,
        aria2c_path: str | None = None,
        aria2_secret: str = "",
        rpc_port: int = 6800,
        auto_start: bool = True,
        monitor_interval: float = 2.0,
        extra_aria2_args: list[str] | None = None,
    ) -> None:
        self._download_dir  = str(Path(download_dir).resolve())
        self._secret        = aria2_secret
        self._port          = rpc_port
        self._monitor_interval = monitor_interval

        # Resolve aria2c binary
        binary = aria2c_path or find_aria2c(hint_dirs=[os.getcwd(), self._download_dir])
        self._aria2_proc = Aria2Process(
            binary=binary,
            download_dir=self._download_dir,
            port=rpc_port,
            secret=aria2_secret,
            extra_args=extra_aria2_args,
        )
        self._rpc = Aria2Rpc(port=rpc_port, secret=aria2_secret)

        # Storage
        _db = db_path or os.path.join(self._download_dir, "boltdown.db")
        self._storage = Storage(_db)

        # GID lookup cache: info_hash -> GID
        self._gid_cache: dict[str, str] = {}
        self._gid_lock = threading.Lock()

        # Monitoring thread
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None

        if auto_start:
            self.start()

    # -- Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Launch aria2c and begin background monitoring."""
        self._aria2_proc.start()
        self._start_monitoring()
        logger.info("BoltdownClient ready. Download dir: %s", self._download_dir)

    def shutdown(self) -> None:
        """Stop monitoring and gracefully terminate aria2c."""
        self._stop_monitoring()
        self._aria2_proc.stop(rpc=self._rpc)
        self._storage.close()
        logger.info("BoltdownClient shut down.")

    # -- Add downloads ─────────────────────────────────────────────────────────

    def add_magnet(self, magnet_link: str) -> DownloadTask:
        """
        Add a magnet link and start downloading.

        Parameters
        ----------
        magnet_link : A ``magnet:?xt=urn:btih:...`` URI string.

        Returns
        -------
        DownloadTask

        Raises
        ------
        InvalidMagnetError  : If the magnet link is malformed.
        Aria2RpcError       : If aria2 rejects the request.
        """
        _magnet.validate(magnet_link)

        gid = self._rpc.add_uri([magnet_link])
        if not gid:
            raise Aria2RpcError("aria2 did not return a GID for the magnet link.")

        info_hash = _magnet.extract_hash(magnet_link) or gid
        name      = _magnet.extract_name(magnet_link) or f"Download_{info_hash[:8]}"

        task = DownloadTask(
            info_hash=info_hash,
            name=name,
            save_path=self._download_dir,
            status="downloading",
            gid=gid,
        )
        task = self._storage.insert(task)

        with self._gid_lock:
            self._gid_cache[info_hash] = gid

        logger.info("Added magnet '%s' -> GID %s.", name, gid)
        return task

    def add_torrent_file(self, path: str | Path) -> DownloadTask:
        """
        Add a ``.torrent`` file and start downloading.

        Parameters
        ----------
        path : Absolute or relative path to a ``.torrent`` file.

        Returns
        -------
        DownloadTask

        Raises
        ------
        FileNotFoundError   : If the file does not exist.
        Aria2RpcError       : If aria2 rejects the torrent.
        ImportError         : If ``bencodepy`` is not installed
                              (install with: ``pip install boltdown[torrent]``).
        """
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Torrent file not found: {path}")

        # Guard against loading arbitrarily large files into memory.
        # Real .torrent files are typically <1 MB; 100 MB is extremely generous.
        _MAX_TORRENT_BYTES = 100 * 1024 * 1024  # 100 MB
        file_size = path.stat().st_size
        if file_size > _MAX_TORRENT_BYTES:
            raise ValueError(
                f"Torrent file is too large ({file_size:,} bytes). "
                f"Maximum allowed is {_MAX_TORRENT_BYTES:,} bytes."
            )

        try:
            import bencodepy  # optional extra
        except ImportError as exc:
            raise ImportError(
                "bencodepy is required for .torrent file support. "
                "Install it with: pip install boltdown[torrent]"
            ) from exc

        raw  = path.read_bytes()
        b64  = base64.b64encode(raw).decode()
        gid  = self._rpc.add_torrent(b64)
        if not gid:
            raise Aria2RpcError("aria2 did not return a GID for the torrent file.")

        # Parse metadata
        data  = bencodepy.decode(raw)
        info  = data[b"info"]
        info_hash = hashlib.sha1(bencodepy.encode(info)).hexdigest()
        name      = info.get(b"name", b"Unknown").decode("utf-8", errors="ignore")

        task = DownloadTask(
            info_hash=info_hash,
            name=name,
            save_path=self._download_dir,
            status="downloading",
            gid=gid,
        )
        task = self._storage.insert(task)

        with self._gid_lock:
            self._gid_cache[info_hash] = gid

        logger.info("Added torrent '%s' -> GID %s.", name, gid)
        return task

    # -- Control ───────────────────────────────────────────────────────────────

    def pause(self, task_id: int) -> bool:
        """
        Pause a download.

        Returns ``True`` if aria2 confirmed the pause, ``False`` otherwise.
        Raises :exc:`TaskNotFoundError` if the ID doesn't exist.
        """
        task = self._storage.get_by_id(task_id)
        gid  = self._resolve_gid(task)
        if not gid:
            logger.warning("pause: cannot find GID for task %s.", task_id)
            return False

        ok = self._rpc.pause(gid)
        if ok:
            task.status = "paused"
            self._storage.update(task)
        return ok

    def resume(self, task_id: int) -> bool:
        """
        Resume a paused download.

        Returns ``True`` if aria2 confirmed the resume, ``False`` otherwise.
        Raises :exc:`TaskNotFoundError` if the ID doesn't exist.
        """
        task = self._storage.get_by_id(task_id)
        gid  = self._resolve_gid(task)
        if not gid:
            logger.warning("resume: cannot find GID for task %s.", task_id)
            return False

        ok = self._rpc.unpause(gid)
        if ok:
            task.status = "downloading"
            self._storage.update(task)
        return ok

    def remove(self, task_id: int, delete_files: bool = False) -> None:
        """
        Remove a download from aria2 and the local database.

        Parameters
        ----------
        task_id      : ID of the task to remove.
        delete_files : If ``True``, also delete the downloaded files from disk.

        Raises
        ------
        TaskNotFoundError : If the ID doesn't exist.
        """
        # Capture name & path BEFORE deleting the DB row
        task = self._storage.get_by_id(task_id)
        saved_name = task.name
        saved_path = task.save_path

        gid = self._resolve_gid(task)
        if gid:
            self._rpc.remove(gid)
            with self._gid_lock:
                self._gid_cache.pop(task.info_hash, None)

        self._storage.delete(task_id)
        logger.info("Removed task %s ('%s').", task_id, saved_name)

        if delete_files:
            import shutil
            target = os.path.join(saved_path, saved_name)
            if os.path.exists(target):
                try:
                    if os.path.isfile(target):
                        os.remove(target)
                    else:
                        shutil.rmtree(target)
                    logger.info("Deleted files: %s", target)
                except OSError as exc:
                    logger.error("Could not delete %s: %s", target, exc)

    # -- Query ─────────────────────────────────────────────────────────────────

    def get_task(self, task_id: int) -> DownloadTask:
        """Return the task with *task_id*. Raises :exc:`TaskNotFoundError` if not found."""
        return self._storage.get_by_id(task_id)

    def list_tasks(self) -> list[DownloadTask]:
        """Return all tasks ordered by ID."""
        return self._storage.list_all()

    # -- Monitoring ────────────────────────────────────────────────────────────

    def _start_monitoring(self) -> None:
        if not self._monitoring:
            self._monitoring = True
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                daemon=True,
                name="boltdown-monitor",
            )
            self._monitor_thread.start()

    def _stop_monitoring(self) -> None:
        self._monitoring = False

    def _monitor_loop(self) -> None:
        while self._monitoring:
            try:
                self._sync_all()
            except Exception as exc:
                logger.debug("Monitor error: %s", exc)
            time.sleep(self._monitor_interval)

    def _sync_all(self) -> None:
        """Fetch all download statuses from aria2 and sync to storage."""
        all_downloads = (
            self._rpc.tell_active()
            + self._rpc.tell_waiting()
            + self._rpc.tell_stopped()
        )
        for dl in all_downloads:
            self._sync_one(dl)

    def _sync_one(self, dl: dict) -> None:
        info_hash: str = dl.get("infoHash", "").lower()
        if not info_hash:
            return

        task = self._storage.get_by_hash(info_hash)
        if not task:
            return

        total     = int(dl.get("totalLength", 0))
        completed = int(dl.get("completedLength", 0))

        if total > 0:
            task.progress   = round((completed / total) * 100, 2)
            task.total_size = total

        task.download_speed = int(dl.get("downloadSpeed", 0))
        task.upload_speed   = int(dl.get("uploadSpeed", 0))

        if task.download_speed > 0 and total > completed:
            task.eta = int((total - completed) / task.download_speed)
        else:
            task.eta = 0

        aria2_status = dl.get("status", "active")
        if aria2_status == "complete":
            task.status       = "completed"
            task.progress     = 100.0
            task.completed_at = task.completed_at or datetime.datetime.now(datetime.timezone.utc)
        elif aria2_status == "paused":
            task.status = "paused"
        elif aria2_status == "error":
            task.status        = "error"
            task.error_message = dl.get("errorMessage", "Unknown aria2 error")
        elif task.status not in ("paused", "completed", "error"):
            task.status = "downloading"

        # Resolve name from bittorrent metadata
        if task.name.startswith("Download_"):
            bt_name = dl.get("bittorrent", {}).get("info", {}).get("name")
            if bt_name:
                task.name = bt_name

        # Keep GID cache warm
        gid = dl.get("gid")
        if gid:
            task.gid = gid
            with self._gid_lock:
                self._gid_cache[info_hash] = gid

        self._storage.update(task)

    # -- GID resolution ────────────────────────────────────────────────────────

    def _resolve_gid(self, task: DownloadTask) -> Optional[str]:
        """
        Return the aria2 GID for *task*.

        Checks the in-memory cache first, then falls back to scanning aria2.
        """
        with self._gid_lock:
            gid = self._gid_cache.get(task.info_hash) or task.gid
        if gid:
            return gid

        # Fallback scan
        for dl in (
            self._rpc.tell_active()
            + self._rpc.tell_waiting()
            + self._rpc.tell_stopped()
        ):
            if dl.get("infoHash", "").lower() == task.info_hash.lower():
                found = dl["gid"]
                with self._gid_lock:
                    self._gid_cache[task.info_hash] = found
                return found

        return None

    # -- Context manager support ───────────────────────────────────────────────

    def __enter__(self) -> "BoltdownClient":
        return self

    def __exit__(self, *_) -> None:
        self.shutdown()

    def __repr__(self) -> str:
        status = "running" if self._aria2_proc.is_running() else "stopped"
        return f"<BoltdownClient dir={self._download_dir!r} aria2c={status}>"
