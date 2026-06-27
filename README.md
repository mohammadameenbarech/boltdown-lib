# boltdown

A Python library for managing torrent downloads, powered by [aria2c](https://aria2.github.io/).

[![PyPI](https://img.shields.io/pypi/v/boltdown.svg)](https://pypi.org/project/boltdown/)
[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://pypi.org/project/boltdown/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**boltdown** wraps `aria2c` via JSON-RPC to provide a clean, dependency-free Python API for
torrent and magnet link downloads. No Django. No heavy HTTP frameworks. Just Python and aria2c.

---

## Features

- **Zero external HTTP dependencies** — uses stdlib `urllib` only
- **Magnet links** — full validation, hash extraction, DHT support
- **.torrent files** — optional `bencodepy` extra
- **SQLite state** — stdlib `sqlite3`, no ORM required
- **Background monitoring** — auto-syncs progress from aria2c
- **Typed and documented** — full type hints, Python 3.9+
- **PyPI-ready** — `pip install boltdown`

---

## Quick Start

### 1. Install

```bash
pip install boltdown
# For .torrent file support:
pip install boltdown[torrent]
```

### 2. Download a Magnet Link

```python
from boltdown import BoltdownClient

with BoltdownClient(download_dir="./downloads") as client:
    task = client.add_magnet("magnet:?xt=urn:btih:...")
    print(task)
    # <DownloadTask id=1 name='My File' status='downloading' progress=0.0%>
```

### 3. Download a .torrent File

```python
from boltdown import BoltdownClient

with BoltdownClient(download_dir="./downloads") as client:
    task = client.add_torrent_file("/path/to/file.torrent")
```

### 4. Manage Downloads

```python
client = BoltdownClient(download_dir="./downloads")

# List all tasks
tasks = client.list_tasks()
for t in tasks:
    print(t.to_dict())

# Pause and resume
client.pause(task.id)
client.resume(task.id)

# Remove (and optionally delete files from disk)
client.remove(task.id, delete_files=True)

# Always shut down cleanly
client.shutdown()
```

---

## Configuration

```python
client = BoltdownClient(
    download_dir     = "./downloads",   # Directory where files are saved
    db_path          = "./boltdown.db", # SQLite database (default: inside download_dir)
    aria2c_path      = None,            # Auto-detect, or pass "/usr/bin/aria2c"
    aria2_secret     = "mysecret",      # aria2 RPC token (optional but recommended)
    rpc_port         = 6800,            # aria2 RPC listen port
    monitor_interval = 2.0,             # Seconds between status sync polls
)
```

### Prerequisites

- Python 3.9 or later
- `aria2c` available on your PATH, or placed in your working directory
  - **Windows**: [Download from the aria2 GitHub releases page](https://github.com/aria2/aria2/releases)
  - **Linux**: `sudo apt install aria2`
  - **macOS**: `brew install aria2`

---

## API Reference

### BoltdownClient

| Method | Returns | Description |
|--------|---------|-------------|
| `add_magnet(magnet_link)` | `DownloadTask` | Add a magnet URI and start downloading |
| `add_torrent_file(path)` | `DownloadTask` | Add a `.torrent` file and start downloading |
| `pause(task_id)` | `bool` | Pause a download |
| `resume(task_id)` | `bool` | Resume a paused download |
| `remove(task_id, delete_files=False)` | `None` | Remove a download, optionally deleting files |
| `get_task(task_id)` | `DownloadTask` | Retrieve a single task by ID |
| `list_tasks()` | `list[DownloadTask]` | List all tasks, ordered by ID |
| `shutdown()` | `None` | Stop monitoring and terminate aria2c |

### DownloadTask

| Field | Type | Description |
|-------|------|-------------|
| `id` | `int` | Auto-assigned integer ID |
| `info_hash` | `str` | 40-character hex SHA-1 info hash |
| `name` | `str` | Display name |
| `status` | `str` | One of: `queued`, `downloading`, `paused`, `completed`, `error` |
| `progress` | `float` | Completion percentage (0.0 to 100.0) |
| `download_speed` | `int` | Current download speed in bytes per second |
| `upload_speed` | `int` | Current upload speed in bytes per second |
| `total_size` | `int` | Total file size in bytes |
| `eta` | `int` | Estimated seconds remaining |
| `save_path` | `str` | Directory where files are saved |
| `added_at` | `datetime` | UTC datetime when the task was created |
| `completed_at` | `datetime or None` | UTC datetime when the download finished |
| `error_message` | `str or None` | Description of the last error, if any |

### Exceptions

| Exception | When raised |
|-----------|-------------|
| `BoltdownError` | Base class for all library errors |
| `Aria2NotFoundError` | The aria2c binary could not be located |
| `Aria2RpcError` | aria2 returned an error or refused the RPC call |
| `InvalidMagnetError` | The supplied string is not a valid magnet link |
| `TaskNotFoundError` | No task exists with the given ID |
| `StorageError` | A database or persistence error occurred |

---

## Architecture

```
boltdown/
    client.py      BoltdownClient — main entry point
    aria2.py       aria2c process management and JSON-RPC client (stdlib urllib)
    storage.py     SQLite state persistence (stdlib sqlite3)
    models.py      DownloadTask dataclass
    magnet.py      Magnet URI parsing utilities
    exceptions.py  Custom exception hierarchy
    _version.py    Version string
```

---

## Running Tests

```bash
cd boltdown-lib
pip install -e ".[dev]"
pytest
```

---

## Publishing to PyPI

```bash
pip install build twine
python -m build
twine upload dist/*
```

To test on TestPyPI first:

```bash
twine upload --repository testpypi dist/*
pip install --index-url https://test.pypi.org/simple/ boltdown
```

---

## License

MIT — see [LICENSE](LICENSE).

---

By Mohammad Ameen Barech
