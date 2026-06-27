"""
boltdown -- aria2c process lifecycle and JSON-RPC wrapper
Uses only stdlib (urllib) -- no `requests` dependency.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Optional

from .exceptions import Aria2NotFoundError, Aria2RpcError

logger = logging.getLogger(__name__)

_DEFAULT_PORT   = 6800
_DEFAULT_SECRET = ""
_STARTUP_WAIT   = 2.0   # seconds to wait for aria2c to bind its RPC port


def find_aria2c(hint_dirs: list[str] | None = None) -> str:
    """
    Locate the aria2c binary.

    Search order:
      1. Each directory in *hint_dirs* (e.g., the caller's working directory).
      2. The system PATH via ``shutil.which``.

    Returns the resolved path string.
    Raises :exc:`~boltdown.exceptions.Aria2NotFoundError` if not found.
    """
    import shutil

    candidates: list[str] = []

    # 1 -- caller-supplied hints
    for d in (hint_dirs or []):
        for name in ("aria2c.exe", "aria2c"):
            candidates.append(os.path.join(d, name))

    # 2 -- PATH
    for name in ("aria2c.exe", "aria2c"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    for path in candidates:
        if os.path.isfile(path):
            return path

    raise Aria2NotFoundError(
        "aria2c binary not found. "
        "Download from https://github.com/aria2/aria2/releases and add it to PATH "
        "or pass aria2c_path= to BoltdownClient."
    )


class Aria2Rpc:
    """
    Thin wrapper around the aria2 JSON-RPC interface.

    Parameters
    ----------
    port   : RPC listen port (default 6800).
    secret : RPC secret token.
    """

    def __init__(self, port: int = _DEFAULT_PORT, secret: str = _DEFAULT_SECRET) -> None:
        self._url    = f"http://127.0.0.1:{port}/jsonrpc"
        self._secret = secret
        self._seq    = 0
        self._seq_lock = threading.Lock()  # guard concurrent increments

    # -- Low-level call ────────────────────────────────────────────────────────

    def call(self, method: str, params: list | None = None) -> Any:
        """
        Invoke an aria2 RPC method.

        Returns the ``result`` value on success.
        Raises :exc:`~boltdown.exceptions.Aria2RpcError` on aria2-level errors.
        Returns ``None`` on network / connection errors (aria2 may not be up yet).
        """
        with self._seq_lock:
            self._seq += 1
            seq = self._seq
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id":      str(seq),
            "method":  method,
            "params":  ([f"token:{self._secret}"] if self._secret else []) + (params or []),
        }).encode()

        req = urllib.request.Request(
            self._url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read())
        except urllib.error.URLError as exc:
            logger.debug("aria2 RPC unreachable (%s): %s", method, exc)
            return None

        if "error" in body:
            raise Aria2RpcError(
                f"aria2 RPC error [{method}]: {body['error'].get('message', body['error'])}"
            )
        return body.get("result")

    # -- Convenience wrappers ──────────────────────────────────────────────────

    def add_uri(self, uris: list[str]) -> Optional[str]:
        """Add download by URI (e.g. magnet link). Returns GID or None."""
        return self.call("aria2.addUri", [uris])

    def add_torrent(self, torrent_b64: str) -> Optional[str]:
        """Add .torrent file (base64-encoded). Returns GID or None."""
        return self.call("aria2.addTorrent", [torrent_b64])

    def pause(self, gid: str) -> bool:
        result = self.call("aria2.pause", [gid])
        return result == gid

    def unpause(self, gid: str) -> bool:
        result = self.call("aria2.unpause", [gid])
        return result == gid

    def remove(self, gid: str) -> bool:
        result = self.call("aria2.remove", [gid])
        return result == gid

    def tell_active(self) -> list[dict]:
        return self.call("aria2.tellActive") or []

    def tell_waiting(self, offset: int = 0, num: int = 100) -> list[dict]:
        return self.call("aria2.tellWaiting", [offset, num]) or []

    def tell_stopped(self, offset: int = 0, num: int = 100) -> list[dict]:
        return self.call("aria2.tellStopped", [offset, num]) or []

    def shutdown(self) -> None:
        self.call("aria2.shutdown")

    def is_alive(self) -> bool:
        """Return True if the aria2 RPC server is responding."""
        try:
            result = self.call("aria2.getVersion")
            return result is not None
        except Exception:
            return False


class Aria2Process:
    """
    Manages the lifecycle of a locally-spawned aria2c process.

    Parameters
    ----------
    binary     : Full path to the aria2c executable.
    download_dir : Directory where files are saved.
    port       : RPC listen port.
    secret     : RPC token.
    extra_args : Additional command-line args forwarded to aria2c.
    """

    def __init__(
        self,
        binary: str,
        download_dir: str,
        port: int = _DEFAULT_PORT,
        secret: str = _DEFAULT_SECRET,
        extra_args: list[str] | None = None,
    ) -> None:
        self._binary       = binary
        self._download_dir = download_dir
        self._port         = port
        self._secret       = secret
        self._extra_args   = extra_args or []
        self._process: Optional[subprocess.Popen] = None

    def start(self) -> None:
        """Launch aria2c in RPC daemon mode."""
        os.makedirs(self._download_dir, exist_ok=True)

        cmd = [
            self._binary,
            "--enable-rpc",
            f"--rpc-listen-port={self._port}",
            "--rpc-listen-all=false",
            f"--dir={self._download_dir}",
            "--max-connection-per-server=16",
            "--min-split-size=1M",
            "--split=16",
            "--continue=true",
            "--seed-time=0",
            "--bt-max-peers=50",
            "--quiet=true",
        ]
        if self._secret:
            cmd.append(f"--rpc-secret={self._secret}")

        cmd.extend(self._extra_args)

        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        time.sleep(_STARTUP_WAIT)
        logger.info("aria2c started (PID %s) on port %s.", self._process.pid, self._port)

    def stop(self, rpc: "Aria2Rpc | None" = None) -> None:
        """Gracefully shut down aria2c."""
        if rpc:
            try:
                rpc.shutdown()
            except Exception:
                pass
        if self._process and self._process.poll() is None:
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.terminate()
            logger.info("aria2c process stopped.")

    @property
    def pid(self) -> Optional[int]:
        return self._process.pid if self._process else None

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None
