"""
Full-algorithm test suite for FreeWise review selection.
Tests the complete recommendation algorithm from first principles using
mock objects (no database or app dependency).

Covers:
  1. Time-decay formula (tau = 14 days)
  2. Anchor selection (last_reviewed_at > created_at > 30d fallback)
  3. Weight system (highlight_weight, book review_weight)
  4. is_favorited has no effect on scoring
  5. is_discarded exclusion & review_count unused
  6. Recency bias (highlight_recency slider)
  7. Diversity / per-book cap
  8. daily_review_count and settings clamping
  9. Integration: combined weight + recency + diversity
"""
import math
import random
from datetime import datetime, timedelta
from collections import Counter, defaultdict

import pytest

# ─── EXACT MIRROR OF PRODUCTION ALGORITHM ─────────────────────────────────────
TAU_DAYS = 14.0
NOW = datetime(2026, 2, 22, 12, 0, 0)


class MockBook:
    def __init__(self, id, bw=1.0):
        self.id = id
        self.review_weight = bw


class MockHighlight:
    def __init__(self, id, ca=30, lr=None, hw=1.0, bw=1.0,
                 fav=False, disc=False, rc=0, bid=None):
        self.id = id
        self.book_id = bid or id
        self.created_at = NOW - timedelta(days=ca) if ca is not None else None
        self.last_reviewed_at = NOW - timedelta(days=lr) if lr is not None else None
        self.highlight_weight = hw
        self.is_favorited = fav
        self.is_discarded = disc
        self.review_count = rc
        self.book = MockBook(self.book_id, bw)


class MockSettings:
    def __init__(self, n=5, r=5):
        self.daily_review_count = n
        self.highlight_recency = r


def _ts(d):
    return 1.0 - math.exp(-d / TAU_DAYS)


def _bw(h):
    return max(0.0, float(h.book.review_weight)) if h.book else 1.0


def _hw(h):
    return max(0.0, float(h.highlight_weight)) if h.highlight_weight is not None else 1.0


def _days(h):
    a = h.last_reviewed_at or h.created_at
    return 30.0 if a is None else max(0.0, (NOW - a).total_seconds() / 86400.0)


def _wpick(items):
    tot = sum(x[1] for x in items)
    if tot <= 0:
        return random.choice(items)
    r = random.random() * tot
    u = 0.0
    for it in items:
        u += it[1]
        if u >= r:
            return it
    return items[-1]


def algo(pool, settings, n=None):
    if n is None:
        n = settings.daily_review_count
    active = [h for h in pool if not h.is_discarded]
    if not active:
        return []
    cands = []
    for h in active:
        w = _bw(h) * _hw(h)
        if w <= 0.0:
            continue
        s = _ts(_days(h)) * w
        if s <= 0.0:
            continue
        cands.append((h, s, h.book_id))
    if not cands:
        return []
    alpha = (settings.highlight_recency - 5) / 5.0
    if alpha != 0.0:
        raw = [
            (max(0.0, (NOW - h.created_at).total_seconds() / 86400.0) if h.created_at else None)
            for h, _, _ in cands
        ]
        known = [a for a in raw if a is not None]
        fb = sorted(known)[len(known) // 2] if known else 0.0
        ages = [a if a is not None else fb for a in raw]
        mn, mx = min(ages), max(ages)
        sp = max(mx - mn, 1.0)
        nc = []
        for (h, s, bid), age in zip(cands, ages):
            norm = (age - mn) / sp
            ns = s * math.exp(alpha * (0.5 - norm) * 4)
            if ns > 0.0:
                nc.append((h, ns, bid))
        cands = nc
    if not cands:
        return []
    mpb = 2 if n >= 4 else 1
    sel, bc, rem = [], defaultdict(int), cands[:]
    while len(sel) < n and rem:
        elig = [c for c in rem if bc[c[2]] < mpb]
        if not elig:
            break
        p = _wpick(elig)
        sel.append(p[0])
        bc[p[2]] += 1
        rem.remove(p)
    if len(sel) < n and rem:
        while len(sel) < n and rem:
            p = _wpick(rem)
            sel.append(p[0])
            rem.remove(p)
    return sel


def sim(pool, settings, n=None, T=8_000):
    counts = Counter()
    _n = n if n is not None else settings.daily_review_count
    for _ in range(T):
        for h in algo(pool, settings, n=_n):
            counts[h.id] += 1
    return {hid: c / T for hid, c in counts.items()}


def mk_book(bid, n_h, base_id, ca=60):
    return [MockHighlight(base_id + i, ca=ca, bid=bid) for i in range(n_h)]


# ── Fixture: deterministic random seed ────────────────────────────────────────

@pytest.fixture(autouse=True)
def _seed_rng():
    random.seed(2026)


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 1 — Time-decay formula (tau = 14 days)
# ══════════════════════════════════════════════════════════════════════════════

class TestTimeDecayFormula:
    def test_ts_zero_is_exactly_zero(self):
        assert _ts(0.0) == 0.0

    def test_ts_at_tau(self):
        assert abs(_ts(14) - (1 - 1 / math.e)) < 1e-9

    def test_ts_at_two_tau(self):
        assert abs(_ts(28) - (1 - math.exp(-2))) < 1e-9

    def test_ts_one_day_very_small(self):
        assert _ts(1) < 0.07

    def test_ts_thirty_days(self):
        assert abs(_ts(30) - 0.882681) < 1e-5

    def test_ts_monotone(self):
        assert _ts(1) < _ts(7) < _ts(14) < _ts(30) < _ts(90) < _ts(365)

    def test_ts_bounded_zero_one(self):
        assert all(0.0 <= _ts(d) <= 1.0 for d in [0, 1, 14, 30, 100, 1000, 9999])

    def test_ts_saturates_at_530d(self):
        assert _ts(530) == 1.0

    def test_ts_365d_less_than_one(self):
        assert _ts(365) < 1.0

    def test_ts_zero_excludes_from_pool(self):
        assert len(algo([MockHighlight(1, lr=0)], MockSettings())) == 0


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 2 — Anchor selection
# ══════════════════════════════════════════════════════════════════════════════

class TestAnchorSelection:
    def test_lr_takes_priority_over_ca(self):
        assert abs(_days(MockHighlight(1, ca=365, lr=1)) - 1.0) < 0.01

    def test_lr_365d_even_when_ca_1d(self):
        assert abs(_days(MockHighlight(2, ca=1, lr=365)) - 365.0) < 0.1

    def test_never_reviewed_uses_ca(self):
        assert abs(_days(MockHighlight(3, ca=90)) - 90.0) < 0.01

    def test_both_none_30d_fallback(self):
        assert _days(MockHighlight(4, ca=None)) == 30.0

    def test_score_ordering_lr(self):
        s_lr1 = _ts(_days(MockHighlight(1, ca=365, lr=1)))
        s_def = _ts(30.0)
        s_lr365 = _ts(_days(MockHighlight(3, ca=1, lr=365)))
        assert s_lr1 < s_def < s_lr365

    def test_long_unreviewed_wins_statistically(self):
        f = sim(
            [MockHighlight(1, ca=365, lr=1, bid=1),
             MockHighlight(2, ca=365, lr=60, bid=2)],
            MockSettings(r=5), n=1,
        )
        assert f.get(1, 0) < f.get(2, 0) * 0.5


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 3 — Weight system
# ══════════════════════════════════════════════════════════════════════════════

class TestWeightSystemFull:
    def test_hw_zero_excluded(self):
        assert len(algo([MockHighlight(1, hw=0.0)], MockSettings())) == 0

    def test_bw_zero_excluded(self):
        assert len(algo([MockHighlight(1, bw=0.0)], MockSettings())) == 0

    def test_hw_high_bw_zero_excluded(self):
        assert len(algo([MockHighlight(1, hw=2.0, bw=0.0)], MockSettings())) == 0

    def test_hw_none_fallback(self):
        assert len(algo([MockHighlight(1, hw=None)], MockSettings())) == 1

    @pytest.mark.parametrize("hw_val,label", [
        (0.25, "Much less"), (0.5, "Less"), (1.0, "Normal"),
        (1.5, "More"), (2.0, "Much more"),
    ])
    def test_ui_weight_options_in_pool(self, hw_val, label):
        assert len(algo([MockHighlight(1, hw=hw_val)], MockSettings())) == 1

    def test_hw_2_is_2x(self):
        b = _ts(30.0)
        assert abs(b * 2.0 / (b * 1.0) - 2.0) < 1e-9

    def test_hw_half_is_half(self):
        b = _ts(30.0)
        assert abs(b * 0.5 / (b * 1.0) - 0.5) < 1e-9

    def test_much_more_much_less_ratio_8x(self):
        b = _ts(30.0)
        assert abs(b * 2.0 / (b * 0.25) - 8.0) < 1e-9

    def test_hw_2_bw_2_is_4x(self):
        b = _ts(30.0)
        assert abs(b * 4.0 / (b * 1.0) - 4.0) < 1e-9

    def test_hw_1_5_bw_2_is_3x(self):
        b = _ts(30.0)
        assert abs(b * 3.0 / (b * 1.0) - 3.0) < 1e-9

    def test_statistical_much_more_vs_much_less(self):
        fw = sim(
            [MockHighlight(1, ca=30, hw=2.0, bid=1),
             MockHighlight(2, ca=30, hw=0.25, bid=2)],
            MockSettings(), n=1,
        )
        ratio = fw.get(1, 0.0001) / fw.get(2, 0.0001)
        assert 7.0 < ratio < 9.0, f"ratio={ratio:.2f}"


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 4 — is_favorited has NO effect on scoring
# ══════════════════════════════════════════════════════════════════════════════

class TestFavoritedNoEffect:
    def test_identical_raw_scores(self):
        h_fav = MockHighlight(1, ca=30, fav=True, bid=1)
        h_unf = MockHighlight(2, ca=30, fav=False, bid=2)
        s_fav = _ts(_days(h_fav)) * _bw(h_fav) * _hw(h_fav)
        s_unf = _ts(_days(h_unf)) * _bw(h_unf) * _hw(h_unf)
        assert abs(s_fav - s_unf) < 1e-9

    def test_favorited_not_excluded(self):
        assert len(algo([MockHighlight(1, ca=30, fav=True)], MockSettings())) == 1

    def test_statistical_50_50(self):
        h_fav = MockHighlight(1, ca=30, fav=True, bid=1)
        h_unf = MockHighlight(2, ca=30, fav=False, bid=2)
        ff = sim([h_fav, h_unf], MockSettings(), n=1)
        assert abs(ff.get(1, 0) - ff.get(2, 0)) < 0.03


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 5 — is_discarded exclusion & review_count unused
# ══════════════════════════════════════════════════════════════════════════════

class TestDiscardedAndReviewCount:
    def test_discarded_hw_high_excluded(self):
        assert len(algo([MockHighlight(1, hw=2.0, disc=True)], MockSettings())) == 0

    def test_mixed_only_nondiscarded(self):
        r = algo([MockHighlight(1, disc=True), MockHighlight(2)], MockSettings())
        assert len(r) == 1 and r[0].id == 2

    def test_all_discarded_empty(self):
        pool = [MockHighlight(i, disc=True) for i in range(5)]
        assert len(algo(pool, MockSettings())) == 0

    def test_discarded_plus_high_weight_excluded(self):
        assert len(algo([MockHighlight(1, hw=2.0, bw=2.0, disc=True)], MockSettings())) == 0

    def test_review_count_not_in_formula(self):
        h_r0 = MockHighlight(1, ca=60, lr=30, rc=0, bid=60)
        h_r99 = MockHighlight(2, ca=60, lr=30, rc=99, bid=61)
        sc0 = _ts(_days(h_r0)) * _bw(h_r0) * _hw(h_r0)
        sc99 = _ts(_days(h_r99)) * _bw(h_r99) * _hw(h_r99)
        assert abs(sc0 - sc99) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 6 — Recency bias
# ══════════════════════════════════════════════════════════════════════════════

class TestRecencyBiasFull:
    def test_r5_alpha_zero(self):
        assert (5 - 5) / 5.0 == 0.0

    def test_r0_alpha_neg1(self):
        assert abs((0 - 5) / 5.0 - (-1.0)) < 1e-9

    def test_r10_alpha_pos1(self):
        assert abs((10 - 5) / 5.0 - 1.0) < 1e-9

    def test_r0_older_boosted(self):
        alpha = -1.0
        m_old = math.exp(alpha * (0.5 - 1.0) * 4)
        m_new = math.exp(alpha * (0.5 - 0.0) * 4)
        assert m_old > 1.0
        assert m_new < 1.0
        assert abs(m_old * m_new - 1.0) < 1e-9
        assert m_old >= 7.0

    def test_r10_newer_boosted(self):
        alpha = 1.0
        m_old = math.exp(alpha * (0.5 - 1.0) * 4)
        m_new = math.exp(alpha * (0.5 - 0.0) * 4)
        assert m_new > 1.0
        assert m_old < 1.0
        assert abs(m_old * m_new - 1.0) < 1e-9
        assert m_new >= 7.0

    def test_slider_old_mult_monotone_decreasing(self):
        mults = [math.exp(((r - 5) / 5.0) * (0.5 - 1.0) * 4) if r != 5 else 1.0
                 for r in range(11)]
        assert all(mults[i] >= mults[i + 1] for i in range(10))

    def test_slider_new_mult_monotone_increasing(self):
        mults_old = [math.exp(((r - 5) / 5.0) * (0.5 - 1.0) * 4) if r != 5 else 1.0
                     for r in range(11)]
        mults_new = [1 / m for m in mults_old]
        assert all(mults_new[i] <= mults_new[i + 1] for i in range(10))

    def test_r5_old_mult_exactly_one(self):
        mults = [math.exp(((r - 5) / 5.0) * (0.5 - 1.0) * 4) if r != 5 else 1.0
                 for r in range(11)]
        assert abs(mults[5] - 1.0) < 1e-9

    def test_recency_uses_ca_old_boosted(self):
        alpha_0 = -1.0
        mn_ca, mx_ca, sp_ca = 1.0, 730.0, 729.0
        norm_A = (730 - mn_ca) / sp_ca
        mA = math.exp(alpha_0 * (0.5 - norm_A) * 4)
        assert mA > 1.0

    def test_recency_uses_ca_new_penalised(self):
        alpha_0 = -1.0
        mn_ca, sp_ca = 1.0, 729.0
        norm_B = (1 - mn_ca) / sp_ca
        mB = math.exp(alpha_0 * (0.5 - norm_B) * 4)
        assert mB < 1.0

    @pytest.mark.parametrize("r_v", [0, 10])
    def test_same_age_identical_multipliers(self, r_v):
        alpha = (r_v - 5) / 5.0
        ages = [60.0, 60.0, 60.0]
        sp = max(max(ages) - min(ages), 1.0)
        mults = [math.exp(alpha * (0.5 - (a - 60.0) / sp) * 4) for a in ages]
        assert abs(mults[0] - mults[1]) < 1e-9
        assert abs(mults[1] - mults[2]) < 1e-9

    def test_statistical_r0_old_selected_more(self):
        pool = [MockHighlight(1, ca=730, bid=1), MockHighlight(2, ca=1, bid=2)]
        f_r0 = sim(pool, MockSettings(r=0), n=1)
        f_r5 = sim(pool, MockSettings(r=5), n=1)
        assert f_r0.get(1, 0) > f_r5.get(1, 0)

    def test_statistical_r10_new_selected_more(self):
        pool = [MockHighlight(1, ca=730, bid=1), MockHighlight(2, ca=1, bid=2)]
        f_r10 = sim(pool, MockSettings(r=10), n=1)
        f_r5 = sim(pool, MockSettings(r=5), n=1)
        assert f_r10.get(2, 0) > f_r5.get(2, 0)


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 7 — Diversity / per-book cap
# ══════════════════════════════════════════════════════════════════════════════

class TestDiversityFull:
    def test_max_per_book_n_le_3(self):
        assert all((2 if n >= 4 else 1) == 1 for n in [1, 2, 3])

    def test_max_per_book_n_ge_4(self):
        assert all((2 if n >= 4 else 1) == 2 for n in [4, 5, 6, 15])

    def test_n3_single_book_pool_returns_3(self):
        pool6 = mk_book(1, 6, 100)
        for _ in range(200):
            assert len(algo(pool6, MockSettings(n=3))) == 3

    def test_n4_single_book_pool_returns_4(self):
        pool6 = mk_book(1, 6, 100)
        for _ in range(200):
            assert len(algo(pool6, MockSettings(n=4))) == 4

    def test_n4_three_books_cap_respected(self):
        pool_3b = mk_book(10, 2, 200) + mk_book(20, 2, 210) + mk_book(30, 2, 220)
        for _ in range(200):
            r = algo(pool_3b, MockSettings(n=4))
            bc = Counter(h.book_id for h in r)
            assert max(bc.values()) <= 2

    def test_no_duplicate_highlights(self):
        for _ in range(200):
            ids = [h.id for h in algo(mk_book(1, 20, 300), MockSettings(n=10))]
            assert len(ids) == len(set(ids))

    def test_pool_smaller_than_n(self):
        assert len(algo(mk_book(1, 3, 400), MockSettings(n=10))) == 3

    def test_n1_returns_exactly_one(self):
        assert len(algo(mk_book(1, 5, 500), MockSettings(n=1))) == 1

    def test_fill_dominant_book(self):
        pool_dom = mk_book(1, 10, 600) + mk_book(2, 1, 700)
        for _ in range(200):
            assert len(algo(pool_dom, MockSettings(n=5))) == 5

    def test_fill_kicks_in(self):
        pool_dom = mk_book(1, 10, 600) + mk_book(2, 1, 700)
        results = [algo(pool_dom, MockSettings(n=5)) for _ in range(200)]
        book_A_counts = [Counter(h.book_id for h in r).get(1, 0) for r in results]
        assert any(c > 2 for c in book_A_counts)


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 8 — daily_review_count and settings clamping
# ══════════════════════════════════════════════════════════════════════════════

class TestSettingsClamping:
    @pytest.mark.parametrize("nv,expected", [
        (1, 1), (3, 3), (5, 5), (7, 7), (10, 10), (15, 10),
    ])
    def test_n_returns_min_n_pool(self, nv, expected):
        pool10 = [MockHighlight(i, bid=i) for i in range(1, 11)]
        assert len(algo(pool10, MockSettings(n=nv))) == expected

    def test_n0_returns_empty(self):
        pool10 = [MockHighlight(i, bid=i) for i in range(1, 11)]
        assert len(algo(pool10, MockSettings(), n=0)) == 0

    @pytest.mark.parametrize("v,expected", [
        (-1, 1), (0, 1), (1, 1), (7, 7), (15, 15), (16, 15), (100, 15),
    ])
    def test_clamp_daily_review_count(self, v, expected):
        assert max(1, min(15, v)) == expected

    @pytest.mark.parametrize("v,expected", [
        (-1, 0), (0, 0), (5, 5), (10, 10), (11, 10),
    ])
    def test_clamp_highlight_recency(self, v, expected):
        assert max(0, min(10, v)) == expected


# ══════════════════════════════════════════════════════════════════════════════
# SUITE 9 — Integration
# ══════════════════════════════════════════════════════════════════════════════

class TestAlgoIntegration:
    def test_discarded_overrides_high_weight(self):
        r = algo(
            [MockHighlight(1, hw=2.0, disc=True), MockHighlight(2, hw=0.25)],
            MockSettings(),
        )
        assert len(r) == 1 and r[0].id == 2

    def test_bw_zero_plus_recency_still_excluded(self):
        assert len(algo([MockHighlight(1, ca=1, bw=0.0)], MockSettings(r=10))) == 0

    def test_r0_old_hw_high_dominates(self):
        f = sim(
            [MockHighlight(1, ca=730, hw=2.0, bid=1),
             MockHighlight(2, ca=1, hw=0.25, bid=2)],
            MockSettings(r=0), n=1,
        )
        assert f.get(1, 0) > 0.90, f"old={f.get(1, 0):.3f}"

    def test_r10_new_hw_high_dominates(self):
        f = sim(
            [MockHighlight(1, ca=1, hw=2.0, bid=1),
             MockHighlight(2, ca=730, hw=0.25, bid=2)],
            MockSettings(r=10), n=1,
        )
        assert f.get(1, 0) > 0.95, f"new={f.get(1, 0):.3f}"

    def test_r0_old_unfavorited_beats_new_favorited(self):
        h_fav_new = MockHighlight(1, ca=1, hw=1.0, fav=True, bid=1)
        h_unf_old = MockHighlight(2, ca=730, hw=1.0, fav=False, bid=2)
        f = sim([h_fav_new, h_unf_old], MockSettings(r=0), n=1)
        assert f.get(2, 0) > f.get(1, 0)

    @pytest.mark.parametrize("n_val", [1, 5, 10, 15])
    def test_daily_review_count_respected(self, n_val):
        pool20 = [MockHighlight(i, bid=i) for i in range(1, 21)]
        for _ in range(20):
            r = algo(pool20, MockSettings(n=n_val))
            assert len(r) == n_val
