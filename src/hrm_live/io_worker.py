"""Single-threaded worker for file I/O that must stay off the UI thread.

AppKit actions (NSSavePanel, dashboard buttons) run on the main thread;
AGENTS.md requires export writing and session persistence to happen away
from it.  This module owns one daemon ``ThreadPoolExecutor`` that serializes
those writes.  The UI thread only queues work; state callbacks run on the
worker thread and are safe because AppState methods are RLock-guarded.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

log = logging.getLogger(__name__)

_WORKER_PREFIX = "hrm-io"
_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=_WORKER_PREFIX)
    return _executor


def submit(
    fn: Callable[[], object],
    *,
    on_success: Callable[[object], None] | None = None,
    on_failure: Callable[[BaseException], None] | None = None,
) -> None:
    """Run *fn* on the I/O worker thread and dispatch result callbacks.

    A single worker serializes writes so the dashboard never blocks on disk.
    Callbacks execute on the worker thread and must be thread-safe; failures
    are logged here when no callback is supplied.
    """

    def _run() -> None:
        try:
            result = fn()
        except BaseException as exc:  # noqa: BLE001 - worker boundary
            if on_failure is not None:
                try:
                    on_failure(exc)
                except Exception:
                    log.exception("I/O worker failure callback raised")
            else:
                log.exception("I/O worker task failed", exc_info=exc)
            return
        if on_success is not None:
            try:
                on_success(result)
            except Exception:
                log.exception("I/O worker success callback raised")

    _get_executor().submit(_run)


def write_text_atomic_async(text: str, path: Path, *, context: str) -> None:
    """Atomically write *text* to *path* on the worker thread (best-effort)."""

    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)

    submit(
        _write,
        on_failure=lambda exc: log.warning(
            "Failed to persist %s: %s",
            context,
            exc,
        ),
    )


def flush(timeout: float = 10.0) -> None:
    """Block until all previously queued worker work completes.

    Used by tests and by the guarded shutdown coordinator so archives are
    fully drained before Python finalization.
    """

    if _executor is None:
        return
    marker = _executor.submit(lambda: None)
    marker.result(timeout=timeout)


def shutdown() -> None:
    """Drain pending work and stop the worker thread permanently."""

    if _executor is None:
        return
    _executor.shutdown(wait=True)
