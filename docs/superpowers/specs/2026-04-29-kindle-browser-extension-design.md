# Kindle Browser Extension — Design Document

| Field | Value |
|---|---|
| Date | 2026-04-29 |
| Author | chikaki |
| Status | Draft (awaiting approval) |
| Branch | `feat/readwise-api-v2` (target for implementation) |
| Audience | Single user, self-hosted FreeWise. **Not for public distribution.** |

---

## 1. Problem & Goal

The current Kindle scraper runs Playwright headless Chromium on QNAP, authenticates with a `storage_state.json` cookie, and scrapes `read.amazon.com/notebook` server-side. As of 2026-04-29 it consistently hangs at "Launching headless Chromium" within minutes of fresh login — Amazon's anti-bot heuristics now flag the headless session almost immediately.

**Goal**: replace the headless-on-server architecture with a browser extension that scrapes inside the user's real Chrome session. The extension reuses the user's existing Amazon login and avoids bot detection because the requests come from a real, interactive browser. The user clicks the extension's toolbar icon to trigger a sync; the extension opens `read.amazon.com/kp/notebook` in a hidden tab, scrapes it, and POSTs the result to a new `/api/v2/imports/kindle` endpoint.

The QNAP scraper is preserved as a monthly fallback rather than deleted, with the `storage_state.json` cookie now uploadable through a new dashboard page (eliminating the current `ssh + rsync` workflow).

---

## 2. Audience & non-goals

**Audience.** Single user (chikaki). FreeWise instance behind Cloudflare Access at `freewise.chikaki.com`. Self-hosted on QNAP NAS.

**Non-goals.**

- Public distribution. No Chrome Web Store, no privacy policy, no localization, no onboarding optimization for strangers.
- Multi-user / multi-account.
- Firefox or Safari support. Chrome / Edge only (both Chromium MV3, single codebase).
- Background automatic scheduling (`chrome.alarms`). Deferred to a possible Phase 2.
- Per-book streaming uploads, real-time progress over WebSocket, push notifications.

---

## 3. Architecture overview

Three independent paths converge on the same `Book` / `Highlight` rows in SQLite:

```
┌──────────────────────────────┐         ┌────────────────────────────────┐
│  Chrome / Edge (user)        │         │  FreeWise                       │
│                              │         │                                 │
│  Browser extension           │  POST   │  api.freewise.chikaki.com       │
│   ・popup (Sync now)         ├─────────▶  /v2/imports/kindle (new)       │
│   ・content script (scrape) ◀┼─ DOM ──▶│   ・ApiToken auth (existing)    │
│   ・background SW            │         │   ・CORS for ext origin         │
│       opens hidden tab       │         │   ・dispatches to existing      │
│       to read.amazon.com     │         │     import_kindle_notebook_json │
└──────────────────────────────┘         │                                 │
                                          │                                 │
┌──────────────────────────────┐         │  freewise.chikaki.com           │
│  Dashboard (Cookie UI, new)  ├─────────▶  /dashboard/kindle/cookie (new) │
│  upload storage_state.json   │ multipart│   ・validate JSON shape         │
└──────────────────────────────┘         │   ・atomic write to             │
                                          │     /share/.../storage_state.json│
                                          │                                 │
┌──────────────────────────────┐         │                                 │
│  QNAP scraper (fallback)     │  cron   │  /imports/kindle/*.json         │
│  ・monthly cron only         ├─────────▶  picked up by existing watcher  │
│  ・dashboard "Scrape now"    │         │                                 │
│  ・unchanged today           │         └─────────────────────────────────┘
└──────────────────────────────┘
```

The extension is the primary path. Cookie upload UI removes the SSH workflow that today's monthly fallback requires. The QNAP scraper remains as a safety net but the daily cron is removed; only manual + monthly automatic invocations remain.

---

## 4. User flow (Phase 1)

**One-time setup** (after installing the unpacked extension):

0a. User opens the popup. Settings tab shows empty `Server URL` and `Token` fields.
0b. In another tab, user generates an API token at `https://freewise.chikaki.com/settings/api-tokens` (existing UI), copies the value.
0c. Returns to the extension popup, pastes `Server URL: https://api.freewise.chikaki.com` and the token. Saves.
0d. Setup is now complete; the popup main view shows the "Sync now" button.

**Sync flow** (every time the user wants to sync):

1. User clicks the FreeWise Kindle Importer icon in the Chrome toolbar.
2. Popup opens. Shows "Sync now" button and last sync result.
3. User clicks "Sync now".
4. Background SW calls `chrome.tabs.create({url: 'https://read.amazon.com/kp/notebook', active: false})`. Hidden tab loads.
5. Content script (URL-matched in manifest) injects, waits for `#kp-notebook-library` to render, then iterates books: clicks each, waits for the right pane to swap, extracts highlights.
6. Content script reports progress via `chrome.runtime.sendMessage({type: 'progress', current: 8, total: 16})` to the SW, which forwards to the popup.
7. When done, content script sends final `KindleExportV1` envelope to SW.
8. SW closes the hidden tab.
9. SW reads `server_url` and `token` from `chrome.storage.local`.
10. SW POSTs `https://api.freewise.chikaki.com/v2/imports/kindle` with `Authorization: Token <value>` and gzipped body.
11. SW pushes result to popup. Popup renders contextual success message (see § 9 First-sync UX).

If the user closes the popup mid-sync, the sync continues in the SW. Reopening the popup shows current state (the SW persists the in-progress flag in `chrome.storage.session`).

---

## 5. Cloudflare Access integration (CRITICAL)

`freewise.chikaki.com` is gated by Cloudflare Access. A `chrome-extension://...` origin sending `fetch()` to `freewise.chikaki.com/api/v2/...` cannot present the `CF_Authorization` cookie (cross-site, SameSite). The Access edge then redirects to the login page; the extension receives an HTML response and JSON parsing fails.

**Resolution**: split the API surface onto a separate subdomain that bypasses Access.

| Hostname | Purpose | Protected by |
|---|---|---|
| `freewise.chikaki.com` | Human-facing UI (dashboard, all `/dashboard/*`, settings) | Cloudflare Access |
| `api.freewise.chikaki.com` | Machine API (`/v2/*`) | ApiToken (FastAPI dependency); CF Access bypassed |

Both hostnames point to the same Cloudflare Tunnel and the same FastAPI app. The split is enforced at Cloudflare Access policy level, not in the application — the FastAPI side serves both, and the existing routers don't need a hostname check (the `api_v2` router is namespaced under `/api/v2/*` regardless of host).

This subdomain split also benefits future API consumers (CLI, mobile, Readwise-compatible third-party clients).

**Setup actions** (recorded for the implementation plan):

1. Cloudflare DNS: add CNAME `api.freewise.chikaki.com` → same Tunnel as `freewise.chikaki.com`.
2. Cloudflare Tunnel (`cloudflared` config on QNAP): add an ingress rule mapping `api.freewise.chikaki.com` to the same backend `http://freewise:8063`.
3. Cloudflare Access: scope existing application to hostname `freewise.chikaki.com` only. The new `api.freewise.chikaki.com` subdomain has no Access application configured, so requests reach the origin unauthenticated at the Cloudflare level. ApiToken auth in FastAPI is the sole gate for the API subdomain.
4. Verify `curl -H "Authorization: Token xxx" https://api.freewise.chikaki.com/v2/highlights` returns JSON, not the Cloudflare Access login HTML.

---

## 6. Browser extension structure

Manifest V3, built with Vite + esbuild. No code obfuscation.

### Files

```
extensions/kindle-importer/
├── manifest.json
├── src/
│   ├── popup.html
│   ├── popup.ts
│   ├── popup.css
│   ├── background.ts          (service worker)
│   ├── content.ts             (runs on read.amazon.com/kp/notebook)
│   └── lib/
│       ├── kindle-extract.ts  (DOM scraping core; pure function)
│       ├── selectors.ts       (auto-generated from shared/)
│       ├── schema-validate.ts (ajv against shared schema)
│       └── storage.ts         (chrome.storage helpers)
├── icons/16.png, 48.png, 128.png  (FreeWise logo derivatives)
├── package.json, vite.config.ts, tsconfig.json
└── README.md                   (developer setup)
```

### `manifest.json` skeleton

```json
{
  "manifest_version": 3,
  "name": "FreeWise Kindle Importer",
  "version": "1.0.0",
  "description": "Sync Kindle highlights to a self-hosted FreeWise.",
  "permissions": ["tabs", "scripting", "storage"],
  "host_permissions": [
    "https://read.amazon.com/*",
    "https://api.freewise.chikaki.com/*"
  ],
  "action": { "default_popup": "popup.html" },
  "background": { "service_worker": "background.js", "type": "module" },
  "content_scripts": [{
    "matches": ["https://read.amazon.com/kp/notebook*"],
    "js": ["content.js"],
    "run_at": "document_idle",
    "all_frames": false
  }],
  "icons": { "16": "icons/16.png", "48": "icons/48.png", "128": "icons/128.png" }
}
```

`host_permissions` is required (not `activeTab`) because the SW opens the read.amazon.com tab itself, not on user click.

### Content script lifecycle (Manifest V3 specifics)

- **Isolated world by default.** DOM reads only; do not rely on Amazon's React internal state. If a selector returns null, retry up to 3 times with 200ms gaps to handle React lazy-mount.
- **Page lifecycle**:
  - Skip when `document.prerendering === true`.
  - Reset state on `pageshow` (bfcache restore).
  - Do not auto-trigger; wait for an explicit `sync` message from the SW (the SW opens the hidden tab and sends the message after `tabs.onUpdated` fires `complete`).
- **No banner UI.** The popup is the user-facing surface. Content script communicates exclusively via `chrome.runtime.sendMessage`.

### Service worker eviction (HIGH)

MV3 SWs evict after ~30s idle. The sync can run for minutes (100 books × ~2s each). Mitigation:

- The SW sends a `sync` message to the content script in the hidden tab and *holds open a port* (`chrome.runtime.connect`). The port keeps the SW alive while the content script is active.
- The actual POST is performed from the SW (not the content script) to keep `Authorization` token out of the Amazon-context script — but the SW only does the POST after the content script has sent the final payload, so the SW's idle window is short-circuited just before the POST.
- If eviction does occur, the SW reattaches via `chrome.tabs.onUpdated` and retries via stored state in `chrome.storage.session`.

### Token storage

`chrome.storage.local` stores `{ server_url, token }`. Token is pasted manually by the user into the popup's settings tab on first install. There is no onboarding handshake.

For a self-hosted single user, the `chrome.storage.local` ergonomics are acceptable. The user generates a token via the existing `/settings/api-tokens` UI on `freewise.chikaki.com` and pastes it into the extension popup once.

---

## 7. FreeWise endpoints

### `POST /api/v2/imports/kindle` (new)

```
Hostname: api.freewise.chikaki.com
Auth: Authorization: Token <value>  (existing api_v2 dependency)
Content-Type: application/json
Content-Encoding: gzip  (optional, supported)
Body: KindleExportV1 envelope (existing schema, unchanged)

Returns 200 + JSON:
{
  "books_created": 0,
  "books_matched": 16,
  "highlights_created": 23,
  "highlights_skipped_duplicates": 118,
  "errors": [
    { "book_title": "Sapiens", "reason": "missing required field 'asin'" }
  ]
}

Returns 401 if token invalid.
Returns 400 if envelope schema invalid.
Returns 422 if envelope partially valid (some books fail).
Returns 500 on unexpected internal error.
```

This endpoint is a thin wrapper. It validates the envelope, then delegates to the existing `import_kindle_notebook_json()` in `app/importers/kindle_notebook.py`. The existing dedup logic (ASIN tag → `(title, author)` → `(text, location)`) is unchanged.

The `errors` array is upgraded from `list[str]` to `list[{book_title, reason}]` to give the popup actionable per-book detail. The internal `KindleImportResult` dataclass is extended; existing call sites (CLI, watcher) need a small migration to consume the new shape.

### `GET /dashboard/kindle/cookie` (new)

Renders Jinja2 template. Shows current cookie status:

- Last modified time (file mtime).
- Cookie domains found (`amazon.com`, `amazon.co.jp`, `read.amazon.com`).
- Whether `at-main` cookie is present.
- File size.

Includes upload form and instructions for generating the file (`make login` on the user's Mac, then download the resulting `state/kindle/storage_state.json`).

### `POST /dashboard/kindle/cookie` (new)

Multipart upload. Server-side validation:

- Content type starts with `application/json` or `application/octet-stream`.
- Body size < 100 KB.
- Parses as JSON.
- Has `cookies` array (Playwright storage_state shape) and (optionally) `origins` array.
- `cookies` array contains at least one entry for `amazon.com` or `amazon.co.jp` domain.
- At least one cookie named `at-main` or `session-token` exists.

On success: atomic write via temp file + `os.replace`. Preserves owner (chowned to `freewise:freewise` so the scraper container can read). Returns updated status JSON.

Concurrency safety: before writing, check `KINDLE_SCRAPE_STATE_FILE` for `running == true` (running scrape). If active, return 409 Conflict. The user can wait or cancel the running scrape via the existing dashboard button.

---

## 8. Shared selector and schema definitions (DRY)

Today the DOM selector list lives in `scrapers/kindle/scraper.py`. A second copy in `content.ts` would silently drift. Move them to a single source.

```
shared/
├── kindle-selectors.json      (selectors for read.amazon.com DOM)
└── kindle-export-v1.schema.json  (JSON Schema for the envelope)
```

`kindle-selectors.json`:

```json
{
  "library_container": ["#kp-notebook-library", "#library-section", "div.kp-notebook-library"],
  "library_row": "div.kp-notebook-library-each-book",
  "annotation_container": ["#kp-notebook-annotations", "#annotations", "div.kp-notebook-annotation-list"],
  "annotation_row": "div.a-row.a-spacing-base.a-spacing-top-medium",
  "highlight_text": "span#highlight",
  "note_text": "span#note",
  "highlight_color_prefix": "kp-notebook-highlight-",
  "location_text": "span#kp-annotation-location",
  "header_note_label": "span#annotationNoteHeader",
  "book_title": "h2.kp-notebook-searchable",
  "book_author": "p.kp-notebook-searchable",
  "book_cover_image": "img.kp-notebook-cover-image"
}
```

Python loads the JSON at import time (`scrapers/kindle/scraper.py` refactor — drops hardcoded constants, reads from the shared file). Vite inlines it into the extension bundle at build time.

`kindle-export-v1.schema.json`: standard JSON Schema 2020-12 covering the envelope from `docs/KINDLE_JSON_SCHEMA.md`. Both sides validate:

- JS side: `ajv` validates before POST. Errors abort the sync with a "internal extraction error" message in the popup.
- Python side: existing `_validate_envelope()` continues to check `schema_version` and `source`; supplement with full schema validation (jsonschema package) for thorough server-side check.

This catches the regression class where the JS side emits a slightly malformed envelope and the importer's lenient parser silently drops fields.

---

## 9. First-sync UX & messaging

The user's existing DB has 23,571 highlights. The first sync after installing the extension will likely produce mostly duplicates. This must read as success, not failure.

Popup result messaging, based on `KindleImportResult`:

| Condition | Message |
|---|---|
| `highlights_created > 0` and `highlights_skipped_duplicates == 0` | ✓ Synced N highlights from M books |
| `highlights_created > 0` and `skipped > 0` | ✓ Added N new · M already in your library |
| `highlights_created == 0` and `skipped > 0` | ✓ Library up to date (no changes since last sync) |
| `highlights_created == 0` and `skipped == 0` | ⚠ No highlights found. Are you logged into Amazon? |
| `errors.length > 0` (partial) | ⚠ Synced N · M books failed (see details) |

Progress bar during scan: "Scanning N of M books..." with cancel button.

---

## 10. Coverage & limitations

**What syncs.**

- Books purchased from Amazon Kindle Store (any region; merged accounts work via `read.amazon.com`).
- Highlights, notes, locations, and page numbers (where Amazon exposes them).
- Book metadata: title, author, ASIN, cover URL.

**What doesn't sync.**

- Personal documents (send-to-kindle, sideloaded PDFs). Not in `read.amazon.com/notebook`.
- Highlights truncated by Amazon's per-book copyright export limit (~10-20% of book text). The extension respects whatever the page shows.
- Page numbers for fixed-layout books where Amazon doesn't expose them.

**Fallback for personal documents.** The existing `My Clippings.txt` upload flow at `/import/ui/kindle` continues to work. README documents it as the personal-document path.

---

## 11. Error handling matrix

| Scenario | Detection | UX response |
|---|---|---|
| User not logged in to Amazon | Content script: no `#kp-notebook-library` after 10s + login form found | Popup: "Please log in to read.amazon.com first." Button: "Open Amazon login". |
| FreeWise unreachable | `fetch` throws `TypeError` (DNS/network) or 5xx | Popup: "FreeWise unreachable. Server: \<url\>". Button: "Retry" + "Open settings". |
| Token rejected | 401 response | Popup: "Token expired or revoked. Re-paste in settings." Button: "Open settings" + "Open token page on FreeWise". |
| CORS rejected by browser | `fetch` throws `TypeError: NetworkError when attempting to fetch resource` | Popup: "API CORS misconfigured. Check api.freewise.chikaki.com server." Console error with detail. |
| Schema validation fails (JS-side) | ajv rejects envelope | Popup: "Internal extraction error: \<field path\>". Console: full JSON for debugging. Sync aborts before POST. |
| Amazon DOM changed | All selector candidates fail | Popup: "Amazon changed their notebook page format. Update extension." Console: which selectors failed. |
| Hidden tab fails to load | `tabs.onUpdated` doesn't fire `complete` within 60s | Popup: "Couldn't open Amazon page. Try opening read.amazon.com manually first to verify your session." |
| Scan cancelled by user | Cancel button in popup → SW sends `abort` to content | Popup: "Sync cancelled.". SW closes hidden tab. |
| Partial scrape (some books fail) | Per-book try/catch in content script | Popup: "Synced N of M books. Failed: \<title\>, \<title\>". Detail in expandable section. |
| Cookie upload: invalid JSON | Server JSON parse fails | Cookie page: "File is not valid JSON." |
| Cookie upload: wrong shape | Validation: missing `cookies` array | Cookie page: "File is not a Playwright storage_state.json. Run `make login` on your Mac." |
| Cookie upload: scraper running | `scrape_state.json` shows `running` | Cookie page: 409 + "A scrape is currently running. Wait or cancel it first." |

---

## 12. Performance & memory

Empirical baseline from 2026-04-26 successful run:

- 16 books, 141 highlights, ~83s wall time.
- Peak Chromium memory: ~10 MB extension overhead.
- Final JSON payload: ~120 KB.

Linear extrapolation to 100 books / 1000 highlights:

- ~8-10 minutes wall time. Acceptable as a manual-trigger flow but borderline.
- ~1 MB JSON.

**Optimizations.**

- gzip request body via `CompressionStream` (Compression Streams API, Chrome 80+). Expected 70% reduction.
- Server-side: FastAPI accepts `Content-Encoding: gzip` for request bodies — middleware needed (the standard `GZipMiddleware` is for responses; request decompression requires a small custom middleware).
- Progress UI prevents user perception of "frozen".
- Cancel button limits damage.

If 100+ book libraries become a real bottleneck, **per-book streaming POST** is the Phase 2 mitigation. For now, accept the 10-minute ceiling.

---

## 13. Storage & atomic operations

Cookie upload writes to `${KINDLE_STATE_PATH}/storage_state.json` (default `/share/Container/freewise/state/storage_state.json`). The scraper container reads this path read-only.

Atomic write sequence:

1. Verify `KINDLE_SCRAPE_STATE_FILE` does not show `running == true`. Return 409 if active.
2. Validate uploaded JSON.
3. Write to `storage_state.json.tmp.<pid>` in the same directory.
4. `os.replace(tmp_path, storage_state.json)` — atomic on POSIX, same filesystem.
5. `os.chown(path, freewise_uid, freewise_gid)` — preserves ownership the scraper container needs.
6. Return updated status JSON.

If the rename fails partway, the temp file remains and the next upload cleans it up. The scraper container never sees a partial file.

---

## 14. Testing strategy

### Python (existing + new)

- `tests/api_v2/test_kindle_import.py` (new). FastAPI TestClient. Cases:
  - Valid envelope, valid token → 200, expected counts.
  - Missing token → 401.
  - Invalid token → 401.
  - Schema major mismatch → 400.
  - Partial errors → 422 with `errors` array.
  - gzipped body → decompression succeeds.
- `tests/services/test_kindle_cookie.py` (new). Unit tests for validation + atomic write.
  - Valid `storage_state.json` → write succeeds.
  - Invalid JSON → ValueError raised.
  - Wrong shape → ValueError.
  - Running scrape → 409 raised.
  - Atomic write idempotency.
- `tests/importers/test_kindle_notebook.py` (existing). Extended for new `errors: list[dict]` shape.

### JavaScript (extension)

- `extensions/kindle-importer/test/extract.test.ts` (Vitest). Feed Amazon HTML fixtures (saved snapshots from real `read.amazon.com/kp/notebook`); assert extracted `KindleExportV1` matches expected JSON.
- Fixtures: `extensions/kindle-importer/test/fixtures/{en,jp}/library.html` + per-book annotation snapshots. Sync these from real pages periodically as Amazon changes the DOM.

### Manual E2E

- Install unpacked extension in Chrome.
- Click icon → Sync now → observe full flow against the real `freewise.chikaki.com`.
- Verify result: highlight count in DB matches Amazon's notebook count.
- Verify popup messaging matches § 9.
- Verify cookie upload page renders and validates correctly.

### Pre-release dogfood

After all automated tests pass, dogfood for 1 week before promoting to "stable" (in this case, "consider it shipped"). Manual checklist in implementation plan.

---

## 15. File layout (new + modified)

```
freewise/  (chkk525/FreeWise, branch feat/readwise-api-v2)
├── extensions/                              NEW
│   └── kindle-importer/
│       ├── manifest.json
│       ├── package.json
│       ├── vite.config.ts
│       ├── tsconfig.json
│       ├── src/
│       │   ├── popup.html
│       │   ├── popup.ts
│       │   ├── popup.css
│       │   ├── background.ts
│       │   ├── content.ts
│       │   └── lib/{kindle-extract,selectors,schema-validate,storage}.ts
│       ├── icons/{16,48,128}.png
│       ├── test/{extract.test.ts,fixtures/}
│       └── README.md
├── shared/                                  NEW
│   ├── kindle-selectors.json
│   └── kindle-export-v1.schema.json
├── app/
│   ├── api_v2/
│   │   ├── kindle_import.py                 NEW (POST /v2/imports/kindle)
│   │   ├── auth.py                          (existing, no changes)
│   │   └── router.py                        MODIFY (mount kindle_import)
│   ├── routers/
│   │   ├── dashboard.py                     MODIFY (add cookie routes)
│   │   └── kindle_cookie.py                 NEW (cookie upload page + endpoint)
│   ├── services/
│   │   └── kindle_cookie.py                 NEW (storage_state validation + atomic write)
│   └── templates/
│       ├── kindle_cookie.html               NEW
│       └── _kindle_cookie_status.html       NEW (HTMX partial)
├── scrapers/
│   └── kindle/
│       └── scraper.py                       MODIFY (load selectors from shared/)
├── tests/
│   ├── api_v2/
│   │   └── test_kindle_import.py            NEW
│   ├── services/
│   │   └── test_kindle_cookie.py            NEW
│   └── importers/
│       └── test_kindle_notebook.py          MODIFY (errors list[dict] shape)
└── docs/
    ├── KINDLE_JSON_SCHEMA.md                MODIFY (note errors shape, link extension)
    └── superpowers/specs/
        └── 2026-04-29-kindle-browser-extension-design.md   (THIS FILE)
```

---

## 16. QNAP scraper sunset (deferred)

Not part of v1. Recorded so it doesn't get forgotten:

> **Sunset criteria.** If the extension + cookie UI fully covers needs for 6 months (no scraper container invocations, no fallback button presses, no cookie expiry incidents that the UI couldn't handle), retire `scrapers/kindle/`, `Dockerfile.kindle`, `docker-compose.kindle.yml`, the dashboard `Scrape now` button, the `kindle_scrape_trigger.py` service, the `KINDLE_SCRAPE_CMD` env var family, and the QNAP `/share/Container/freewise/kindle/` deploy directory. Update README to reflect extension-only architecture.

Until then: the daily QNAP cron is removed (running today only causes wasted resource on hung Amazon sessions). The dashboard button stays as a manual fallback.

---

## 17. Implementation phases (rough effort)

Implementation plan (the next document) will detail each step. Rough sketch:

| Phase | Step | LOC est. | Dependencies |
|---|---|---|---|
| Infra | A. Cloudflare subdomain `api.freewise.chikaki.com` | infra only | — |
| Backend | B. Shared selectors JSON, refactor `scraper.py` | ~60 | A |
| Backend | C. JSON Schema file + Python validator | ~80 | B |
| Backend | D. `POST /api/v2/imports/kindle` + tests | ~150 | C |
| Backend | E. CORS middleware on api subdomain + ApiToken scope | ~60 | A, D |
| Backend | F. `/dashboard/kindle/cookie` page + endpoint + tests | ~200 | — |
| Extension | G. Skeleton: manifest, popup, background, vite | ~150 | — |
| Extension | H. Content script DOM extraction + schema validation | ~300 | B, C |
| Extension | I. Popup UI + sync flow | ~200 | G |
| Extension | J. Background SW: tab management + POST + gzip | ~150 | D, G |
| QA | K. Manual E2E + dogfood week | — | all |

Total: ~1350 LOC new + ~50 LOC modified. Estimate 2-3 days of focused work.

---

## 18. Decision log

Recorded for future reference:

- Trigger model: extension toolbar icon click → hidden tab scrape. (Phase 1)
  - Rationale: user rarely visits `read.amazon.com/notebook` by hand; banner-on-page would die unused.
- Auth: manual token paste in popup settings.
  - Rationale: single user, no need for `externally_connectable` handshake.
- Sync model: full export every time.
  - Rationale: server-side `(text, location)` dedup makes this idempotent and stateless.
- Distribution: unpacked load only.
  - Rationale: single user, no Web Store overhead.
- Browser: Chrome / Edge only.
  - Rationale: same Chromium MV3 codebase covers both; Firefox / Safari not needed.
- Fallback: keep QNAP scraper as monthly cron + manual button + new cookie upload UI.
  - Rationale: safety net for Amazon DOM regressions or extension bugs.
- Subdomain split for API: `api.freewise.chikaki.com` bypasses Cloudflare Access.
  - Rationale: only way to make extension `fetch()` work without rewriting CF Access for cookie sharing.

---

## 19. Open questions for implementation

- Exact Cloudflare Tunnel ingress config (need to inspect `cloudflared` setup on QNAP).
- Where to source the FreeWise icon for extension (existing `app/static/` has favicons; resize to 16/48/128).
- Whether to add a "Verify cookie" button in the cookie upload UI that does a live test scrape (deferred to v1.1; spec section in implementation plan).
- Whether to gzip-compress responses from `/v2/imports/kindle` (the existing `GZipMiddleware` should already handle this; verify).
