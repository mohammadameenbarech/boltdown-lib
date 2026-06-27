"""Tests for boltdown.storage (uses in-memory SQLite)."""

import datetime
import pytest

from boltdown.storage import Storage
from boltdown.models import DownloadTask
from boltdown.exceptions import TaskNotFoundError, StorageError


@pytest.fixture
def store():
    s = Storage(":memory:")
    yield s
    s.close()


def _make_task(**kwargs) -> DownloadTask:
    defaults = dict(
        info_hash="a" * 40,
        name="Test Torrent",
        save_path="/tmp/downloads",
    )
    defaults.update(kwargs)
    return DownloadTask(**defaults)


class TestInsert:
    def test_insert_sets_id(self, store):
        task = _make_task()
        result = store.insert(task)
        assert result.id > 0

    def test_duplicate_insert_is_idempotent(self, store):
        t1 = store.insert(_make_task(info_hash="b" * 40, name="First"))
        t2 = store.insert(_make_task(info_hash="b" * 40, name="Second"))
        assert t1.id == t2.id  # same row, no error


class TestGetById:
    def test_retrieves_correct_task(self, store):
        task = store.insert(_make_task(name="My Torrent"))
        fetched = store.get_by_id(task.id)
        assert fetched.name == "My Torrent"

    def test_raises_for_missing_id(self, store):
        with pytest.raises(TaskNotFoundError):
            store.get_by_id(9999)


class TestGetByHash:
    def test_returns_task(self, store):
        task = store.insert(_make_task(info_hash="c" * 40))
        found = store.get_by_hash("c" * 40)
        assert found is not None
        assert found.id == task.id

    def test_returns_none_if_missing(self, store):
        assert store.get_by_hash("d" * 40) is None


class TestUpdate:
    def test_update_status(self, store):
        task = store.insert(_make_task())
        task.status = "paused"
        task.progress = 42.5
        store.update(task)
        reloaded = store.get_by_id(task.id)
        assert reloaded.status == "paused"
        assert reloaded.progress == pytest.approx(42.5)


class TestDelete:
    def test_delete_removes_task(self, store):
        task = store.insert(_make_task())
        store.delete(task.id)
        with pytest.raises(TaskNotFoundError):
            store.get_by_id(task.id)


class TestListAll:
    def test_empty_list(self, store):
        assert store.list_all() == []

    def test_returns_all_tasks(self, store):
        store.insert(_make_task(info_hash="e" * 40, name="A"))
        store.insert(_make_task(info_hash="f" * 40, name="B"))
        assert len(store.list_all()) == 2
