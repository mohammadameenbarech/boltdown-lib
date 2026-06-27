"""
boltdown -- Lightning-fast torrent download manager for Python.

Public API surface::

    from boltdown import BoltdownClient, DownloadTask
    from boltdown.exceptions import (
        BoltdownError, Aria2NotFoundError, Aria2RpcError,
        InvalidMagnetError, TaskNotFoundError, StorageError,
    )

Basic usage::

    with BoltdownClient(download_dir="./downloads") as client:
        task = client.add_magnet("magnet:?xt=urn:btih:...")
        print(task.status)  # 'downloading'

        tasks = client.list_tasks()
        client.pause(task.id)
        client.resume(task.id)
        client.remove(task.id, delete_files=False)
"""

from ._version import __version__
from .client import BoltdownClient
from .exceptions import (
    Aria2NotFoundError,
    Aria2RpcError,
    BoltdownError,
    InvalidMagnetError,
    StorageError,
    TaskNotFoundError,
)
from .models import DownloadTask

__all__ = [
    "__version__",
    "BoltdownClient",
    "DownloadTask",
    # Exceptions
    "BoltdownError",
    "Aria2NotFoundError",
    "Aria2RpcError",
    "InvalidMagnetError",
    "TaskNotFoundError",
    "StorageError",
]
