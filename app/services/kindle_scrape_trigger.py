"""On-demand Kindle scrape trigger (Phase 3 of the Kindle pipeline).

The QNAP cron at 03:00 covers the daily case; this module is for the
"I just finished a book and want it in FreeWise *now*" case.

The dashboard exposes a button → POST /dashboard/kindle/scrape-now →
``trigger_scrape()`` here → ``subprocess.Popen`` of ``KINDLE_SCRAPE_CMD``
(typically ``/share/Container/freewise/kindle/tools/kindle_dl.sh``) with
stdout / stderr captured to a tail buffer.

State is persisted as JSON in ``KINDLE_SCRAPE_STATE_FILE`` (default
``/tmp/freewise-kindle-scrape.json``) so multiple uvicorn workers see
the same view, and the status survives a worker restart.

Disabled when ``KINDLE_SCRAPE_CMD`` is unset — the button hides itself
and the trigger endpoint returns 503.
"""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import signal
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Env knobs.
_ENV_CMD = "KINDLE_SCRAPE_CMD"
_ENV_STATE = "KINDLE_SCRAPE_STATE_FILE"
_ENV_LOG_TAIL_BYTES = "KINDLE_SCRAPE_LOG_TAIL_BYTES"

_DEFAULT_STATE_PATH = "/tmp/freewise-kindle-scrape.json"
_DEFAULT_LOG_TAIL = 4096

# Process-local mutex around the read-check-write sequence in
# trigger_scrape() — without this, two concurrent POST /scrape-now
# requests can both pass the "running?" check before either writes
# state, double-spawning the scraper. (U100 review HIGH #2.)
_TRIGGER_LOCK = threading.Lock()


@dataclass(frozen=True)
class ScrapeStatus:
    enabled: bool
    running: bool
    pid: Optional[int] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    exit_code: Optional[int] = None
    log_tail: str = ""
    duration_s: Optional[float] = None
    cmd: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _ProcessHandle:
    """Internal state we persist between requests."""
    pid: int
    started_at: str
    cmd: str
    log_path: str
    finished_at: Optional[str] = None
    exit_code: Optional[int] = None


def _state_path() -> Path:
    return Path(os.environ.get(_ENV_STATE, _DEFAULT_STATE_PATH))


def _log_tail_bytes() -> int:
    raw = os.environ.get(_ENV_LOG_TAIL_BYTES, "")
    try:
        return max(256, int(raw)) if raw else _DEFAULT_LOG_TAIL
    except ValueError:
        return _DEFAULT_LOG_TAIL


def _enabled() -> bool:
    return bool(os.environ.get(_ENV_CMD, "").strip())


def _read_handle() -> Optional[_ProcessHandle]:
    p = _state_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return _ProcessHandle(**data)


def _write_handle(h: _ProcessHandle) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(h)))


def _check_and_reap(pid: int) -> tuple[bool, Optional[int]]:
    """Cross-platform liveness check that captures the exit code on reap.

    Returns ``(alive, exit_code)``:
    - alive=True, exit_code=None: process is still running
    - alive=False, exit_code=N: we just reaped it; N is the real status
    - alive=False, exit_code=None: dead but unreaped by us (different
      parent, e.g. uvicorn worker restart) — caller marks unknown

    ``os.kill(pid, 0)`` alone returns True for zombies (the kernel slot
    is still allocated until reaped), so we always attempt a non-blocking
    ``waitpid`` to harvest the exit status before it's lost. The previous
    version reaped via ``waitpid`` but discarded the status, causing
    ``get_status`` to retry and always fall back to exit_code=-1.
    """
    if pid <= 0:
        return False, None
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return False, None
    # Reap zombies. WNOHANG returns (0, 0) for a still-running child.
    try:
        reaped_pid, status = os.waitpid(pid, os.WNOHANG)
        if reaped_pid == pid:
            if os.WIFEXITED(status):
                return False, os.WEXITSTATUS(status)
            if os.WIFSIGNALED(status):
                return False, -os.WTERMSIG(status)
            return False, None
    except ChildProcessError:
        # Not our child anymore (or never was). Trust the kill probe.
        pass
    except OSError:
        pass
    return True, None


def _process_alive(pid: int) -> bool:
    """Backwards-compatible bool wrapper around :func:`_check_and_reap`."""
    alive, _ = _check_and_reap(pid)
    return alive


def _read_log_tail(log_path: str, n: int) -> str:
    p = Path(log_path)
    if not p.is_file():
        return ""
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > n:
                fh.seek(-n, 2)
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_status() -> ScrapeStatus:
    """Read current state. Cheap; safe to poll."""
    if not _enabled():
        return ScrapeStatus(enabled=False, running=False)

    h = _read_handle()
    if h is None:
        return ScrapeStatus(enabled=True, running=False, cmd=os.environ.get(_ENV_CMD))

    if h.exit_code is None:
        alive, reaped_rc = _check_and_reap(h.pid)
    else:
        alive, reaped_rc = False, None

    # If the handle says "no exit_code" but the process is dead, reap it.
    if not alive and h.exit_code is None:
        # exit_code=None below (rather than -1) means "dead but unreaped
        # by us" — reapership was lost (e.g. uvicorn worker restart).
        h.exit_code = reaped_rc
        h.finished_at = _now_iso()
        _write_handle(h)

    duration: Optional[float] = None
    if h.started_at and h.finished_at:
        try:
            t0 = datetime.fromisoformat(h.started_at).timestamp()
            t1 = datetime.fromisoformat(h.finished_at).timestamp()
            duration = round(t1 - t0, 2)
        except ValueError:
            pass

    return ScrapeStatus(
        enabled=True,
        running=alive,
        pid=h.pid if alive else None,
        started_at=h.started_at,
        finished_at=h.finished_at,
        exit_code=h.exit_code,
        log_tail=_read_log_tail(h.log_path, _log_tail_bytes()),
        duration_s=duration,
        cmd=h.cmd,
    )


class ScrapeAlreadyRunning(RuntimeError):
    pass


class ScrapeNotConfigured(RuntimeError):
    pass


def trigger_scrape() -> ScrapeStatus:
    """Spawn the scrape command in the background. Idempotent: a second
    call while a scrape is in flight raises ``ScrapeAlreadyRunning``."""
    cmd_str = os.environ.get(_ENV_CMD, "").strip()
    if not cmd_str:
        raise ScrapeNotConfigured(f"{_ENV_CMD} env var is not set")

    # Hold the lock across the read-check-write so two concurrent
    # callers can't both pass the running check.
    with _TRIGGER_LOCK:
        current = get_status()
        if current.running:
            raise ScrapeAlreadyRunning(
                f"scrape already running (pid={current.pid}, started={current.started_at})"
            )

        log_path = str(_state_path().with_suffix(".log"))
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(log_path, "wb")

        # shlex split so the env var can be a full command line, but we
        # also accept a single binary path (no spaces) without splitting.
        argv = shlex.split(cmd_str)
        proc = subprocess.Popen(
            argv,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # detach from the uvicorn process group
        )
        log_fh.close()  # the subprocess holds its own fd

        handle = _ProcessHandle(
            pid=proc.pid,
            started_at=_now_iso(),
            cmd=cmd_str,
            log_path=log_path,
        )
        _write_handle(handle)

    # Outside the lock — brief sleep so the OS commits the fork before
    # we report status.
    time.sleep(0.05)
    return get_status()


def _cancel_scrape_blocking() -> ScrapeStatus:
    """Blocking implementation — sleeps up to ~1.6s. Use ``cancel_scrape``
    (async) from request handlers; only call this directly from sync
    code or when you've already moved off the event loop."""
    current = get_status()
    if not current.running or not current.pid:
        return current
    pid = current.pid
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return get_status()

    # Wait up to ~1.5s for graceful exit. Use _check_and_reap directly
    # so the SIGTERM exit status (typically -15) isn't lost — the bool
    # wrapper _process_alive would discard it, leaving get_status to
    # retry on an already-reaped pid and fall back to exit_code=None.
    captured_rc: Optional[int] = None
    for _ in range(15):
        time.sleep(0.1)
        alive, rc = _check_and_reap(pid)
        if not alive:
            captured_rc = rc
            break

    alive, rc = _check_and_reap(pid)
    if alive:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        # Give the kernel a beat to mark the entry dead, then reap.
        time.sleep(0.1)
        _, rc = _check_and_reap(pid)
        captured_rc = rc
    elif captured_rc is None:
        captured_rc = rc

    # Persist the captured exit code so get_status doesn't try to
    # waitpid an already-reaped pid (which would yield exit_code=None).
    h = _read_handle()
    if h is not None and h.exit_code is None:
        h.exit_code = captured_rc
        h.finished_at = _now_iso()
        _write_handle(h)
    return get_status()


async def cancel_scrape() -> ScrapeStatus:
    """Best-effort kill of a running scrape. Sends SIGTERM first, then
    escalates to SIGKILL if the process hasn't died within ~1.5s. Real-
    world child is a shell wrapper around ``docker compose``; polite
    SIGTERM doesn't always propagate to the container, so escalation
    is necessary.

    Async-first so the up-to-1.6s wait doesn't block the uvicorn event
    loop. Falls back to sync ``_cancel_scrape_blocking`` for callers
    that aren't on the loop.
    """
    return await asyncio.get_running_loop().run_in_executor(
        None, _cancel_scrape_blocking
    )
