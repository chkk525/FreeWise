# Kindle Browser Extension

A Chrome MV3 extension that scrapes the user's own
`https://read.amazon.com/kp/notebook` page from inside their real browser
session and uploads the parsed highlights to a self-hosted FreeWise
instance. Single-user (chkk525 personal fork); not distributed via the
Chrome Web Store.

## Why an extension instead of the QNAP Playwright scraper?

The Playwright headless-Chromium scraper running on QNAP is now reliably
flagged by Amazon's anti-bot heuristics within minutes of fresh login.
Scraping inside the user's own browser uses the same authenticated
session as their normal Kindle reading — no headless detection, no fresh
login mismatch.

The QNAP scraper is **demoted to a monthly fallback** (cron 03:00 JST,
1st of each month). The extension is the daily/on-demand path.

## Server-side wiring

The extension POSTs to a separate hostname so Cloudflare Access does
not gate the API:

| Hostname | Purpose | Auth |
|---|---|---|
| `freewise.chikaki.com` | UI | Cloudflare Access (email/Google OAuth) |
| `freewiseapi.chikaki.com` | API (`/api/v2/*`) | `ApiToken` bearer; no CF Access |

Both hostnames terminate at the same FastAPI container via the same
Cloudflare Tunnel — only the CF Access app boundary differs. The API
hostname is **1 level deep** (`freewiseapi.chikaki.com`, not
`api.freewise.chikaki.com`) so it is covered by Cloudflare's free
Universal SSL certificate without an Advanced Certificate upgrade.

The endpoint:

```
POST https://freewiseapi.chikaki.com/api/v2/imports/kindle
Authorization: Token <value>
Content-Type: application/json
Content-Encoding: gzip          # optional; cuts ~70% off a 1MB export
```

Body: a `KindleExportV1` envelope as defined in
[`shared/kindle-export-v1.schema.json`](../shared/kindle-export-v1.schema.json).
Response: a JSON object with `books_created`, `books_matched`,
`highlights_created`, `highlights_skipped_duplicates`, and
`errors: list[{book_title, reason}]`.

The importer validates the envelope against the strict JSON Schema
(Draft 2020-12) before any DB write. Invalid envelopes return HTTP 400
with the first failing path, not a partial import.

The token used by the extension must carry the `kindle:import` scope
(set on the `apitoken.scopes` column). Tokens with `scopes IS NULL`
are treated as full-access for backwards compatibility.

CORS is configured to accept any `chrome-extension://[a-z0-9]+`
origin. Server-side `ApiToken` auth is the actual security gate.

## Repo layout

```
extensions/kindle-importer/
├── manifest.json          # Chrome MV3 manifest
├── package.json           # vite + vitest + ajv
├── vite.config.ts
├── vitest.config.ts
├── tsconfig.json
├── icons/                 # 16/48/128 PNG (placeholder; replace before public release)
├── src/
│   ├── popup.{html,ts,css}    # toolbar UI: settings + Sync now
│   ├── background.ts          # service worker: tab + port + gzip POST
│   ├── content.ts             # runs on read.amazon.com/kp/notebook
│   └── lib/
│       ├── kindle-extract.ts  # pure DOM extractors
│       ├── selectors.ts       # imports shared/kindle-selectors.json
│       ├── schema-validate.ts # ajv validator over shared schema
│       └── storage.ts         # chrome.storage.local helpers
└── test/
    ├── extract.test.ts
    ├── schema-validate.test.ts
    ├── storage.test.ts
    └── fixtures/notebook-en.html
```

The DOM selectors and JSON Schema live in `shared/` at the repo root so
the Python scraper (monthly fallback) and the TypeScript content script
share a single source of truth.

## Build & install

```sh
cd extensions/kindle-importer
npm install
npm run build      # produces dist/
```

Then:

1. Open `chrome://extensions/`
2. Enable Developer mode (top-right toggle)
3. Click "Load unpacked"
4. Select the `extensions/kindle-importer/dist/` directory

The toolbar shows a placeholder icon. Click it once to open the popup.

## First run

1. Click the toolbar icon → settings form appears.
2. Enter:
   - Server URL: `https://freewiseapi.chikaki.com`
   - API Token: paste a token created at
     `https://freewise.chikaki.com/settings/api-tokens` with the
     `kindle:import` scope.
3. Save. The popup switches to the Sync view.
4. Click **Sync now**. The extension opens a hidden tab on
   `read.amazon.com/kp/notebook`, the content script scrapes book by
   book, and the SW POSTs the gzipped envelope to FreeWise.

If you are not logged into Amazon, the hidden tab will redirect to the
sign-in page. The extension detects this via
`chrome.tabs.onUpdated` watching the final URL and surfaces
"Please log in to read.amazon.com first" in the popup.

## Test

```sh
npm run test       # vitest (DOM extractor + schema + storage)
```

## Cookie upload (fallback path)

When the monthly QNAP scraper's `storage_state.json` (Amazon login
cookie file) expires, refresh it through the dashboard at
`https://freewise.chikaki.com/dashboard/kindle/cookie` instead of
`ssh + scp`. The page validates the upload (size ≤ 100KB, valid JSON,
contains `at-main` cookie on `.amazon.com`) and writes atomically.

To generate a fresh `storage_state.json` on your Mac:

```sh
cd ~/Development/freewise-qnap-kindle
make login
# A browser window opens. Log into Amazon (incl. 2FA).
# Then upload state/kindle/storage_state.json via the dashboard.
```

The upload is rejected with HTTP 409 if a scrape is currently running,
so you cannot mid-flight clobber the file the scraper is reading.

## Error matrix

| Symptom in popup | Cause |
|---|---|
| "Please log in to read.amazon.com first" | Amazon redirected the hidden tab away from `kp/notebook` |
| "Token rejected (401)" | API token unknown or revoked |
| "FreeWise unreachable" | Network / DNS / Cloudflare Tunnel down |
| "HTTP 400: …" | Envelope failed JSON-Schema validation server-side |
| "HTTP 403: Token missing required scope" | Token lacks `kindle:import` |
| "Tab did not finish loading within 60s" | `read.amazon.com` is slow or hung |
| "schema validation failed: …" | Client-side AJV caught a bad envelope before POST |

## Known limitations (v1)

- No background scheduling — sync is manual only. (`chrome.alarms`
  deferred per spec § 2.)
- Chrome / Edge only. No Firefox or Safari.
- Per-book error rows still attempt to scrape but get an empty
  `highlights: []`. Errors surface in the popup result via the
  `errors` array, not as a hard failure.
- The cookie upload UI does not currently include a "verify cookie" /
  live-test button — paste the file, see the parsed status. Live
  verification is fast-follow.
