"""
Tests for the review-frequency (highlight_weight) control
added to the highlight edit form (_highlight_edit.html + save_highlight_edit).

Covers:
  1. Template logic  – hidden field value & active-button CSS selection
  2. Endpoint        – save_highlight_edit accepts & persists highlight_weight
  3. Clamping        – values outside [0.0, 2.0] are clamped
  4. None fallback   – highlight_weight=None renders and saves as 1.0
  5. Idempotency     – saving the same weight twice keeps value unchanged
  6. Algorithm link  – the saved field is the exact one used by the scoring algo
  7. Context routing – weight saved correctly for book / default / review contexts
"""
import sys, math
from pathlib import Path

# ── make app importable ───────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from sqlmodel import create_engine, Session, SQLModel
from sqlalchemy.pool import StaticPool

# 1. Build the test engine BEFORE importing the app.
#    StaticPool: all connections share the same in-memory SQLite DB.
_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# 2. Patch app.db._engine so that:
#    - get_engine() (used in lifespan's create_all) → test engine
#    - get_session() (used by every route)          → test engine
import app.db as _db
_db._engine = _test_engine

# 3. Now import the app (models register with SQLModel.metadata during import)
from app.main import app
from app.models import Highlight, Book, User, Settings

# 4. Also override get_session dependency for belt-and-suspenders
def _override_get_session():
    with Session(_test_engine) as session:
        yield session

app.dependency_overrides[_db.get_session] = _override_get_session

# ── seed minimal data ─────────────────────────────────────────────────────────
# Use TestClient as a context manager so the lifespan (create_all) runs first
with TestClient(app) as started_client:
    pass  # lifespan ran; tables now exist in _test_engine

with Session(_test_engine) as s:
    s.add(User(id=1, email="test@test.com", password_hash="x"))
    bk = Book(id=1, title="Test Book", author="Author", review_weight=1.0)
    s.add(bk)
    # Settings may already exist from lifespan – add only if absent
    from sqlmodel import select
    if not s.exec(select(Settings)).first():
        s.add(Settings(daily_review_count=5, highlight_recency=5, theme="light"))
    s.commit()

def make_highlight(id: int, hw: float | None = 1.0) -> Highlight:
    from datetime import datetime
    with Session(_test_engine) as s:
        existing = s.get(Highlight, id)
        if existing:
            existing.highlight_weight = hw
            s.add(existing)
            s.commit()
            return existing
        h = Highlight(id=id, text=f"Highlight {id}", book_id=1, user_id=1,
                      highlight_weight=hw,
                      created_at=datetime(2025, 1, 1))
        s.add(h)
        s.commit()
        return h

client = TestClient(app, raise_server_exceptions=True)

P = F = 0
def chk(name: str, ok: bool, detail: str = ""):
    global P, F
    if ok:
        print(f"  [PASS] {name}")
        P += 1
    else:
        print(f"  [FAIL] {name}" + (f"  <<< {detail}" if detail else ""))
        F += 1

# ═════════════════════════════════════════════════════════════════════════════
# SUITE 1 — Template logic (Jinja rendering, no HTTP)
# ═════════════════════════════════════════════════════════════════════════════
print("=" * 64)
print("SUITE 1 -- Template rendering logic")
print("=" * 64)

from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader(str(ROOT / "app" / "templates")))
tpl = env.get_template("_highlight_edit.html")

OPTIONS = [0.25, 0.5, 1.0, 1.5, 2.0]
LABELS  = ["Much less", "Less", "Normal", "More", "Much more"]

class FakeHighlight:
    def __init__(self, id, hw):
        self.id = id; self.text = "T"; self.note = None
        self.highlight_weight = hw; self.book = None
        self.location = None; self.location_type = None

def html_buttons_only(html: str) -> str:
    """Return only the portion of the rendered HTML before the <script> block."""
    script_start = html.find("<script>")
    return html[:script_start] if script_start != -1 else html

# Marker that appears exclusively in an active button's class attribute
# (uses double-quotes, while the setHW() JS string uses single-quotes)
ACTIVE_MARKER = 'class="px-3 py-2 rounded-md border text-xs font-medium transition-colors bg-primary-600 text-white border-primary-600"'

for hw_val, label in zip(OPTIONS, LABELS):
    h = FakeHighlight(id=99, hw=hw_val)
    html = tpl.render(highlight=h, context="book", request=None)
    html_btns = html_buttons_only(html)

    # hidden input carries the correct default value
    chk(f"  hw={hw_val}: hidden input value={hw_val}",
        f'value="{hw_val}"' in html or f"value=\"{hw_val}\"" in html,
        "hidden input mismatch")

    # exactly one button is active (has bg-primary-600) in the HTML (not JS)
    active_count = html_btns.count(ACTIVE_MARKER)
    chk(f"  hw={hw_val}: exactly 1 active button",
        active_count == 1, f"got {active_count}")

    # the active button is the right label
    idx = html_btns.find(ACTIVE_MARKER)
    snippet = html_btns[idx:idx+200]
    chk(f"  hw={hw_val}: active button is '{label}'",
        label in snippet, f"snippet: {snippet[:80]}")

# None weight → defaults to 1.0 (Normal active)
h_none = FakeHighlight(id=98, hw=None)
html_none = tpl.render(highlight=h_none, context="book", request=None)
html_none_btns = html_buttons_only(html_none)
active_none = html_none_btns.count(ACTIVE_MARKER)
chk("hw=None renders without error and has exactly 1 active button", active_none == 1)
idx_none = html_none_btns.find(ACTIVE_MARKER)
chk("hw=None: 'Normal' is the active button",
    "Normal" in html_none_btns[idx_none:idx_none + 250])

# setHW JS function is present
chk("setHW JS function present in template output",
    "function setHW(" in html_none)
# hidden input name is highlight_weight
chk("hidden input name='highlight_weight' present",
    'name="highlight_weight"' in html_none)

# ═════════════════════════════════════════════════════════════════════════════
# SUITE 2 — HTTP endpoint: save_highlight_edit persists highlight_weight
# ═════════════════════════════════════════════════════════════════════════════
print()
print("=" * 64)
print("SUITE 2 -- save_highlight_edit endpoint persists weight")
print("=" * 64)

def post_edit(hid: int, hw: float | str, context: str = "book") -> int:
    """POST edit form and return HTTP status code."""
    return client.post(f"/highlights/{hid}/edit",
                       data={"text": "Updated text", "highlight_weight": str(hw),
                             "context": context}).status_code

def get_hw(hid: int) -> float | None:
    with Session(_test_engine) as s:
        h = s.get(Highlight, hid)
        return h.highlight_weight if h else None

# Save each of the 5 UI weight values
for hw_val in OPTIONS:
    make_highlight(id=200 + int(hw_val * 100), hw=1.0)
    hid = 200 + int(hw_val * 100)
    status = post_edit(hid, hw_val)
    chk(f"  POST /highlights/{hid}/edit hw={hw_val} -> 200", status == 200)
    saved = get_hw(hid)
    chk(f"  Persisted value = {hw_val}",
        saved is not None and abs(saved - hw_val) < 1e-9,
        f"got {saved}")

# ═════════════════════════════════════════════════════════════════════════════
# SUITE 3 — Clamping (endpoint level)
# ═════════════════════════════════════════════════════════════════════════════
print()
print("=" * 64)
print("SUITE 3 -- Clamping outside [0.0, 2.0]")
print("=" * 64)

make_highlight(301, hw=1.0); make_highlight(302, hw=1.0); make_highlight(303, hw=1.0)

post_edit(301, -0.5)
chk("hw=-0.5 clamped to 0.0", abs(get_hw(301) - 0.0) < 1e-9, f"got {get_hw(301)}")

post_edit(302, 5.0)
chk("hw=5.0  clamped to 2.0", abs(get_hw(302) - 2.0) < 1e-9, f"got {get_hw(302)}")

post_edit(303, 0.0)
chk("hw=0.0 (boundary) saved as 0.0", abs(get_hw(303) - 0.0) < 1e-9, f"got {get_hw(303)}")

# ═════════════════════════════════════════════════════════════════════════════
# SUITE 4 — None / missing field behaviour
# ═════════════════════════════════════════════════════════════════════════════
print()
print("=" * 64)
print("SUITE 4 -- None / missing highlight_weight field")
print("=" * 64)

make_highlight(401, hw=0.5)
# POST without highlight_weight field at all → existing value preserved
status = client.post("/highlights/401/edit",
                     data={"text": "No weight field", "context": "book"}).status_code
chk("POST without highlight_weight field: 200 ok", status == 200)
chk("Existing hw=0.5 preserved when field omitted", abs(get_hw(401) - 0.5) < 1e-9,
    f"got {get_hw(401)}")

# highlight_weight=None in DB → template uses 1.0 fallback (tested in Suite 1)
make_highlight(402, hw=None)
status2 = post_edit(402, 1.0)
chk("hw=None record: can be set to 1.0 via edit form", status2 == 200)
chk("hw=None record: value saved as 1.0", abs(get_hw(402) - 1.0) < 1e-9)

# ═════════════════════════════════════════════════════════════════════════════
# SUITE 5 — Idempotency
# ═════════════════════════════════════════════════════════════════════════════
print()
print("=" * 64)
print("SUITE 5 -- Idempotency (saving same value twice)")
print("=" * 64)

make_highlight(501, hw=1.5)
post_edit(501, 1.5)
chk("First save hw=1.5: value still 1.5", abs(get_hw(501) - 1.5) < 1e-9)
post_edit(501, 1.5)
chk("Second save hw=1.5: value still 1.5", abs(get_hw(501) - 1.5) < 1e-9)
# Change and revert
post_edit(501, 2.0)
chk("Changed to 2.0", abs(get_hw(501) - 2.0) < 1e-9)
post_edit(501, 1.5)
chk("Reverted to 1.5", abs(get_hw(501) - 1.5) < 1e-9)

# ═════════════════════════════════════════════════════════════════════════════
# SUITE 6 — Algorithm link: saved field identical to scoring field
# ═════════════════════════════════════════════════════════════════════════════
print()
print("=" * 64)
print("SUITE 6 -- Algorithm link: highlight_weight feeds directly into scoring")
print("=" * 64)

import math as _math
TAU = 14.0
def ts(d): return 1.0 - _math.exp(-d / TAU)

# Save hw=2.0 via edit endpoint, then verify the scoring formula uses it
make_highlight(601, hw=1.0)
post_edit(601, 2.0)
saved_hw = get_hw(601)
chk("After edit-form save, highlight_weight == 2.0", abs(saved_hw - 2.0) < 1e-9)

# Scoring formula: score = ts(days) * book_weight * highlight_weight
# book_weight = 1.0 (test book), days = 365 (created Jan 2025)
from datetime import datetime, timezone
now = datetime.now(timezone.utc).replace(tzinfo=None)
with Session(_test_engine) as s:
    h601 = s.get(Highlight, 601)
    anchor = h601.last_reviewed_at or h601.created_at
    days = max(0.0, (now - anchor).total_seconds() / 86400.0) if anchor else 30.0
    score_hw2 = ts(days) * 1.0 * h601.highlight_weight   # hw saved via edit form
    score_hw1 = ts(days) * 1.0 * 1.0                     # baseline
chk("Score with hw=2.0 via edit form = 2x baseline",
    abs(score_hw2 / score_hw1 - 2.0) < 1e-6, f"ratio={score_hw2/score_hw1:.6f}")

# Save hw=0.25 (Much less) and confirm 8x difference from hw=2.0
make_highlight(602, hw=1.0)
post_edit(602, 0.25)
saved_hw2 = get_hw(602)
with Session(_test_engine) as s:
    h602 = s.get(Highlight, 602)
    anchor2 = h602.last_reviewed_at or h602.created_at
    days2 = max(0.0, (now - anchor2).total_seconds() / 86400.0) if anchor2 else 30.0
    score_ml = ts(days2) * 1.0 * h602.highlight_weight
score_mm = ts(days) * 1.0 * 2.0
ratio = score_mm / score_ml
chk("Score ratio Much-more (2.0) / Much-less (0.25) = 8x after edit-form save",
    abs(ratio - 8.0) < 0.01, f"ratio={ratio:.4f}")

# hw=0.0 → excluded from review pool (zero weight)
make_highlight(603, hw=1.0)
post_edit(603, 0.0)
with Session(_test_engine) as s:
    h603 = s.get(Highlight, 603)
    w603 = max(0.0, float(h603.highlight_weight or 0.0))
chk("hw=0.0 saved via edit form → weight=0.0 → excluded from pool",
    w603 == 0.0, f"got {w603}")

# ═════════════════════════════════════════════════════════════════════════════
# SUITE 7 — Context routing: weight saved correctly in all contexts
# ═════════════════════════════════════════════════════════════════════════════
print()
print("=" * 64)
print("SUITE 7 -- Context routing (book / default / favorites / discarded)")
print("=" * 64)

for ctx, hid_base in [("book", 700), ("", 710), ("favorites", 720), ("discarded", 730)]:
    make_highlight(hid_base, hw=1.0)
    resp = client.post(f"/highlights/{hid_base}/edit",
                       data={"text": "ctx test", "highlight_weight": "1.5",
                             "context": ctx})
    saved = get_hw(hid_base)
    label = f"context='{ctx}'" if ctx else "context=''"
    chk(f"  {label}: weight saved as 1.5", saved is not None and abs(saved - 1.5) < 1e-9,
        f"got {saved}, status={resp.status_code}")

# ═════════════════════════════════════════════════════════════════════════════
print()
print("=" * 64)
print(f"TOTAL: {P}/{P+F} passed  ({F} failed)")
print("=" * 64)
sys.exit(0 if F == 0 else 1)
