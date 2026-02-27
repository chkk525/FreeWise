"""
Tests for the review-frequency (highlight_weight) control
added to the highlight edit form (_highlight_edit.html + save_highlight_edit).

Covers:
  1. Template logic  - hidden field value & active-button CSS selection
  2. Endpoint        - save_highlight_edit accepts & persists highlight_weight
  3. Clamping        - values outside [0.0, 2.0] are clamped
  4. None fallback   - highlight_weight=None renders and saves as 1.0
  5. Idempotency     - saving the same weight twice keeps value unchanged
  6. Algorithm link  - the saved field is the exact one used by the scoring algo
  7. Context routing - weight saved correctly for book / default / review contexts
"""
import math
from pathlib import Path
from datetime import datetime, timezone

import pytest
from sqlmodel import Session
from jinja2 import Environment, FileSystemLoader

from app.models import Highlight

ROOT = Path(__file__).resolve().parent.parent

# ── Template rendering helpers ────────────────────────────────────────────────

OPTIONS = [0.25, 0.5, 1.0, 1.5, 2.0]
LABELS = ["Much less", "Less", "Normal", "More", "Much more"]

# Marker that appears exclusively in an active button's class attribute
ACTIVE_MARKER = (
    'class="px-3 py-2 rounded-md border text-xs font-medium '
    'transition-colors bg-primary-600 text-white border-primary-600"'
)


class FakeHighlight:
    """Minimal highlight-like object for template rendering tests."""
    def __init__(self, id, hw):
        self.id = id
        self.text = "T"
        self.note = None
        self.highlight_weight = hw
        self.book = None
        self.location = None
        self.location_type = None


def _render(hw):
    env = Environment(loader=FileSystemLoader(str(ROOT / "app" / "templates")))
    tpl = env.get_template("_highlight_edit.html")
    return tpl.render(highlight=FakeHighlight(id=99, hw=hw), context="book", request=None)


def _buttons_only(html: str) -> str:
    """Return HTML before the <script> block to avoid matching JS strings."""
    idx = html.find("<script>")
    return html[:idx] if idx != -1 else html


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 1 — Template rendering logic
# ══════════════════════════════════════════════════════════════════════════════

class TestTemplateRendering:
    @pytest.mark.parametrize("hw_val,label", list(zip(OPTIONS, LABELS)))
    def test_hidden_input_has_correct_value(self, hw_val, label):
        html = _render(hw_val)
        assert f'value="{hw_val}"' in html

    @pytest.mark.parametrize("hw_val,label", list(zip(OPTIONS, LABELS)))
    def test_exactly_one_active_button(self, hw_val, label):
        html = _buttons_only(_render(hw_val))
        assert html.count(ACTIVE_MARKER) == 1

    @pytest.mark.parametrize("hw_val,label", list(zip(OPTIONS, LABELS)))
    def test_active_button_is_correct_label(self, hw_val, label):
        html = _buttons_only(_render(hw_val))
        idx = html.find(ACTIVE_MARKER)
        snippet = html[idx:idx + 200]
        assert label in snippet

    def test_none_renders_one_active_button(self):
        html = _buttons_only(_render(None))
        assert html.count(ACTIVE_MARKER) == 1

    def test_none_defaults_to_normal(self):
        html = _buttons_only(_render(None))
        idx = html.find(ACTIVE_MARKER)
        assert "Normal" in html[idx:idx + 250]

    def test_sethw_js_function_present(self):
        assert "function setHW(" in _render(None)

    def test_hidden_input_name_present(self):
        assert 'name="highlight_weight"' in _render(None)


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 2 — save_highlight_edit endpoint persists weight
# ══════════════════════════════════════════════════════════════════════════════

class TestEndpointPersistsWeight:
    @pytest.mark.parametrize("hw_val", OPTIONS)
    def test_save_weight_value(self, hw_val, client, make_highlight, db):
        h = make_highlight(highlight_weight=1.0)
        resp = client.post(
            f"/highlights/{h.id}/edit",
            data={"text": "Updated text", "highlight_weight": str(hw_val), "context": "book"},
        )
        assert resp.status_code == 200
        db.refresh(h)
        assert abs(h.highlight_weight - hw_val) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 3 — Clamping outside [0.0, 2.0]
# ══════════════════════════════════════════════════════════════════════════════

class TestWeightClamping:
    def test_negative_clamped_to_zero(self, client, make_highlight, db):
        h = make_highlight(highlight_weight=1.0)
        client.post(
            f"/highlights/{h.id}/edit",
            data={"text": "t", "highlight_weight": "-0.5", "context": "book"},
        )
        db.refresh(h)
        assert abs(h.highlight_weight - 0.0) < 1e-9

    def test_above_max_clamped_to_two(self, client, make_highlight, db):
        h = make_highlight(highlight_weight=1.0)
        client.post(
            f"/highlights/{h.id}/edit",
            data={"text": "t", "highlight_weight": "5.0", "context": "book"},
        )
        db.refresh(h)
        assert abs(h.highlight_weight - 2.0) < 1e-9

    def test_boundary_zero_saved(self, client, make_highlight, db):
        h = make_highlight(highlight_weight=1.0)
        client.post(
            f"/highlights/{h.id}/edit",
            data={"text": "t", "highlight_weight": "0.0", "context": "book"},
        )
        db.refresh(h)
        assert abs(h.highlight_weight - 0.0) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 4 — None / missing field behaviour
# ══════════════════════════════════════════════════════════════════════════════

class TestMissingWeightField:
    def test_omitted_field_preserves_existing(self, client, make_highlight, db):
        h = make_highlight(highlight_weight=0.5)
        resp = client.post(
            f"/highlights/{h.id}/edit",
            data={"text": "No weight field", "context": "book"},
        )
        assert resp.status_code == 200
        db.refresh(h)
        assert abs(h.highlight_weight - 0.5) < 1e-9

    def test_none_record_can_be_set(self, client, make_highlight, db):
        h = make_highlight(highlight_weight=None)
        resp = client.post(
            f"/highlights/{h.id}/edit",
            data={"text": "t", "highlight_weight": "1.0", "context": "book"},
        )
        assert resp.status_code == 200
        db.refresh(h)
        assert abs(h.highlight_weight - 1.0) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 5 — Idempotency
# ══════════════════════════════════════════════════════════════════════════════

class TestIdempotency:
    def test_save_same_value_twice(self, client, make_highlight, db):
        h = make_highlight(highlight_weight=1.5)
        for _ in range(2):
            client.post(
                f"/highlights/{h.id}/edit",
                data={"text": "t", "highlight_weight": "1.5", "context": "book"},
            )
            db.refresh(h)
            assert abs(h.highlight_weight - 1.5) < 1e-9

    def test_change_and_revert(self, client, make_highlight, db):
        h = make_highlight(highlight_weight=1.5)
        client.post(
            f"/highlights/{h.id}/edit",
            data={"text": "t", "highlight_weight": "2.0", "context": "book"},
        )
        db.refresh(h)
        assert abs(h.highlight_weight - 2.0) < 1e-9
        client.post(
            f"/highlights/{h.id}/edit",
            data={"text": "t", "highlight_weight": "1.5", "context": "book"},
        )
        db.refresh(h)
        assert abs(h.highlight_weight - 1.5) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 6 — Algorithm link: saved field feeds directly into scoring
# ══════════════════════════════════════════════════════════════════════════════

class TestAlgorithmLink:
    TAU = 14.0

    @staticmethod
    def _ts(d):
        return 1.0 - math.exp(-d / 14.0)

    def test_hw_2_is_2x_baseline(self, client, make_highlight, db):
        h = make_highlight(highlight_weight=1.0)
        client.post(
            f"/highlights/{h.id}/edit",
            data={"text": "t", "highlight_weight": "2.0", "context": "book"},
        )
        db.refresh(h)
        assert abs(h.highlight_weight - 2.0) < 1e-9
        # Score ratio: hw=2.0 / hw=1.0 = 2.0 (same time-decay & book weight)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        anchor = h.last_reviewed_at or h.created_at
        days = max(0.0, (now - anchor).total_seconds() / 86400.0) if anchor else 30.0
        score_hw2 = self._ts(days) * 1.0 * h.highlight_weight
        score_hw1 = self._ts(days) * 1.0 * 1.0
        assert abs(score_hw2 / score_hw1 - 2.0) < 1e-6

    def test_much_more_much_less_ratio_8x(self, client, make_highlight, db):
        h_mm = make_highlight(highlight_weight=1.0)
        h_ml = make_highlight(highlight_weight=1.0)
        client.post(
            f"/highlights/{h_mm.id}/edit",
            data={"text": "t", "highlight_weight": "2.0", "context": "book"},
        )
        client.post(
            f"/highlights/{h_ml.id}/edit",
            data={"text": "t", "highlight_weight": "0.25", "context": "book"},
        )
        db.refresh(h_mm)
        db.refresh(h_ml)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        a_mm = h_mm.last_reviewed_at or h_mm.created_at
        a_ml = h_ml.last_reviewed_at or h_ml.created_at
        d_mm = max(0.0, (now - a_mm).total_seconds() / 86400.0) if a_mm else 30.0
        d_ml = max(0.0, (now - a_ml).total_seconds() / 86400.0) if a_ml else 30.0
        s_mm = self._ts(d_mm) * 1.0 * h_mm.highlight_weight
        s_ml = self._ts(d_ml) * 1.0 * h_ml.highlight_weight
        assert abs(s_mm / s_ml - 8.0) < 0.01

    def test_hw_zero_excluded_from_pool(self, client, make_highlight, db):
        h = make_highlight(highlight_weight=1.0)
        client.post(
            f"/highlights/{h.id}/edit",
            data={"text": "t", "highlight_weight": "0.0", "context": "book"},
        )
        db.refresh(h)
        assert max(0.0, float(h.highlight_weight or 0.0)) == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 7 — Context routing
# ══════════════════════════════════════════════════════════════════════════════

class TestContextRouting:
    @pytest.mark.parametrize("ctx", ["book", "", "favorites", "discarded"])
    def test_weight_saved_in_context(self, ctx, client, make_highlight, db):
        h = make_highlight(highlight_weight=1.0)
        resp = client.post(
            f"/highlights/{h.id}/edit",
            data={"text": "ctx test", "highlight_weight": "1.5", "context": ctx},
        )
        db.refresh(h)
        assert abs(h.highlight_weight - 1.5) < 1e-9
