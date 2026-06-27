"""
boltdown -- exceptions module
"""


class BoltdownError(Exception):
    """Base exception for all boltdown errors."""


class Aria2NotFoundError(BoltdownError):
    """aria2c binary could not be located."""


class Aria2RpcError(BoltdownError):
    """An aria2 JSON-RPC call returned an error or failed to connect."""


class InvalidMagnetError(BoltdownError):
    """The supplied string is not a valid magnet link."""


class TaskNotFoundError(BoltdownError):
    """No download task exists with the given ID or info_hash."""


class StorageError(BoltdownError):
    """A database / persistence error occurred."""
