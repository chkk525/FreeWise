"""Tests for the on-demand Kindle scrape trigger (U99)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from app.services import kindle_scrape_trigger as trig


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    """Point KINDLE_SCRAPE_STATE_FILE at a fresh tmp file per test."""
    state_path = tmp_path / "scrape_state.json"
    monkeypatch.setenv("KINDLE_SCRAPE_STATE_FILE", str(state_path))
    yield state_path


class TestScrapeStatus:
    def test_disabled_when_cmd_unset(self, isolated_state, monkeypatch):
        monkeypatch.delenv("KINDLE_SCRAPE_CMD", raising=False)
        s = trig.get_status()
        assert s.enabled is False
        assert s.running is False
        assert s.pid is None

    def test_enabled_idle_when_cmd_set_and_no_state(self, isolated_state, monkeypatch):
        monkeypatch.setenv("KINDLE_SCRAPE_CMD", f"{sys.executable} -c \"pass\"")
        s = trig.get_status()
        assert s.enabled is True
        assert s.running is False
        assert s.cmd == f"{sys.executable} -c \"pass\""


class TestTriggerScrape:
    def test_raises_when_unconfigured(self, isolated_state, monkeypatch):
        monkeypatch.delenv("KINDLE_SCRAPE_CMD", raising=False)
        with pytest.raises(trig.ScrapeNotConfigured):
            trig.trigger_scrape()

    def test_runs_quick_command_to_completion(self, isolated_state, monkeypatch):
        # Use /bin/true which exits 0 immediately. We don't want to
        # depend on shell features so the env var is just the bare path.
        monkeypatch.setenv("KINDLE_SCRAPE_CMD", f"{sys.executable} -c \"pass\"")
        s = trig.trigger_scrape()
        # The process may already be done by the time this returns;
        # poll a few times to give the OS a chance to reap.
        for _ in range(20):
            s = trig.get_status()
            if not s.running:
                break
            time.sleep(0.05)
        assert s.running is False
        # The reap path captures the real exit status (0 for `pass`).
        # None is also acceptable if reapership was lost between threads
        # (rare in tests but possible).
        assert s.exit_code in (0, None)
        assert s.started_at is not None

    def test_nonzero_exit_code_is_captured(self, isolated_state, monkeypatch):
        """Regression: the reaper must surface the real exit code, not
        the previous always-fallback of -1."""
        monkeypatch.setenv(
            "KINDLE_SCRAPE_CMD",
            f"{sys.executable} -c \"import sys; sys.exit(7)\"",
        )
        trig.trigger_scrape()
        for _ in range(40):
            s = trig.get_status()
            if not s.running:
                break
            time.sleep(0.05)
        s = trig.get_status()
        assert s.running is False
        assert s.exit_code == 7

    def test_concurrent_trigger_raises(self, isolated_state, monkeypatch):
        # Use /bin/sleep 1 so the first run is still going when we
        # attempt the second.
        monkeypatch.setenv("KINDLE_SCRAPE_CMD", f"{sys.executable} -c \"import time; time.sleep(1)\"")
        first = trig.trigger_scrape()
        assert first.running is True
        with pytest.raises(trig.ScrapeAlreadyRunning):
            trig.trigger_scrape()
        # Cleanup — don't leave the sleep child orphaned.
        trig._cancel_scrape_blocking()

    def test_concurrent_threads_only_spawn_once(self, isolated_state, monkeypatch):
        """U100 review HIGH #2 fix: the trigger lock must serialize the
        read-check-write so two threads racing both produce one Popen
        and one ScrapeAlreadyRunning, not two child processes."""
        import threading
        monkeypatch.setenv("KINDLE_SCRAPE_CMD", f"{sys.executable} -c \"import time; time.sleep(2)\"")

        results: list = []
        errors: list = []
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            try:
                results.append(trig.trigger_scrape())
            except trig.ScrapeAlreadyRunning as e:
                errors.append(e)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start(); t2.start()
        t1.join(); t2.join()

        # Exactly one trigger should have succeeded; the other must have
        # been rejected with ScrapeAlreadyRunning.
        assert len(results) == 1
        assert len(errors) == 1
        # And only one process should be alive.
        status = trig.get_status()
        assert status.running is True
        # Cleanup.
        trig._cancel_scrape_blocking()

    def test_log_tail_captures_stdout(self, isolated_state, monkeypatch):
        # Echo a known marker; the log tail should pick it up.
        marker = "freewise-test-marker-7c1a"
        monkeypatch.setenv(
            "KINDLE_SCRAPE_CMD",
            f"{sys.executable} -c \"print('{marker}')\"",
        )
        trig.trigger_scrape()
        for _ in range(40):
            s = trig.get_status()
            if not s.running:
                break
            time.sleep(0.05)
        s = trig.get_status()
        assert marker in s.log_tail

    def test_cancel_terminates_running_process(self, isolated_state, monkeypatch):
        monkeypatch.setenv("KINDLE_SCRAPE_CMD", f"{sys.executable} -c \"import time; time.sleep(30)\"")
        trig.trigger_scrape()
        assert trig.get_status().running is True
        trig._cancel_scrape_blocking()
        # Poll up to ~3s — SIGTERM delivery + Python signal handler +
        # process exit can take a noticeable beat on a busy CI host.
        for _ in range(60):
            if not trig.get_status().running:
                break
            time.sleep(0.05)
        assert trig.get_status().running is False


# ── Endpoint integration ────────────────────────────────────────────────


class TestScrapeEndpoints:
    def test_scrape_status_partial_disabled_state(self, client, monkeypatch):
        monkeypatch.delenv("KINDLE_SCRAPE_CMD", raising=False)
        r = client.get("/dashboard/kindle/scrape-status")
        assert r.status_code == 200
        assert "Kindle scraping is not configured" in r.text

    def test_scrape_status_partial_idle_state(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("KINDLE_SCRAPE_CMD", f"{sys.executable} -c \"pass\"")
        monkeypatch.setenv("KINDLE_SCRAPE_STATE_FILE", str(tmp_path / "s.json"))
        r = client.get("/dashboard/kindle/scrape-status")
        assert r.status_code == 200
        assert "Scrape now" in r.text
        assert "kindle-scrape-card" in r.text

    def test_scrape_now_503_when_unconfigured(self, client, monkeypatch):
        monkeypatch.delenv("KINDLE_SCRAPE_CMD", raising=False)
        r = client.post("/dashboard/kindle/scrape-now")
        assert r.status_code == 503
        assert "not configured" in r.text.lower()

    def test_scrape_now_starts_and_renders_running(self, client, monkeypatch, tmp_path):
        monkeypatch.setenv("KINDLE_SCRAPE_CMD", f"{sys.executable} -c \"import time; time.sleep(1)\"")
        monkeypatch.setenv("KINDLE_SCRAPE_STATE_FILE", str(tmp_path / "s.json"))
        r = client.post("/dashboard/kindle/scrape-now")
        assert r.status_code == 200
        # Either we caught it running, or it already finished — both fine.
        assert ("Scraping read.amazon.com" in r.text) or ("Scrape now" in r.text)
        # Cleanup
        trig._cancel_scrape_blocking()
