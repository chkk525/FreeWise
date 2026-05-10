# Hands-off / Session Closeout

Last updated: 2026-05-10.

This file should stay in the repo. `tailwind.config.js` references it for the
Crimson Pro exception, and it is the handoff point for the next coding session.
The old Minna migration plan has been completed on `main` and is no longer the
source of truth.

## 1. Current State

Main app repo:

- Path: `/Users/chikaki/Development/freewise`
- Branch: `main`
- Remote status at closeout: clean and in sync with `origin/main`
- Latest commit: `9a19eff perf: defer dashboard activity heatmaps`

Deploy repo:

- Path: `/Users/chikaki/Development/freewise-qnap-deploy`
- Branch: `main`
- Remote status at closeout: clean and in sync with `origin/main`
- Latest commit: `03d8fa9 ops: suppress known compose orphan warning`

Production:

- LAN: `http://192.168.0.171:8063`
- Public: `https://freewise.chikaki.com` behind Cloudflare Access
- Ollama host: `http://192.168.0.151:11434`
- QNAP FreeWise container status at closeout: healthy

## 2. What This Session Completed

Performance:

- Materialized semantic duplicate scan cache in SQLite.
- Process-local semantic duplicate scan cache retained.
- Embedding input length capped with `FREEWISE_EMBED_TEXT_MAX_CHARS=1000`.
- Dashboard/review query trimming:
  - highlight totals merged into one aggregate query;
  - duplicated streak computation removed from the dashboard shell;
  - review page avoids the active-highlight full count unless rendering empty state.
- Dashboard heatmap renderer moved from inline JS to `/static/js/dashboard-heatmaps.js`.
- Dashboard activity heatmaps and streak cards moved behind `/dashboard/ui/activity`.
- Cover images now use async decoding; list/search cover images are lazy-loaded where appropriate.

Operations:

- Docker healthcheck now calls `/healthz`, not `/`.
- QNAP deploy script uses a writable Docker config path under app state.
- Known sibling `cloudflared` orphan warning is suppressed without deleting containers.
- Deploy script still preserves QNAP `.env.qnap` and runtime data.

Verification:

- Full local suite after latest app change: `948 passed in 14.77s`.
- Production `/healthz`: OK.
- Production active highlights: `23569`.
- Production embeddings: `23569 / 23569`, `100.0%`.
- Production dashboard shell warm timing: about `0.24-0.29s`.
- Production `/dashboard/ui/activity` warm timing: about `0.05s`.
- Production semantic duplicate page remains materialized-cache backed.

## 3. Design Notes

The Minna design pass is already on `main`. Do not restart the old migration
plan from scratch. Future UI work should continue using the existing token and
component conventions in:

- `tailwind.config.js`
- `app/static/css/input.css`
- `app/templates/base.html`
- existing `mn-*` component classes

### 3.1 Guardrails

- Keep the yellow accent scarce: one primary stamp-like action per screen unless
  there is a clear semantic reason.
- Avoid reintroducing blue as a brand color.
- Avoid shadows for normal product UI. Use borders, surface changes, and layout.
- Keep HTMX partials small and independently renderable.
- Keep keyboard shortcuts intact. The shared script is
  `/static/js/keyboard-shortcuts.js`, included once through `_keyboard_shortcuts.html`.

### 3.2 Crimson Pro Exception

The brand stack is intentionally serif-free, but `.highlight-text` keeps
Crimson Pro for book quote bodies. Product chrome should use Inter/Noto Sans JP;
reading-mode highlight text can keep Crimson Pro because it preserves the
voice of the quoted book. This is intentional and is referenced from
`tailwind.config.js`.

## 4. Known Remaining Work

No urgent production blocker is open at closeout.

Useful next work, in priority order:

1. Profile dashboard subwidgets individually on production with a small timing
   middleware or route-level logging, then decide whether tag cloud, cold books,
   or echoes should also become deferred partials.
2. Add a browser-level smoke test for dashboard HTMX swaps so
   `/dashboard/ui/activity` rendering is verified beyond string assertions.
3. Consider static asset versioning for JS/CSS URLs if browser cache staleness
   becomes visible during rapid deploys.
4. Review local-only branches/worktrees before deleting anything:
   `feat/minna-design` in `/Users/chikaki/Development/freewise-kindle` and
   `feat/readwise-api-v2` are not merged into `main`.
5. `ruff` is not installed in the current `uv` environment. Tests pass, but
   lint verification was skipped for that reason.

## 5. Closing Commands Used

```bash
uv run pytest tests/ -q
LOCAL_SRC=/Users/chikaki/Development/freewise \
  bash /Users/chikaki/Development/freewise-qnap-deploy/tools/deploy_qnap.sh
curl -fsS http://192.168.0.171:8063/healthz
git status --short --branch
```

## 6. Do Not Delete Without Review

- `handsoff.md`: this closeout file and design-rationale anchor.
- `/Users/chikaki/Development/freewise-kindle`: separate worktree with local
  `feat/minna-design` history.
- `/Users/chikaki/Development/freewise-qnap-deploy`: production deploy scripts.
- Existing git stashes: they archive old worktree cleanup state.
