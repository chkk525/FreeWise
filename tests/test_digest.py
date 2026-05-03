"""Tests for the daily email digest service + SMTP send + admin endpoint."""

from __future__ import annotations

import hashlib
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.models import ApiToken
from app.services.digest import build_digest
from app.services.email import EmailNotConfigured, SmtpConfig, load_config, send_email


# ── Digest content ──────────────────────────────────────────────────────


class TestDigestContent:
    def test_empty_library_still_renders(self, db):
        d = build_digest(db, user_id=1)
        assert "FreeWise digest" in d.subject
        assert "LIBRARY HEALTH" in d.text_body
        assert "Active highlights: 0" in d.text_body
        # Empty highlight set → no TODAY'S PICK section
        assert "TODAY'S PICK" not in d.text_body

    def test_includes_today_pick(self, db, make_highlight):
        make_highlight(text="Wisdom is knowing you know nothing")
        d = build_digest(db, user_id=1)
        assert "TODAY'S PICK" in d.text_body
        assert "Wisdom is knowing you know nothing" in d.text_body
        assert "Wisdom is knowing you know nothing" in d.html_body

    def test_includes_on_this_day_past_year(self, db, make_highlight):
        # Create a highlight from a past year on today's MM-DD.
        today = datetime.now()
        make_highlight(
            text="anniversary thought",
            created_at=datetime(today.year - 2, today.month, today.day, 9, 0),
        )
        d = build_digest(db, user_id=1)
        assert "ON THIS DAY" in d.text_body
        assert "anniversary thought" in d.text_body
        assert str(today.year - 2) in d.text_body

    def test_health_counts_dup_groups(self, db, make_highlight):
        text = "Long enough text for the 80-char prefix grouping fingerprint check"
        for _ in range(3):
            make_highlight(text=text)
        d = build_digest(db, user_id=1)
        assert "Duplicate groups: 1" in d.text_body

    def test_html_body_escapes_user_text(self, db, make_highlight):
        # XSS regression: a <script> tag in highlight text must not survive
        # into the HTML body unescaped.
        make_highlight(text='<script>alert("xss")</script> sneaky')
        d = build_digest(db, user_id=1)
        assert "<script>alert" not in d.html_body
        assert "&lt;script&gt;" in d.html_body


# ── SMTP env loading ────────────────────────────────────────────────────


class TestSmtpConfig:
    def test_missing_required_var_raises(self, monkeypatch):
        for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "SMTP_FROM", "SMTP_TO", "SMTP_PORT"):
            monkeypatch.delenv(k, raising=False)
        with pytest.raises(EmailNotConfigured):
            load_config()

    def test_loads_complete_config(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USER", "u@x.com")
        monkeypatch.setenv("SMTP_PASS", "abcd efgh ijkl mnop")  # spaces allowed
        monkeypatch.setenv("SMTP_FROM", "FreeWise <u@x.com>")
        monkeypatch.setenv("SMTP_TO", "u@x.com,b@x.com")
        cfg = load_config()
        assert cfg.host == "smtp.gmail.com"
        assert cfg.port == 587
        # Spaces stripped from app password.
        assert cfg.password == "abcdefghijklmnop"
        assert cfg.to_addrs == ("u@x.com", "b@x.com")

    def test_invalid_port_raises(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "x"); monkeypatch.setenv("SMTP_USER", "x")
        monkeypatch.setenv("SMTP_PASS", "x"); monkeypatch.setenv("SMTP_FROM", "x")
        monkeypatch.setenv("SMTP_TO", "x"); monkeypatch.setenv("SMTP_PORT", "not-a-number")
        with pytest.raises(EmailNotConfigured):
            load_config()


class TestSendEmail:
    def test_send_calls_login_and_send_message(self):
        cfg = SmtpConfig(
            host="smtp.example", port=587,
            user="u@x.com", password="pw",
            from_addr="u@x.com", to_addrs=("dest@x.com",),
        )
        # MagicMock with context-manager protocol; SMTP() returns it from __enter__.
        smtp_instance = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=smtp_instance)
        ctx.__exit__ = MagicMock(return_value=False)
        factory = MagicMock(return_value=ctx)

        send_email("Hello", "plain body", html_body="<b>html</b>",
                   config=cfg, smtp_factory=factory)

        factory.assert_called_once_with("smtp.example", 587)
        smtp_instance.login.assert_called_once_with("u@x.com", "pw")
        smtp_instance.send_message.assert_called_once()
        msg = smtp_instance.send_message.call_args[0][0]
        assert msg["Subject"] == "Hello"
        assert msg["To"] == "dest@x.com"


# ── Admin endpoint ──────────────────────────────────────────────────────


class TestAdminDigestEndpoint:
    def _seed_token(self, db, value="good-token"):
        t = ApiToken(
            token_prefix=value[:16],
            token_hash=hashlib.sha256(value.encode()).hexdigest(),
            name="t", user_id=1,
        )
        db.add(t); db.commit()

    def test_requires_auth(self, client):
        resp = client.post("/api/v2/admin/digest/send")
        assert resp.status_code == 401

    def test_dry_run_returns_subject_no_send(self, client, db, make_highlight):
        self._seed_token(db)
        make_highlight(text="content for dry-run digest")
        resp = client.post(
            "/api/v2/admin/digest/send?dry_run=true",
            headers={"Authorization": "Token good-token"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "FreeWise digest" in body["subject"]
        assert body["sent"] is False
        assert body["dry_run"] is True
        assert "content for dry-run digest" in body["text_preview"]

    def test_send_without_smtp_config_returns_503(self, client, db, monkeypatch, make_highlight):
        # Strip SMTP env so EmailNotConfigured fires.
        for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "SMTP_FROM", "SMTP_TO"):
            monkeypatch.delenv(k, raising=False)
        self._seed_token(db)
        make_highlight(text="x")
        resp = client.post(
            "/api/v2/admin/digest/send?dry_run=false",
            headers={"Authorization": "Token good-token"},
        )
        assert resp.status_code == 503
        # Generic message — full reason is logged server-side, not echoed.
        assert "SMTP is not configured" in resp.text
