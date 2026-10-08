"""Tests for the off-UI-thread I/O worker."""

from __future__ import annotations

import threading
from pathlib import Path

from hrm_live import io_worker


def test_submit_runs_off_main_thread_and_dispatches_result() -> None:
    observed = []

    def job() -> int:
        observed.append(threading.current_thread().name)
        return 42

    def on_success(result: object) -> None:
        observed.append(result)

    io_worker.submit(job, on_success=on_success)
    io_worker.flush()

    assert observed, "worker task never ran"
    assert observed[0] != "MainThread"
    assert observed[1] == 42


def test_submit_dispatches_failure_with_exception() -> None:
    captured: list[BaseException] = []

    def boom() -> None:
        raise ValueError("nope")

    io_worker.submit(boom, on_failure=lambda exc: captured.append(exc))
    io_worker.flush()

    assert len(captured) == 1
    assert isinstance(captured[0], ValueError)
    assert str(captured[0]) == "nope"


def test_write_text_atomic_async_lands_payload(tmp_path: Path) -> None:
    archive = tmp_path / "archive.json"
    io_worker.write_text_atomic_async('{"a": 1}\n', archive, context="test archive")
    io_worker.flush()

    assert archive.read_text(encoding="utf-8") == '{"a": 1}\n'
    assert list(tmp_path.iterdir()) == [archive]  # no temp file left behind


def test_write_text_atomic_async_replaces_existing(tmp_path: Path) -> None:
    archive = tmp_path / "archive.json"
    archive.write_text("old", encoding="utf-8")

    io_worker.write_text_atomic_async("new", archive, context="test archive")
    io_worker.flush()

    assert archive.read_text(encoding="utf-8") == "new"


def test_flush_drains_all_queued_work_in_order(tmp_path: Path) -> None:
    archive = tmp_path / "archive.json"
    io_worker.write_text_atomic_async("a\n", archive, context="order")
    io_worker.write_text_atomic_async("b\n", archive, context="order")
    io_worker.flush()

    # Single worker + atomic replace: the last write wins, no interleaving.
    assert archive.read_text(encoding="utf-8") == "b\n"
