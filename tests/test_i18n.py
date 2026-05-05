"""Tests for app.i18n + the language toggle on /settings/ui."""
from __future__ import annotations

from sqlmodel import select

from app.i18n import DEFAULT_LANGUAGE, LANGUAGES, t
from app.models import Settings


# ── Pure translator function ────────────────────────────────────────────


def test_t_returns_source_for_default_language():
    """English passes through unchanged — no dict lookup."""
    assert t("Library", "en") == "Library"


def test_t_returns_japanese_when_language_is_ja():
    assert t("Library", "ja") == "ライブラリ"


def test_t_falls_back_to_source_for_missing_key():
    """Untranslated keys must not crash a render."""
    assert t("__never_translated__", "ja") == "__never_translated__"


def test_t_falls_back_for_unknown_language():
    assert t("Library", "klingon") == "Library"


def test_t_handles_empty_key():
    assert t("", "ja") == ""


def test_default_language_is_english():
    assert DEFAULT_LANGUAGE == "en"


def test_available_languages_includes_japanese():
    codes = {code for code, _ in LANGUAGES}
    assert "en" in codes
    assert "ja" in codes


# ── Settings persistence ────────────────────────────────────────────────


def test_settings_default_language_is_english(db):
    """A fresh install keeps the existing English UI."""
    from app.db import get_settings
    s = get_settings(db)
    assert s.language == "en"


def test_post_settings_persists_language(client, db):
    """Submitting the form with language=ja flips the singleton row."""
    resp = client.post("/settings/ui", data={
        "daily_review_count": "5",
        "highlight_recency": "5",
        "theme": "light",
        "language": "ja",
    })
    assert resp.status_code == 200  # PRG redirect → 303 → followed → 200
    settings = db.exec(select(Settings)).first()
    assert settings.language == "ja"


def test_post_settings_rejects_unknown_language(client, db):
    """Crafted POST can't lock the user into an unsupported locale."""
    client.post("/settings/ui", data={
        "daily_review_count": "5",
        "highlight_recency": "5",
        "theme": "light",
        "language": "klingon",
    })
    settings = db.exec(select(Settings)).first()
    assert settings.language == "en"


# ── Template rendering ──────────────────────────────────────────────────


def test_dashboard_renders_japanese_when_language_is_ja(client, db):
    """End-to-end: setting language=ja flips the nav + dashboard cards."""
    s = db.exec(select(Settings)).first()
    s.language = "ja"
    db.add(s)
    db.commit()
    resp = client.get("/")
    assert resp.status_code == 200
    # Nav link
    assert "ライブラリ" in resp.text
    # Streak card label
    assert "現在の連続記録" in resp.text


def test_html_lang_attribute_reflects_setting(client, db):
    """<html lang="…"> updates so screen readers + spellcheck pick it up."""
    s = db.exec(select(Settings)).first()
    s.language = "ja"
    db.add(s)
    db.commit()
    resp = client.get("/")
    assert 'lang="ja"' in resp.text
