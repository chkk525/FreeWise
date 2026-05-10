"""Frontend-facing security and caching hardening checks."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_html_writes_reject_cross_origin_posts(client):
    resp = client.post(
        "/settings/theme/toggle",
        headers={"Origin": "https://evil.example.com"},
    )

    assert resp.status_code == 403
    assert "Cross-origin request rejected" in resp.text


def test_html_writes_allow_same_origin_posts(client):
    resp = client.post(
        "/settings/theme/toggle",
        headers={"Origin": "http://testserver"},
    )

    assert resp.status_code == 204


def test_api_v2_is_not_blocked_by_html_csrf_middleware(client):
    resp = client.post(
        "/api/v2/ask",
        headers={"Origin": "https://evil.example.com"},
        json={"question": "hello"},
    )

    assert resp.status_code == 401


def test_book_detail_tag_remove_uses_form_field_not_hx_vals():
    html = (ROOT / "app/templates/book_detail.html").read_text()

    assert 'hx-vals=\'{"tag":' not in html
    assert 'name="tag"' in html
    assert 'type="hidden"' in html


def test_readwise_import_does_not_use_document_write():
    html = (ROOT / "app/templates/import_readwise.html").read_text()

    assert "document.write" not in html
    assert "DOMParser" in html


def test_service_worker_does_not_intercept_all_static_uploads():
    js = (ROOT / "app/static/sw.js").read_text()

    assert "url.pathname.startsWith('/static/')" not in js
    assert "PRECACHE.includes(url.pathname)" in js


def test_review_page_loads_keyboard_shortcuts_shell():
    html = (ROOT / "app/templates/review.html").read_text()
    partial = (ROOT / "app/templates/_keyboard_shortcuts.html").read_text()

    assert 'extends "base.html"' in html
    assert "/static/js/keyboard-shortcuts.js" in partial


def test_base_page_loads_shared_keyboard_shortcuts_once():
    html = (ROOT / "app/templates/base.html").read_text()
    partial = (ROOT / "app/templates/_keyboard_shortcuts.html").read_text()

    assert html.count('_keyboard_shortcuts.html') == 1
    assert partial.count("/static/js/keyboard-shortcuts.js") == 1
    assert "_NAV_TARGETS" not in html
    assert "review-done-btn" not in html


def test_shared_scripts_are_deferred():
    html = (ROOT / "app/templates/base.html").read_text()
    partial = (ROOT / "app/templates/_keyboard_shortcuts.html").read_text()

    assert '<script src="/static/vendor/htmx/htmx.min.js" defer></script>' in html
    assert '<script src="/static/vendor/lucide/lucide.min.js" defer></script>' in html
    assert '<script src="/static/js/keyboard-shortcuts.js" defer></script>' in partial


def test_keyboard_shortcuts_js_contains_review_actions():
    js = (ROOT / "app/static/js/keyboard-shortcuts.js").read_text()

    assert "review-done-btn" in js
    assert "review-fav-btn" in js
    assert "review-discard-btn" in js
    assert "review-edit-btn" in js


def test_dashboard_heatmap_logic_is_static_asset():
    html = (ROOT / "app/templates/dashboard.html").read_text()
    partial = (ROOT / "app/templates/_dashboard_activity.html").read_text()
    js = (ROOT / "app/static/js/dashboard-heatmaps.js").read_text()

    assert '<script src="/static/js/dashboard-heatmaps.js" defer></script>' in html
    assert 'id="dashboard-heatmap-data"' in partial
    assert 'id="dashboard-review-heatmap-data"' in partial
    assert "function renderHeatmap" not in html
    assert "function renderHeatmap" in js
    assert "htmx:afterSwap" in js
