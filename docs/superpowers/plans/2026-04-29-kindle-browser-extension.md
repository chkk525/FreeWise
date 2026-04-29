# Kindle Browser Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the failing QNAP headless Playwright scraper with a Chrome MV3 browser extension that scrapes `read.amazon.com/kp/notebook` inside the user's real browser session and POSTs the results to a new `/api/v2/imports/kindle` endpoint, plus a dashboard UI for uploading the `storage_state.json` cookie used by the surviving monthly fallback scraper.

**Architecture:** Extension → hidden tab → DOM scrape → POST → reuse existing `import_kindle_notebook_json()` importer. Subdomain split (`freewiseapi.chikaki.com`) bypasses Cloudflare Access. DRY achieved by moving Python scraper into the main FreeWise repo so a single `shared/` directory holds the DOM selectors and JSON Schema used by both Python and TypeScript.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, SQLite (server). TypeScript + Vite + Vitest + ajv (extension). Manifest V3, Chrome / Edge only.

**Reference spec:** `docs/superpowers/specs/2026-04-29-kindle-browser-extension-design.md`

---

## File map

| Path | Status | Responsibility |
|---|---|---|
| `scrapers/kindle/` | MOVED IN (from freewise-qnap-deploy) | Python scraper, used as monthly fallback |
| `tools/kindle_*.sh` | MOVED IN | Login + scrape shell wrappers |
| `Dockerfile.kindle` | MOVED IN | Scraper container image |
| `docker-compose.kindle.yml` | MOVED IN | Compose for one-shot scraper |
| `shared/kindle-selectors.json` | NEW | Single source of truth for DOM selectors |
| `shared/kindle-export-v1.schema.json` | NEW | JSON Schema for the import envelope |
| `app/api_v2/kindle_import.py` | NEW | `POST /api/v2/imports/kindle` |
| `app/api_v2/router.py` | MODIFY | Mount the new sub-router |
| `app/middleware/gzip_request.py` | NEW | Decompress incoming `Content-Encoding: gzip` bodies |
| `app/main.py` | MODIFY | Register middleware + CORS |
| `app/services/kindle_cookie.py` | NEW | Validate + atomic-write `storage_state.json` |
| `app/routers/kindle_cookie.py` | NEW | `GET/POST /dashboard/kindle/cookie` |
| `app/templates/kindle_cookie.html` | NEW | Cookie upload page |
| `app/templates/_kindle_cookie_status.html` | NEW | HTMX status partial |
| `app/models.py` | MODIFY | Add `scopes` column to `ApiToken` |
| `app/api_v2/auth.py` | MODIFY | Optional scope check |
| `app/importers/kindle_notebook.py` | MODIFY | `KindleImportResult.errors` becomes `list[dict]`, schema validation |
| `scrapers/kindle/scraper.py` | MODIFY | Load selectors from `shared/kindle-selectors.json` |
| `extensions/kindle-importer/` | NEW | Browser extension (Vite + TypeScript) |
| `tests/api_v2/test_kindle_import.py` | NEW | Endpoint tests |
| `tests/middleware/test_gzip_request.py` | NEW | Middleware tests |
| `tests/services/test_kindle_cookie.py` | NEW | Cookie service tests |
| `tests/routers/test_kindle_cookie_route.py` | NEW | Cookie route tests |
| `tests/importers/test_kindle_notebook.py` | MODIFY | New error shape |
| `tests/conftest.py` | (existing) | TestClient fixture, db session |

---

# Phase 0 — Repo consolidation

Mechanical file moves from `freewise-qnap-deploy` into the main FreeWise repo. Phase 0 is not TDD — it is a refactor whose correctness is verified by re-running the existing scraper test suite after the move.

### Task 0.1: Move `scrapers/kindle/` into the main repo

**Files:**
- Move from: `/Users/chikaki/Development/freewise-qnap-kindle/scrapers/kindle/` → `/Users/chikaki/Development/freewise/scrapers/kindle/`

- [ ] **Step 1: Verify source state**

```bash
ls /Users/chikaki/Development/freewise-qnap-kindle/scrapers/kindle/
```

Expected output: `__init__.py __main__.py cli.py models.py scraper.py fixtures/ tests/`

- [ ] **Step 2: Copy into main repo**

```bash
mkdir -p /Users/chikaki/Development/freewise/scrapers
cp -R /Users/chikaki/Development/freewise-qnap-kindle/scrapers/kindle \
      /Users/chikaki/Development/freewise/scrapers/kindle
```

- [ ] **Step 3: Verify Python imports work in the new location**

```bash
cd /Users/chikaki/Development/freewise
.venv/bin/python -c "from scrapers.kindle import scraper; print(scraper.NOTEBOOK_URL)"
```

Expected: `https://read.amazon.com/kp/notebook` (or similar — confirms import path resolves).

- [ ] **Step 4: Run scraper's own pytest suite from main repo**

```bash
cd /Users/chikaki/Development/freewise
.venv/bin/python -m pytest scrapers/kindle/tests/ -q
```

Expected: all green.

- [ ] **Step 5: Delete originals from deploy repo**

```bash
rm -rf /Users/chikaki/Development/freewise-qnap-kindle/scrapers
```

- [ ] **Step 6: Commit (main repo)**

```bash
cd /Users/chikaki/Development/freewise
git add scrapers/
git commit -m "feat(kindle): consolidate scrapers/kindle from freewise-qnap-deploy

Phase 0 of the browser-extension migration. Moves the Python Playwright
scraper into the main repo so the future shared/ directory can be a
single source of truth for DOM selectors used by both the Python
scraper (monthly fallback) and the TypeScript content script."
```

- [ ] **Step 7: Commit (deploy repo)**

```bash
cd /Users/chikaki/Development/freewise-qnap-kindle
git add -A
git commit -m "chore: scrapers/kindle moved to chkk525/FreeWise main repo

Part of the browser-extension migration. The deploy repo now only
holds deploy orchestration. Scraper code lives with the FastAPI app."
```

### Task 0.2: Move kindle shell tools

**Files:**
- Move from: `/Users/chikaki/Development/freewise-qnap-kindle/tools/{kindle_dl.sh, kindle_login.sh, kindle_check_state.sh, install_kindle_cron.sh, kindle_notify.sh}` → `/Users/chikaki/Development/freewise/tools/`

- [ ] **Step 1: Identify scripts to move**

```bash
ls /Users/chikaki/Development/freewise-qnap-kindle/tools/kindle*.sh \
   /Users/chikaki/Development/freewise-qnap-kindle/tools/install_kindle_cron.sh
```

- [ ] **Step 2: Create destination, copy**

```bash
mkdir -p /Users/chikaki/Development/freewise/tools
cp /Users/chikaki/Development/freewise-qnap-kindle/tools/kindle_dl.sh \
   /Users/chikaki/Development/freewise-qnap-kindle/tools/kindle_login.sh \
   /Users/chikaki/Development/freewise-qnap-kindle/tools/kindle_check_state.sh \
   /Users/chikaki/Development/freewise-qnap-kindle/tools/install_kindle_cron.sh \
   /Users/chikaki/Development/freewise-qnap-kindle/tools/kindle_notify.sh \
   /Users/chikaki/Development/freewise/tools/ 2>/dev/null || true
chmod +x /Users/chikaki/Development/freewise/tools/kindle_*.sh \
         /Users/chikaki/Development/freewise/tools/install_kindle_cron.sh
ls -la /Users/chikaki/Development/freewise/tools/kindle_dl.sh
```

Expected: `-rwxr-xr-x ... kindle_dl.sh`

- [ ] **Step 3: Verify path references in `kindle_dl.sh`**

Open `/Users/chikaki/Development/freewise/tools/kindle_dl.sh`. Verify:

```bash
grep -n 'APP_ROOT\|docker-compose\|scrapers/\|tools/' /Users/chikaki/Development/freewise/tools/kindle_dl.sh
```

Expected pattern: every absolute path is built from `${APP_ROOT}` (e.g. `${APP_ROOT}/docker-compose.kindle.yml`). If any line hardcodes `/share/Container/freewise/kindle/...` or `${REPO_DIR}/scrapers/...`, replace it with `${APP_ROOT}/...` so the script works regardless of which repo it runs from. If no hardcoded paths are found, no edit needed.

- [ ] **Step 4: Delete originals from deploy repo**

```bash
rm /Users/chikaki/Development/freewise-qnap-kindle/tools/kindle_*.sh \
   /Users/chikaki/Development/freewise-qnap-kindle/tools/install_kindle_cron.sh
```

- [ ] **Step 5: Commit (both repos)**

```bash
cd /Users/chikaki/Development/freewise
git add tools/
git commit -m "feat(kindle): consolidate kindle shell tools from freewise-qnap-deploy"

cd /Users/chikaki/Development/freewise-qnap-kindle
git add -A
git commit -m "chore: kindle tools moved to chkk525/FreeWise main repo"
```

### Task 0.3: Move `Dockerfile.kindle` and `docker-compose.kindle.yml`

**Files:**
- Move from: `freewise-qnap-deploy/Dockerfile.kindle` → `freewise/Dockerfile.kindle`
- Move from: `freewise-qnap-deploy/docker-compose.kindle.yml` → `freewise/docker-compose.kindle.yml`

- [ ] **Step 1: Copy**

```bash
cp /Users/chikaki/Development/freewise-qnap-kindle/Dockerfile.kindle \
   /Users/chikaki/Development/freewise/Dockerfile.kindle
cp /Users/chikaki/Development/freewise-qnap-kindle/docker-compose.kindle.yml \
   /Users/chikaki/Development/freewise/docker-compose.kindle.yml
```

- [ ] **Step 2: Verify scraper container build context references work**

```bash
grep -n 'COPY\|context\|build' /Users/chikaki/Development/freewise/Dockerfile.kindle \
                                /Users/chikaki/Development/freewise/docker-compose.kindle.yml
```

The Dockerfile's `COPY scrapers/` lines now resolve correctly because `scrapers/` is in the same repo. No edit expected.

- [ ] **Step 3: Delete originals**

```bash
rm /Users/chikaki/Development/freewise-qnap-kindle/Dockerfile.kindle \
   /Users/chikaki/Development/freewise-qnap-kindle/docker-compose.kindle.yml
```

- [ ] **Step 4: Commit (both repos)**

```bash
cd /Users/chikaki/Development/freewise
git add Dockerfile.kindle docker-compose.kindle.yml
git commit -m "feat(kindle): consolidate Dockerfile.kindle + compose"

cd /Users/chikaki/Development/freewise-qnap-kindle
git add -A
git commit -m "chore: Dockerfile.kindle moved to chkk525/FreeWise main repo"
```

### Task 0.4: Update QNAP deploy script to expect scraper code in main repo

**Files:**
- Modify: `/Users/chikaki/Development/freewise-qnap-kindle/tools/deploy_kindle_qnap.sh`

- [ ] **Step 1: Inspect current rsync source**

```bash
grep -n 'rsync\|scrapers\|tools' /Users/chikaki/Development/freewise-qnap-kindle/tools/deploy_kindle_qnap.sh
```

- [ ] **Step 2: Update the rsync source path**

The deploy script currently rsyncs from `${REPO_DIR}/scrapers/`. Change it to fetch from the main FreeWise repo's tarball (matching the pattern in `tools/deploy_qnap.sh`).

Open the file and replace:

```bash
rsync -az --delete \
  --exclude='__pycache__' \
  ${REPO_DIR}/scrapers/ ${QNAP_HOST}:${APP_ROOT}/scrapers/
```

with:

```bash
echo "[2/5] Fetching kindle scraper sources (from main FreeWise tarball)"
ssh "${QNAP_HOST}" "
  cd ${APP_ROOT}
  curl -fsSL https://github.com/chkk525/FreeWise/archive/refs/heads/main.tar.gz \
    -o /tmp/freewise-main.tar.gz
  tar xzf /tmp/freewise-main.tar.gz \
    --strip-components=1 \
    --wildcards 'FreeWise-main/scrapers/*' \
                'FreeWise-main/tools/kindle_*.sh' \
                'FreeWise-main/Dockerfile.kindle' \
                'FreeWise-main/docker-compose.kindle.yml'
"
```

- [ ] **Step 3: Commit (deploy repo)**

```bash
cd /Users/chikaki/Development/freewise-qnap-kindle
git add tools/deploy_kindle_qnap.sh
git commit -m "fix(deploy): pull kindle scraper from main FreeWise repo

Phase 0 of the browser-extension migration consolidated the scraper
code into the main repo. The deploy script now fetches it from there
instead of expecting it in this deploy repo."
```

---

# Phase A — Cloudflare subdomain (infra)

This phase is performed via the Cloudflare API (no code is committed; verification is via `curl`).

> **Note (executed 2026-04-29):** Originally specified `api.freewise.chikaki.com`, but Cloudflare's free Universal SSL only covers `chikaki.com` + `*.chikaki.com` (one level). A 2-level subdomain would need an Advanced Certificate ($10/mo). Renamed to `freewiseapi.chikaki.com` (1-level) — same security model (separate hostname → no CF Access), zero cost.

### Task A.1: Add DNS + Tunnel ingress for `freewiseapi.chikaki.com`

- [x] **Step 1: Identify Account/Zone/Tunnel IDs via API**

```bash
export CF_API_TOKEN=<token-with-Zone:Read,Zone:DNS:Edit,Account:Cloudflare-Tunnel:Edit>
# Zone (account_id is in the zone metadata)
curl -s "https://api.cloudflare.com/client/v4/zones?name=chikaki.com" \
  -H "Authorization: Bearer $CF_API_TOKEN" | jq '.result[] | {id,account:.account.id}'
# Tunnels
curl -s "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/cfd_tunnel?is_deleted=false" \
  -H "Authorization: Bearer $CF_API_TOKEN" | jq '.result[] | {id,name}'
```

Outcome: ZONE_ID=`dae9c9ba553b003b9f043c074f6e54cb`, ACCOUNT_ID=`b8c1de77334ebcda42b581fcbe19b7ca`, TUNNEL_ID=`c1ccecab-7e9d-4882-9c7f-9b3380c611e0` (`freewise-qnap`).

- [x] **Step 2: Inspect current ingress (DO NOT clobber)**

```bash
curl -s "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/cfd_tunnel/$TUNNEL_ID/configurations" \
  -H "Authorization: Bearer $CF_API_TOKEN" | jq .result.config.ingress
```

Existing: single rule `freewise.chikaki.com → http://freewise:8063` plus `http_status:404` catchall.

- [x] **Step 3: Create CNAME `freewiseapi.chikaki.com`**

```bash
curl -s -X POST "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records" \
  -H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json" \
  --data '{"type":"CNAME","name":"freewiseapi","content":"<TUNNEL_ID>.cfargotunnel.com","proxied":true,"ttl":1}'
```

- [x] **Step 4: Update tunnel ingress (preserving existing rules + catchall)**

```bash
curl -s -X PUT "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/cfd_tunnel/$TUNNEL_ID/configurations" \
  -H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json" \
  --data '{"config":{"ingress":[
    {"hostname":"freewise.chikaki.com","service":"http://freewise:8063"},
    {"hostname":"freewiseapi.chikaki.com","service":"http://freewise:8063"},
    {"service":"http_status:404"}
  ],"warp-routing":{"enabled":false}}}'
```

- [x] **Step 5: Confirm CF Access app is bare-hostname only**

```bash
curl -s "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/access/apps" \
  -H "Authorization: Bearer $CF_API_TOKEN" | jq '.result[] | {name, self_hosted_domains}'
```

The `freewise` app has `self_hosted_domains: ["freewise.chikaki.com"]` (no wildcard) — `freewiseapi.chikaki.com` is automatically uncovered. No edit needed.

- [x] **Step 6: Verify**

```bash
# Backend reaches: 200 with healthz JSON (CF Access not applied)
curl -i https://freewiseapi.chikaki.com/healthz | head -5
# Sanity: bare host still gated by Access (302 to login)
curl -o /dev/null -s -w "%{http_code} %{redirect_url}\n" https://freewise.chikaki.com/dashboard
```

Result (executed 2026-04-29): `freewiseapi.chikaki.com/healthz` → 200; `freewise.chikaki.com/dashboard` → 302 to `chikaki.cloudflareaccess.com`. Phase A complete.

(No commit — infra change.)

---

# Phase B — Shared selectors

### Task B.1: Create `shared/kindle-selectors.json`

**Files:**
- Create: `shared/kindle-selectors.json`

- [ ] **Step 1: Create the file**

```bash
mkdir -p shared
```

```json
{
  "library_container": [
    "#kp-notebook-library",
    "#library-section",
    "div.kp-notebook-library"
  ],
  "library_row": "div.kp-notebook-library-each-book",
  "annotation_container": [
    "#kp-notebook-annotations",
    "#annotations",
    "div.kp-notebook-annotation-list"
  ],
  "annotation_row": "div.a-row.a-spacing-base.a-spacing-top-medium",
  "highlight_text": "span#highlight",
  "note_text": "span#note",
  "highlight_color_prefix": "kp-notebook-highlight-",
  "location_text": "span#kp-annotation-location",
  "header_note_label": "span#annotationNoteHeader",
  "book_title": "h2.kp-notebook-searchable",
  "book_author": "p.kp-notebook-searchable",
  "book_cover_image": "img.kp-notebook-cover-image",
  "notebook_url": "https://read.amazon.com/kp/notebook"
}
```

- [ ] **Step 2: Commit**

```bash
git add shared/kindle-selectors.json
git commit -m "feat(shared): kindle DOM selectors as single source of truth

Will be loaded by both scrapers/kindle/scraper.py (monthly fallback)
and the new TypeScript content script in the browser extension."
```

### Task B.2: Refactor `scrapers/kindle/scraper.py` to load selectors from JSON

**Files:**
- Modify: `scrapers/kindle/scraper.py`
- Test: `scrapers/kindle/tests/test_selectors_load.py` (new)

- [ ] **Step 1: Write the failing test**

Create `scrapers/kindle/tests/test_selectors_load.py`:

```python
"""Verify scraper loads its selector list from the shared JSON file."""
from __future__ import annotations

import json
from pathlib import Path

from scrapers.kindle import scraper


REPO_ROOT = Path(__file__).resolve().parents[3]
SHARED_JSON = REPO_ROOT / "shared" / "kindle-selectors.json"


def test_scraper_uses_shared_library_container_selectors():
    expected = json.loads(SHARED_JSON.read_text())["library_container"]
    assert tuple(scraper.LIBRARY_CONTAINER_SELECTORS) == tuple(expected)


def test_scraper_uses_shared_library_row_selector():
    expected = json.loads(SHARED_JSON.read_text())["library_row"]
    assert scraper.LIBRARY_ROW_SELECTOR == expected


def test_scraper_uses_shared_notebook_url():
    expected = json.loads(SHARED_JSON.read_text())["notebook_url"]
    assert scraper.NOTEBOOK_URL == expected
```

- [ ] **Step 2: Run test to confirm failure**

```bash
.venv/bin/python -m pytest scrapers/kindle/tests/test_selectors_load.py -v
```

Expected: tests pass for the values that are currently hardcoded equal to the JSON, fail for any drift. (If they all pass, the hardcoded values happen to match the JSON we wrote — proceed to step 3 to make them load dynamically anyway, then re-run.)

- [ ] **Step 3: Refactor `scraper.py` to load from JSON**

Open `scrapers/kindle/scraper.py`. Replace the hardcoded selector constants near the top of the file:

```python
NOTEBOOK_URL = "https://read.amazon.com/kp/notebook"

LIBRARY_CONTAINER_SELECTORS: tuple[str, ...] = (
    "#kp-notebook-library",
    "#library-section",
    "div.kp-notebook-library",
)
LIBRARY_ROW_SELECTOR = "div.kp-notebook-library-each-book"
# ... etc
```

with:

```python
import json as _json
from pathlib import Path as _Path

_SHARED_DIR = _Path(__file__).resolve().parents[2] / "shared"
_SELECTORS = _json.loads((_SHARED_DIR / "kindle-selectors.json").read_text())

NOTEBOOK_URL: str = _SELECTORS["notebook_url"]
LIBRARY_CONTAINER_SELECTORS: tuple[str, ...] = tuple(_SELECTORS["library_container"])
LIBRARY_ROW_SELECTOR: str = _SELECTORS["library_row"]
ANNOTATIONS_CONTAINER_SELECTORS: tuple[str, ...] = tuple(_SELECTORS["annotation_container"])
ANNOTATION_ROW_SELECTOR: str = _SELECTORS["annotation_row"]
HIGHLIGHT_TEXT_SELECTOR: str = _SELECTORS["highlight_text"]
NOTE_TEXT_SELECTOR: str = _SELECTORS["note_text"]
HIGHLIGHT_COLOR_PREFIX: str = _SELECTORS["highlight_color_prefix"]
LOCATION_TEXT_SELECTOR: str = _SELECTORS["location_text"]
HEADER_NOTE_LABEL_SELECTOR: str = _SELECTORS["header_note_label"]
```

- [ ] **Step 4: Run all scraper tests**

```bash
.venv/bin/python -m pytest scrapers/kindle/tests/ -v
```

Expected: all green, including the new selector-load tests.

- [ ] **Step 5: Commit**

```bash
git add scrapers/kindle/scraper.py scrapers/kindle/tests/test_selectors_load.py
git commit -m "refactor(scraper): load DOM selectors from shared/kindle-selectors.json

Replaces hardcoded constants with a single source of truth that the
upcoming TypeScript content script will also consume."
```

---

# Phase C — JSON Schema for the import envelope

### Task C.1: Add `jsonschema` dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add to deps**

Open `pyproject.toml`. In the `[dependency-groups] dev` list, add:

```toml
    "jsonschema>=4.23.0",
```

- [ ] **Step 2: Sync deps**

```bash
uv sync
```

- [ ] **Step 3: Verify**

```bash
.venv/bin/python -c "import jsonschema; print(jsonschema.__version__)"
```

Expected: `4.x.x`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add jsonschema dependency for KindleExportV1 validation"
```

### Task C.2: Create `shared/kindle-export-v1.schema.json`

**Files:**
- Create: `shared/kindle-export-v1.schema.json`

- [ ] **Step 1: Create the schema file**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://chikaki.com/freewise/schemas/kindle-export-v1.json",
  "title": "Kindle Notebook Export Envelope (v1)",
  "type": "object",
  "required": ["schema_version", "exported_at", "source", "books"],
  "additionalProperties": false,
  "properties": {
    "schema_version": {
      "type": "string",
      "pattern": "^1\\.[0-9]+$"
    },
    "exported_at": {
      "type": "string",
      "format": "date-time"
    },
    "source": {
      "const": "kindle_notebook"
    },
    "books": {
      "type": "array",
      "items": { "$ref": "#/$defs/Book" }
    }
  },
  "$defs": {
    "Book": {
      "type": "object",
      "required": ["asin", "title", "highlights"],
      "additionalProperties": false,
      "properties": {
        "asin": { "type": "string", "minLength": 1 },
        "title": { "type": "string", "minLength": 1 },
        "author": { "type": ["string", "null"] },
        "cover_url": { "type": ["string", "null"] },
        "highlights": {
          "type": "array",
          "items": { "$ref": "#/$defs/Highlight" }
        }
      }
    },
    "Highlight": {
      "type": "object",
      "required": ["id", "text"],
      "additionalProperties": false,
      "properties": {
        "id": { "type": "string", "minLength": 1 },
        "text": { "type": "string" },
        "note": { "type": ["string", "null"] },
        "color": {
          "anyOf": [
            { "type": "null" },
            { "enum": ["yellow", "blue", "pink", "orange"] }
          ]
        },
        "location": { "type": ["integer", "null"] },
        "page": { "type": ["integer", "null"] },
        "created_at": { "type": ["string", "null"], "format": "date-time" }
      }
    }
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add shared/kindle-export-v1.schema.json
git commit -m "feat(shared): JSON Schema for KindleExportV1 envelope

Strict validation contract used by both the importer (server-side) and
the browser extension (client-side, before POST)."
```

### Task C.3: Add schema validation to importer

**Files:**
- Modify: `app/importers/kindle_notebook.py`
- Test: `tests/importers/test_kindle_notebook.py`

- [ ] **Step 1: Write failing test for schema validation**

Append to `tests/importers/test_kindle_notebook.py`:

```python
import io
import json

import pytest

from app.importers.kindle_notebook import import_kindle_notebook_json


def test_importer_rejects_envelope_failing_schema(session):
    """Envelope missing required `books` field is rejected before any DB write."""
    bad = {
        "schema_version": "1.0",
        "exported_at": "2026-04-29T00:00:00Z",
        "source": "kindle_notebook",
        # books missing
    }
    with pytest.raises(ValueError, match="books"):
        import_kindle_notebook_json(io.BytesIO(json.dumps(bad).encode()), session, user_id=1)


def test_importer_rejects_book_with_no_asin(session):
    bad = {
        "schema_version": "1.0",
        "exported_at": "2026-04-29T00:00:00Z",
        "source": "kindle_notebook",
        "books": [
            {"title": "No ASIN", "highlights": []}
        ],
    }
    with pytest.raises(ValueError, match="asin"):
        import_kindle_notebook_json(io.BytesIO(json.dumps(bad).encode()), session, user_id=1)
```

- [ ] **Step 2: Run test, expect failure**

```bash
.venv/bin/python -m pytest tests/importers/test_kindle_notebook.py::test_importer_rejects_envelope_failing_schema -v
```

Expected: FAIL (validator not yet hooked in).

- [ ] **Step 3: Add schema validation in importer**

Open `app/importers/kindle_notebook.py`. Near the top:

```python
from pathlib import Path

import jsonschema

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "shared" / "kindle-export-v1.schema.json"
_SCHEMA = json.loads(_SCHEMA_PATH.read_text())
_VALIDATOR = jsonschema.Draft202012Validator(_SCHEMA)
```

Then in `_validate_envelope` (or wherever the existing minimal validation lives), append:

```python
def _validate_envelope(payload: dict[str, Any]) -> None:
    # Existing schema_version + source checks ...

    # Strict full-schema validation. Surface the first error path for clarity.
    errors = sorted(_VALIDATOR.iter_errors(payload), key=lambda e: e.path)
    if errors:
        first = errors[0]
        path = ".".join(str(p) for p in first.absolute_path) or "(root)"
        raise ValueError(f"Schema validation failed at {path}: {first.message}")
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest tests/importers/test_kindle_notebook.py -v
```

Expected: all green (existing tests pass, two new tests pass).

- [ ] **Step 5: Commit**

```bash
git add app/importers/kindle_notebook.py tests/importers/test_kindle_notebook.py
git commit -m "feat(importer): validate envelope against shared JSON Schema

Catches malformed envelopes (e.g., from a buggy extension build) at
the importer boundary before any DB write."
```

### Task C.4: Upgrade `KindleImportResult.errors` to `list[dict]`

**Files:**
- Modify: `app/importers/kindle_notebook.py`
- Modify: `tests/importers/test_kindle_notebook.py`
- Modify: `app/services/kindle_import_watcher.py` (if it consumes `errors`)
- Modify: `app/routers/importer.py` (multipart upload error rendering)

- [ ] **Step 1: Write failing test asserting structured errors**

Add to `tests/importers/test_kindle_notebook.py`:

```python
def test_importer_partial_failure_returns_structured_errors(session, monkeypatch):
    """When one book raises, errors is list[dict] with book_title + reason.
    The good book still imports; the bad one is skipped."""
    import app.importers.kindle_notebook as mod

    real_get_or_create = mod.get_or_create_book

    def flaky_get_or_create(session, *, title, author, **kwargs):
        if title == "Bad Book":
            raise RuntimeError("simulated dedup failure")
        return real_get_or_create(session, title=title, author=author, **kwargs)

    monkeypatch.setattr(mod, "get_or_create_book", flaky_get_or_create)

    payload = {
        "schema_version": "1.0",
        "exported_at": "2026-04-29T00:00:00Z",
        "source": "kindle_notebook",
        "books": [
            {
                "asin": "B07GOOD",
                "title": "Good Book",
                "author": "A",
                "cover_url": None,
                "highlights": [
                    {"id": "QID:1", "text": "valid highlight",
                     "note": None, "color": None,
                     "location": 1, "page": None, "created_at": None}
                ],
            },
            {
                "asin": "B07BAD",
                "title": "Bad Book",
                "author": "B",
                "cover_url": None,
                "highlights": [],
            },
        ],
    }
    result = import_kindle_notebook_json(
        io.BytesIO(json.dumps(payload).encode()), session, user_id=1
    )

    # The good book imported.
    assert result.highlights_created == 1
    assert result.books_created == 1

    # The bad book produced a structured error.
    assert len(result.errors) == 1
    err = result.errors[0]
    assert isinstance(err, dict)
    assert err["book_title"] == "Bad Book"
    assert "simulated dedup failure" in err["reason"]
```

This test exercises the contract `errors: list[{"book_title": str, "reason": str}]`. The implementer must wrap the per-book loop in `import_kindle_notebook_json` with a try/except that appends `{"book_title": book["title"], "reason": str(exc)}` on failure (and continues to the next book rather than aborting the whole import).

- [ ] **Step 2: Update the dataclass**

In `app/importers/kindle_notebook.py`:

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class KindleImportResult:
    books_created: int = 0
    books_matched: int = 0
    highlights_created: int = 0
    highlights_skipped_duplicates: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)
```

- [ ] **Step 3: Update internal error-collection sites**

Find all places that today do:

```python
result.errors.append(f"Book {title!r}: {reason}")
```

Change to:

```python
result.errors.append({"book_title": title, "reason": reason})
```

- [ ] **Step 4: Update consumers**

In `app/routers/importer.py` (multipart upload route), update the error rendering. The template loop probably does `{% for err in errors %}{{ err }}{% endfor %}` — change template to `{{ err.book_title }}: {{ err.reason }}`.

In `app/services/kindle_import_watcher.py`, find any place that joins/logs errors and update to handle the dict shape:

```python
" | ".join(f"{e['book_title']}: {e['reason']}" for e in result.errors)
```

- [ ] **Step 5: Run all importer + watcher + router tests**

```bash
.venv/bin/python -m pytest tests/importers/ tests/services/ tests/routers/test_import_kindle_route.py -v
```

Expected: all green. Fix call sites until green.

- [ ] **Step 6: Commit**

```bash
git add app/ tests/ -- '*.py' '*.html'
git commit -m "refactor(importer): KindleImportResult.errors → list[dict]

Each error now carries book_title + reason so the upcoming extension
popup can render per-book failure detail. Updates all consumers
(watcher, multipart route)."
```

---

# Phase D — `POST /api/v2/imports/kindle` + gzip request middleware

### Task D.1: Failing test for the new endpoint

**Files:**
- Create: `tests/api_v2/test_kindle_import.py`

- [ ] **Step 1: Write the test file**

```python
"""Tests for POST /api/v2/imports/kindle (browser-extension entry point)."""
from __future__ import annotations

import gzip
import io
import json

import pytest


def _envelope(books=None):
    return {
        "schema_version": "1.0",
        "exported_at": "2026-04-29T00:00:00Z",
        "source": "kindle_notebook",
        "books": books or [],
    }


def test_post_requires_token(client):
    r = client.post("/api/v2/imports/kindle", json=_envelope())
    assert r.status_code == 401


def test_post_rejects_unknown_token(client):
    r = client.post(
        "/api/v2/imports/kindle",
        json=_envelope(),
        headers={"Authorization": "Token totally-bogus-value"},
    )
    assert r.status_code == 401


def test_post_accepts_valid_envelope(client, valid_token):
    body = _envelope(books=[
        {
            "asin": "B07TEST",
            "title": "Test Book",
            "author": "Test Author",
            "cover_url": None,
            "highlights": [
                {"id": "QID:1", "text": "first highlight", "note": None,
                 "color": "yellow", "location": 100, "page": None,
                 "created_at": None}
            ],
        }
    ])
    r = client.post(
        "/api/v2/imports/kindle",
        json=body,
        headers={"Authorization": f"Token {valid_token}"},
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["books_created"] == 1
    assert payload["highlights_created"] == 1
    assert payload["errors"] == []


def test_post_rejects_invalid_schema(client, valid_token):
    bad = {"schema_version": "1.0", "source": "kindle_notebook"}  # missing fields
    r = client.post(
        "/api/v2/imports/kindle",
        json=bad,
        headers={"Authorization": f"Token {valid_token}"},
    )
    assert r.status_code == 400
    assert "schema" in r.json()["detail"].lower() or "books" in r.json()["detail"].lower()


def test_post_accepts_gzipped_body(client, valid_token):
    body = _envelope(books=[
        {"asin": "B07GZ", "title": "Compressed", "highlights": [
            {"id": "QID:1", "text": "gz highlight"}
        ]}
    ])
    raw = json.dumps(body).encode("utf-8")
    compressed = gzip.compress(raw)
    r = client.post(
        "/api/v2/imports/kindle",
        content=compressed,
        headers={
            "Authorization": f"Token {valid_token}",
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["books_created"] == 1
```

- [ ] **Step 2: Verify tests fail (route doesn't exist yet)**

```bash
.venv/bin/python -m pytest tests/api_v2/test_kindle_import.py -v
```

Expected: 5 failures (404 or auth-related).

(Pause to confirm `valid_token` and `client` fixtures exist in `tests/conftest.py`; if not, follow the patterns already used by `tests/test_api_token_route.py`.)

### Task D.2: Implement gzip request middleware

**Files:**
- Create: `app/middleware/__init__.py`
- Create: `app/middleware/gzip_request.py`
- Test: `tests/middleware/test_gzip_request.py`

- [ ] **Step 1: Write the failing test**

```python
"""Middleware that decompresses Content-Encoding: gzip request bodies."""
from __future__ import annotations

import gzip
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.gzip_request import GzipRequestMiddleware


def _build_app() -> TestClient:
    app = FastAPI()
    app.add_middleware(GzipRequestMiddleware)

    @app.post("/echo")
    async def echo(payload: dict) -> dict:
        return payload

    return TestClient(app)


def test_uncompressed_body_passthrough():
    client = _build_app()
    r = client.post("/echo", json={"hello": "world"})
    assert r.status_code == 200
    assert r.json() == {"hello": "world"}


def test_gzipped_body_decompressed():
    client = _build_app()
    raw = json.dumps({"hello": "world"}).encode()
    compressed = gzip.compress(raw)
    r = client.post(
        "/echo",
        content=compressed,
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert r.status_code == 200
    assert r.json() == {"hello": "world"}


def test_gzipped_body_with_invalid_compression_returns_400():
    client = _build_app()
    r = client.post(
        "/echo",
        content=b"not actually gzip",
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert r.status_code == 400
```

- [ ] **Step 2: Run test, expect failure**

```bash
.venv/bin/python -m pytest tests/middleware/test_gzip_request.py -v
```

Expected: ImportError (middleware doesn't exist).

- [ ] **Step 3: Create the middleware**

`app/middleware/__init__.py`:

```python
"""Custom Starlette / FastAPI middleware for FreeWise."""
```

`app/middleware/gzip_request.py`:

```python
"""Decompress Content-Encoding: gzip request bodies.

Starlette's built-in GZipMiddleware compresses *responses* but does not
decompress *requests*. This middleware fills the gap so browser-extension
clients can shrink large Kindle import payloads.
"""
from __future__ import annotations

import gzip

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class GzipRequestMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.headers.get("content-encoding", "").lower() != "gzip":
            return await call_next(request)

        try:
            body = await request.body()
            decompressed = gzip.decompress(body)
        except (OSError, gzip.BadGzipFile, EOFError) as exc:
            return JSONResponse(
                {"detail": f"Invalid gzip body: {exc}"},
                status_code=400,
            )

        # Replace the request body. Starlette caches body via _body attr.
        request._body = decompressed

        # Strip the encoding header so downstream handlers don't try to
        # decompress again, and rewrite content-length.
        new_headers = [
            (k, v) for k, v in request.scope["headers"]
            if k.lower() not in (b"content-encoding", b"content-length")
        ]
        new_headers.append((b"content-length", str(len(decompressed)).encode()))
        request.scope["headers"] = new_headers

        return await call_next(request)
```

- [ ] **Step 4: Run middleware tests**

```bash
.venv/bin/python -m pytest tests/middleware/test_gzip_request.py -v
```

Expected: all green.

- [ ] **Step 5: Register middleware in `app/main.py`**

Open `app/main.py`. Near other `add_middleware` calls, add:

```python
from app.middleware.gzip_request import GzipRequestMiddleware

app.add_middleware(GzipRequestMiddleware)
```

- [ ] **Step 6: Commit**

```bash
git add app/middleware/ tests/middleware/ app/main.py
git commit -m "feat(middleware): gzip request body decompression

Browser extension can now POST gzipped bodies to /api/v2/imports/kindle
to cut a 1MB Kindle export down to ~300KB."
```

### Task D.3: Implement the import endpoint

**Files:**
- Create: `app/api_v2/kindle_import.py`
- Modify: `app/api_v2/router.py`

- [ ] **Step 1: Implement the endpoint**

`app/api_v2/kindle_import.py`:

```python
"""POST /api/v2/imports/kindle — browser-extension entry point.

Thin wrapper around :func:`app.importers.kindle_notebook.import_kindle_notebook_json`.
Authenticated by the existing ``Authorization: Token <value>`` scheme.
"""
from __future__ import annotations

import io
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from app.api_v2.auth import get_api_token
from app.db import get_session
from app.importers.kindle_notebook import import_kindle_notebook_json
from app.models import ApiToken

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/imports", tags=["v2-imports"])


@router.post("/kindle")
async def post_kindle_import(
    request: Request,
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    file_obj = io.BytesIO(json.dumps(payload).encode("utf-8"))
    try:
        result = import_kindle_notebook_json(file_obj, session, user_id=token.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("kindle import failed")
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")

    body = {
        "books_created": result.books_created,
        "books_matched": result.books_matched,
        "highlights_created": result.highlights_created,
        "highlights_skipped_duplicates": result.highlights_skipped_duplicates,
        "errors": list(result.errors),
    }
    if result.errors:
        # Partial success — surface 207-Multi-Status semantics via 422.
        return {**body, "_status": "partial"}
    return body
```

- [ ] **Step 2: Mount the sub-router**

Open `app/api_v2/router.py`. After the existing imports:

```python
from app.api_v2.kindle_import import router as kindle_import_router
```

After the existing `router = APIRouter(...)` and other `include_router` calls:

```python
router.include_router(kindle_import_router)
```

- [ ] **Step 3: Run the endpoint tests**

```bash
.venv/bin/python -m pytest tests/api_v2/test_kindle_import.py -v
```

Expected: all green.

- [ ] **Step 4: Run full test suite to catch regressions**

```bash
.venv/bin/python -m pytest -q
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add app/api_v2/kindle_import.py app/api_v2/router.py tests/api_v2/test_kindle_import.py
git commit -m "feat(api-v2): POST /api/v2/imports/kindle endpoint

Browser-extension entry point. Validates envelope against shared
JSON Schema, then delegates to existing import_kindle_notebook_json.
Supports gzipped request bodies via the new middleware."
```

---

# Phase E — CORS + ApiToken scopes

### Task E.1: Add `scopes` column to `ApiToken`

**Files:**
- Modify: `app/models.py`
- Modify: `app/db.py` (lightweight migration on startup, matching existing pattern e.g. `Book.kindle_asin`)

- [ ] **Step 1: Write a failing test for scope enforcement**

In `tests/test_api_token_route.py` or a new `tests/api_v2/test_token_scopes.py`:

```python
def test_token_with_kindle_import_scope_passes(client, db_session):
    # Create token with scopes=["kindle:import"], call /api/v2/imports/kindle, expect 200
    ...

def test_token_without_kindle_import_scope_returns_403(client, db_session):
    # Create token with scopes=["highlights:read"], call /api/v2/imports/kindle, expect 403
    ...

def test_token_with_no_scopes_acts_as_full_access_legacy(client, db_session):
    # Backwards-compat: existing tokens have scopes=NULL/empty → still work everywhere
    ...
```

(Detail the test bodies based on existing fixtures — pattern after the `test_api_token_route.py` shape.)

- [ ] **Step 2: Run, expect failures**

```bash
.venv/bin/python -m pytest tests/api_v2/test_token_scopes.py -v
```

- [ ] **Step 3: Add the column**

In `app/models.py`:

```python
class ApiToken(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    token: str = Field(index=True, unique=True)
    name: str
    user_id: int = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    last_used_at: Optional[datetime] = Field(default=None, index=True)
    scopes: Optional[str] = Field(default=None)  # comma-separated; None = full access
```

- [ ] **Step 4: Add startup migration**

In `app/db.py` (search for the existing pattern that adds `Book.kindle_asin`):

```python
def _ensure_apitoken_scopes_column(engine) -> None:
    with engine.connect() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(apitoken)")}
        if "scopes" not in cols:
            conn.exec_driver_sql("ALTER TABLE apitoken ADD COLUMN scopes VARCHAR")
            conn.commit()
```

Wire it next to the existing `_ensure_book_kindle_asin_column(engine)` call.

- [ ] **Step 5: Update `get_api_token` to expose scopes**

In `app/api_v2/auth.py`, add a helper:

```python
def require_scope(*required: str):
    """FastAPI dependency factory: require the token's scope set to include
    at least one of `required`. Tokens with NULL/empty `scopes` are treated
    as full-access (legacy / pre-scope tokens)."""
    def dep(token: ApiToken = Depends(get_api_token)) -> ApiToken:
        if not token.scopes:
            return token  # legacy: any scope OK
        owned = {s.strip() for s in token.scopes.split(",") if s.strip()}
        if not owned.intersection(required):
            raise HTTPException(
                status_code=403,
                detail=f"Token missing required scope: one of {required!r}",
            )
        return token
    return dep
```

- [ ] **Step 6: Use in the kindle import endpoint**

In `app/api_v2/kindle_import.py`:

```python
from app.api_v2.auth import require_scope

@router.post("/kindle")
async def post_kindle_import(
    request: Request,
    token: ApiToken = Depends(require_scope("kindle:import")),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    ...
```

- [ ] **Step 7: Run tests**

```bash
.venv/bin/python -m pytest tests/api_v2/ -v
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add app/models.py app/db.py app/api_v2/auth.py app/api_v2/kindle_import.py tests/api_v2/test_token_scopes.py
git commit -m "feat(api-v2): ApiToken.scopes column + scope-based auth

POST /api/v2/imports/kindle now requires the kindle:import scope.
Legacy tokens (scopes=NULL) retain full access for backwards compat."
```

### Task E.2: CORS for the api subdomain

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Write a failing CORS test**

`tests/api_v2/test_cors.py`:

```python
def test_options_preflight_from_extension_origin_succeeds(client):
    r = client.options(
        "/api/v2/imports/kindle",
        headers={
            "Origin": "chrome-extension://ABCDEF1234567890",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,content-encoding",
        },
    )
    assert r.status_code == 200
    assert "POST" in r.headers.get("access-control-allow-methods", "")
    assert "authorization" in r.headers.get("access-control-allow-headers", "").lower()
```

- [ ] **Step 2: Run, expect failure**

```bash
.venv/bin/python -m pytest tests/api_v2/test_cors.py -v
```

- [ ] **Step 3: Add CORS middleware**

In `app/main.py`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    # Match any chrome-extension origin. Single-user setup, so no need to
    # pin the exact extension ID. Server-side ApiToken auth is the gate.
    allow_origin_regex=r"^chrome-extension://[a-z0-9]+$",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Content-Encoding"],
    max_age=86400,
)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/python -m pytest tests/api_v2/test_cors.py -v
```

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/api_v2/test_cors.py
git commit -m "feat(cors): allow chrome-extension origins for /api/v2/*

ApiToken auth remains the security gate. CORS regex is narrow enough
to reject regular cross-site origins."
```

---

# Phase F — Cookie upload UI

### Task F.1: Cookie service unit tests

**Files:**
- Create: `tests/services/test_kindle_cookie.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for the storage_state.json validation + atomic write service."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.services.kindle_cookie import (
    CookieValidationError,
    ScrapeRunningError,
    write_storage_state,
    read_storage_state_status,
)


def _valid_storage_state() -> dict:
    return {
        "cookies": [
            {"name": "at-main", "value": "x", "domain": ".amazon.com", "path": "/"},
            {"name": "session-token", "value": "y", "domain": ".amazon.com", "path": "/"},
        ],
        "origins": [],
    }


def test_write_creates_file_atomically(tmp_path):
    target = tmp_path / "storage_state.json"
    write_storage_state(json.dumps(_valid_storage_state()).encode(), target_path=target)
    assert target.is_file()
    assert json.loads(target.read_text())["cookies"][0]["name"] == "at-main"


def test_write_rejects_invalid_json(tmp_path):
    with pytest.raises(CookieValidationError, match="JSON"):
        write_storage_state(b"not json at all", target_path=tmp_path / "x.json")


def test_write_rejects_missing_cookies_array(tmp_path):
    with pytest.raises(CookieValidationError, match="cookies"):
        write_storage_state(b'{"origins": []}', target_path=tmp_path / "x.json")


def test_write_rejects_missing_amazon_cookie(tmp_path):
    bad = {
        "cookies": [
            {"name": "random", "value": "x", "domain": ".example.com", "path": "/"}
        ]
    }
    with pytest.raises(CookieValidationError, match="amazon"):
        write_storage_state(
            json.dumps(bad).encode(),
            target_path=tmp_path / "x.json",
        )


def test_write_rejects_size_over_100kb(tmp_path):
    huge = b"x" * 101_000
    with pytest.raises(CookieValidationError, match="size"):
        write_storage_state(huge, target_path=tmp_path / "x.json")


def test_write_returns_409_when_scrape_running(tmp_path, monkeypatch):
    state_file = tmp_path / "scrape_state.json"
    state_file.write_text(json.dumps({"pid": 1, "finished_at": None}))
    monkeypatch.setenv("KINDLE_SCRAPE_STATE_FILE", str(state_file))

    with pytest.raises(ScrapeRunningError):
        write_storage_state(
            json.dumps(_valid_storage_state()).encode(),
            target_path=tmp_path / "x.json",
        )


def test_status_reads_existing_file(tmp_path):
    p = tmp_path / "storage_state.json"
    p.write_text(json.dumps(_valid_storage_state()))
    s = read_storage_state_status(p)
    assert s["exists"] is True
    assert s["has_at_main"] is True
    assert ".amazon.com" in s["domains"]


def test_status_handles_missing_file(tmp_path):
    s = read_storage_state_status(tmp_path / "does-not-exist.json")
    assert s["exists"] is False
```

- [ ] **Step 2: Run, expect ImportError**

```bash
.venv/bin/python -m pytest tests/services/test_kindle_cookie.py -v
```

### Task F.2: Cookie service implementation

**Files:**
- Create: `app/services/kindle_cookie.py`

- [ ] **Step 1: Implement the service**

```python
"""Validate + atomically write Playwright storage_state.json files.

Used by the dashboard's POST /dashboard/kindle/cookie route. Replaces
the old `ssh + rsync` workflow for refreshing the Amazon login cookie
that the monthly QNAP scraper uses.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_BYTES = 100 * 1024
REQUIRED_COOKIE_NAMES = {"at-main", "session-token"}
AMAZON_DOMAIN_SUFFIXES = (".amazon.com", ".amazon.co.jp", "amazon.com", "amazon.co.jp")


class CookieValidationError(ValueError):
    """Raised when an uploaded payload is not a valid Playwright storage_state."""


class ScrapeRunningError(RuntimeError):
    """Raised when a scrape is in flight; cookie write must be deferred."""


def _scrape_running() -> bool:
    state_file = os.environ.get("KINDLE_SCRAPE_STATE_FILE")
    if not state_file:
        return False
    p = Path(state_file)
    if not p.is_file():
        return False
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("finished_at") is None and data.get("pid") is not None


def _validate(payload: bytes) -> dict[str, Any]:
    if len(payload) > MAX_BYTES:
        raise CookieValidationError(
            f"File size {len(payload)} bytes exceeds {MAX_BYTES} byte limit."
        )
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CookieValidationError(f"Invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise CookieValidationError("Top-level must be a JSON object.")
    cookies = data.get("cookies")
    if not isinstance(cookies, list) or not cookies:
        raise CookieValidationError(
            "Missing or empty 'cookies' array — not a Playwright storage_state.json."
        )

    cookie_names = {c.get("name") for c in cookies if isinstance(c, dict)}
    if not cookie_names & REQUIRED_COOKIE_NAMES:
        raise CookieValidationError(
            f"None of {sorted(REQUIRED_COOKIE_NAMES)} cookies found — "
            f"this does not look like a logged-in Amazon session."
        )

    has_amazon_domain = any(
        any(d.get("domain", "").endswith(suffix) for suffix in AMAZON_DOMAIN_SUFFIXES)
        for d in cookies if isinstance(d, dict)
    )
    if not has_amazon_domain:
        raise CookieValidationError(
            "No amazon.com / amazon.co.jp cookie domains found."
        )
    return data


def write_storage_state(payload: bytes, target_path: Path) -> dict[str, Any]:
    """Validate, then atomically write storage_state.json. Raises on conflict."""
    if _scrape_running():
        raise ScrapeRunningError(
            "A Kindle scrape is currently running. Wait or cancel it first."
        )
    data = _validate(payload)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_suffix(target_path.suffix + f".tmp.{os.getpid()}")
    tmp_path.write_bytes(payload)
    os.replace(tmp_path, target_path)
    os.chmod(target_path, 0o644)
    return read_storage_state_status(target_path)


def read_storage_state_status(path: Path) -> dict[str, Any]:
    """Return a JSON-serializable summary of the cookie file's state."""
    if not path.is_file():
        return {"exists": False}
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"exists": True, "valid": False, "size": len(raw)}

    cookies = data.get("cookies", []) if isinstance(data, dict) else []
    domains = sorted({c.get("domain") for c in cookies
                       if isinstance(c, dict) and c.get("domain")})
    has_at_main = any(c.get("name") == "at-main" for c in cookies if isinstance(c, dict))
    return {
        "exists": True,
        "valid": True,
        "size": len(raw),
        "cookie_count": len(cookies),
        "domains": [d for d in domains if d],
        "has_at_main": has_at_main,
        "mtime": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
    }
```

- [ ] **Step 2: Run tests**

```bash
.venv/bin/python -m pytest tests/services/test_kindle_cookie.py -v
```

Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add app/services/kindle_cookie.py tests/services/test_kindle_cookie.py
git commit -m "feat(kindle): cookie service — validate + atomic-write storage_state.json"
```

### Task F.3: Cookie upload route

**Files:**
- Create: `app/routers/kindle_cookie.py`
- Create: `app/templates/kindle_cookie.html`
- Create: `app/templates/_kindle_cookie_status.html`
- Test: `tests/routers/test_kindle_cookie_route.py`

- [ ] **Step 1: Write failing route tests**

```python
"""Tests for /dashboard/kindle/cookie GET + POST."""
import io
import json
from pathlib import Path

import pytest


def _valid_state() -> bytes:
    return json.dumps({
        "cookies": [
            {"name": "at-main", "value": "x", "domain": ".amazon.com", "path": "/"},
        ],
    }).encode()


def test_get_renders_status_page(client):
    r = client.get("/dashboard/kindle/cookie")
    assert r.status_code == 200
    assert "kindle" in r.text.lower()
    assert "upload" in r.text.lower() or "storage_state" in r.text.lower()


def test_post_uploads_valid_cookie(client, tmp_path, monkeypatch):
    target = tmp_path / "storage_state.json"
    monkeypatch.setenv("KINDLE_STATE_PATH", str(tmp_path))

    r = client.post(
        "/dashboard/kindle/cookie",
        files={"file": ("storage_state.json", _valid_state(), "application/json")},
    )
    assert r.status_code == 200
    assert target.is_file()


def test_post_rejects_invalid_cookie(client, tmp_path, monkeypatch):
    monkeypatch.setenv("KINDLE_STATE_PATH", str(tmp_path))
    r = client.post(
        "/dashboard/kindle/cookie",
        files={"file": ("storage_state.json", b"not json", "application/json")},
    )
    assert r.status_code == 400
```

- [ ] **Step 2: Implement the router**

```python
"""Dashboard route for uploading the Kindle scraper's storage_state.json."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.kindle_cookie import (
    CookieValidationError,
    ScrapeRunningError,
    read_storage_state_status,
    write_storage_state,
)

router = APIRouter(prefix="/dashboard/kindle", tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


def _target_path() -> Path:
    base = os.environ.get(
        "KINDLE_STATE_PATH",
        "/share/Container/freewise/state/kindle",
    )
    return Path(base) / "storage_state.json"


@router.get("/cookie", response_class=HTMLResponse)
async def get_cookie_page(request: Request) -> HTMLResponse:
    status = read_storage_state_status(_target_path())
    return templates.TemplateResponse(
        request, "kindle_cookie.html", {"status": status}
    )


@router.post("/cookie", response_class=HTMLResponse)
async def post_cookie(
    request: Request,
    file: UploadFile = File(...),
) -> HTMLResponse:
    payload = await file.read()
    try:
        status = write_storage_state(payload, target_path=_target_path())
    except CookieValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ScrapeRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return templates.TemplateResponse(
        request, "_kindle_cookie_status.html",
        {"status": status, "success": True},
    )
```

- [ ] **Step 3: Mount in `app/main.py`**

```python
from app.routers import kindle_cookie as kindle_cookie_router

app.include_router(kindle_cookie_router.router)
```

- [ ] **Step 4: Templates**

`app/templates/kindle_cookie.html` — extend the dashboard layout, render the status partial + an upload form. Skeleton:

```html
{% extends "_base.html" %}
{% block content %}
<div class="max-w-2xl mx-auto p-6">
  <h1 class="text-2xl font-bold mb-4">Kindle scraper cookie</h1>

  <div id="cookie-status">
    {% include "_kindle_cookie_status.html" %}
  </div>

  <form hx-post="/dashboard/kindle/cookie"
        hx-encoding="multipart/form-data"
        hx-target="#cookie-status"
        class="mt-6 space-y-3">
    <input type="file" name="file" accept=".json,application/json" required
           class="block">
    <button type="submit"
            class="px-4 py-2 bg-blue-600 text-white rounded">
      Upload
    </button>
  </form>

  <details class="mt-8 text-sm text-gray-600">
    <summary>How to generate this file</summary>
    <pre class="mt-2 p-2 bg-gray-50">cd ~/Development/freewise-qnap-kindle
make login
# Browser opens. Log into Amazon.
# Then upload state/kindle/storage_state.json above.</pre>
  </details>
</div>
{% endblock %}
```

`app/templates/_kindle_cookie_status.html`:

```html
{% if status.exists %}
  {% if status.valid %}
    <div class="p-3 rounded bg-emerald-50 border border-emerald-200">
      ✓ Cookie present.
      Last updated: <time data-iso="{{ status.mtime }}">{{ status.mtime }}</time>
      ({{ status.cookie_count }} cookies, {{ status.size }} bytes)
      {% if status.has_at_main %}<span class="text-emerald-700">at-main ✓</span>
      {% else %}<span class="text-red-600">at-main missing ✗</span>{% endif %}
      <details class="mt-1"><summary class="text-xs">Domains</summary>
        <code class="text-xs">{{ status.domains | join(', ') }}</code>
      </details>
    </div>
  {% else %}
    <div class="p-3 rounded bg-yellow-50 border border-yellow-200">
      ⚠ File present but not valid JSON.
    </div>
  {% endif %}
{% else %}
  <div class="p-3 rounded bg-gray-50 border border-gray-200">
    No cookie file uploaded yet. The monthly QNAP scraper cannot run until you upload one.
  </div>
{% endif %}
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python -m pytest tests/routers/test_kindle_cookie_route.py -v
```

Expected: green.

- [ ] **Step 6: Add a link from the main dashboard**

Open `app/templates/dashboard.html` (or wherever the kindle scrape card lives) and add a small link:

```html
<a href="/dashboard/kindle/cookie" class="text-xs text-blue-600 hover:underline">
  Manage scraper cookie
</a>
```

- [ ] **Step 7: Commit**

```bash
git add app/routers/kindle_cookie.py app/main.py app/templates/kindle_cookie.html \
        app/templates/_kindle_cookie_status.html app/templates/dashboard.html \
        tests/routers/test_kindle_cookie_route.py
git commit -m "feat(dashboard): /dashboard/kindle/cookie upload UI

Replaces the ssh+rsync workflow for refreshing the Kindle scraper's
storage_state.json. Validates the upload, writes atomically, surfaces
status (mtime, domains, at-main presence)."
```

---

# Phase G — Browser extension skeleton

### Task G.1: Vite + TS skeleton

**Files:**
- Create: `extensions/kindle-importer/package.json`
- Create: `extensions/kindle-importer/tsconfig.json`
- Create: `extensions/kindle-importer/vite.config.ts`
- Create: `extensions/kindle-importer/manifest.json`
- Create: `extensions/kindle-importer/src/popup.html`
- Create: `extensions/kindle-importer/src/popup.ts`
- Create: `extensions/kindle-importer/src/popup.css`
- Create: `extensions/kindle-importer/src/background.ts`
- Create: `extensions/kindle-importer/src/content.ts`
- Create: `extensions/kindle-importer/.gitignore`
- Create: `extensions/kindle-importer/README.md`

- [ ] **Step 1: Initialise the package**

```bash
mkdir -p extensions/kindle-importer/src
cd extensions/kindle-importer
```

Create `package.json`:

```json
{
  "name": "freewise-kindle-importer",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "build": "vite build",
    "dev": "vite build --watch",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "devDependencies": {
    "@types/chrome": "^0.0.270",
    "@types/node": "^22.0.0",
    "typescript": "^5.6.3",
    "vite": "^5.4.10",
    "vitest": "^2.1.4",
    "@vitest/web-worker": "^2.1.4",
    "happy-dom": "^15.7.4"
  },
  "dependencies": {
    "ajv": "^8.17.1"
  }
}
```

- [ ] **Step 2: tsconfig**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "types": ["chrome", "node"],
    "resolveJsonModule": true,
    "isolatedModules": true
  },
  "include": ["src/**/*", "test/**/*"]
}
```

- [ ] **Step 3: vite config**

```typescript
// vite.config.ts
import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        popup: resolve(__dirname, 'src/popup.html'),
        background: resolve(__dirname, 'src/background.ts'),
        content: resolve(__dirname, 'src/content.ts'),
      },
      output: {
        entryFileNames: '[name].js',
        chunkFileNames: 'chunks/[name].[hash].js',
        assetFileNames: '[name].[ext]',
      },
    },
  },
});
```

- [ ] **Step 4: manifest**

```json
{
  "manifest_version": 3,
  "name": "FreeWise Kindle Importer",
  "version": "1.0.0",
  "description": "Sync Kindle highlights from read.amazon.com to a self-hosted FreeWise instance.",
  "permissions": ["tabs", "scripting", "storage"],
  "host_permissions": [
    "https://read.amazon.com/*",
    "https://freewiseapi.chikaki.com/*"
  ],
  "action": {
    "default_popup": "popup.html",
    "default_icon": {
      "16": "icons/16.png",
      "48": "icons/48.png",
      "128": "icons/128.png"
    }
  },
  "background": {
    "service_worker": "background.js",
    "type": "module"
  },
  "content_scripts": [{
    "matches": ["https://read.amazon.com/kp/notebook*"],
    "js": ["content.js"],
    "run_at": "document_idle",
    "all_frames": false
  }],
  "icons": {
    "16": "icons/16.png",
    "48": "icons/48.png",
    "128": "icons/128.png"
  }
}
```

- [ ] **Step 5: stub source files**

`src/popup.html`:

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="popup.css">
</head>
<body class="w-80 p-3 text-sm">
  <h1 class="text-base font-bold mb-2">FreeWise Kindle Importer</h1>
  <div id="root">Loading...</div>
  <script type="module" src="popup.ts"></script>
</body>
</html>
```

`src/popup.ts`:

```typescript
const root = document.getElementById('root')!;
root.textContent = 'Skeleton popup — implement in Task I.';
```

`src/popup.css`:

```css
body { font-family: system-ui, sans-serif; }
```

`src/background.ts`:

```typescript
console.info('FreeWise Kindle Importer background SW alive');
```

`src/content.ts`:

```typescript
console.info('FreeWise Kindle Importer content script loaded on', location.href);
```

`.gitignore`:

```
node_modules/
dist/
*.log
```

`README.md`:

```markdown
# FreeWise Kindle Importer (Chrome MV3)

## Build

```sh
npm install
npm run build      # one-shot
npm run dev        # watch mode
```

## Load

1. `npm run build`
2. Chrome → `chrome://extensions/` → Developer mode → Load unpacked → select `extensions/kindle-importer/dist/`

## Test

```sh
npm run test
```
```

- [ ] **Step 6: Install + build**

```bash
cd extensions/kindle-importer
npm install
npm run build
ls dist/
```

Expected: `popup.html background.js content.js popup.js manifest.json icons/` (manifest copied; if not, add a `vite-plugin-static-copy` later).

- [ ] **Step 7: Copy manifest into dist**

Vite doesn't auto-copy `manifest.json`. Add a one-liner postbuild step. In `package.json`:

```json
"scripts": {
  "build": "vite build && cp manifest.json dist/ && mkdir -p dist/icons && cp -R icons/* dist/icons/ 2>/dev/null || true",
  ...
}
```

- [ ] **Step 8: Generate placeholder icons**

```bash
mkdir -p icons
# Use any existing FreeWise PNG. Resize:
cp ../../app/static/favicon.png icons/16.png 2>/dev/null || \
  printf 'PNG placeholder' > icons/16.png
cp icons/16.png icons/48.png
cp icons/16.png icons/128.png
```

(Replace with proper renders later — Task K.1 manual checklist.)

- [ ] **Step 9: Verify dist looks loadable**

```bash
npm run build
ls dist/
```

Expected: `manifest.json popup.html popup.js background.js content.js icons/`.

Load `dist/` as unpacked in Chrome and check the action icon appears in the toolbar.

- [ ] **Step 10: Commit**

```bash
cd /Users/chikaki/Development/freewise
git add extensions/kindle-importer/
git commit -m "feat(extension): MV3 skeleton (manifest, popup, vite, vitest)"
```

---

# Phase H — Content script DOM extraction

### Task H.1: Vitest fixture-based test for kindle-extract

**Files:**
- Create: `extensions/kindle-importer/test/fixtures/notebook-en.html`
- Create: `extensions/kindle-importer/test/extract.test.ts`
- Create: `extensions/kindle-importer/src/lib/kindle-extract.ts`
- Create: `extensions/kindle-importer/src/lib/selectors.ts`

- [ ] **Step 1: Write a small Amazon notebook HTML fixture**

Create `test/fixtures/notebook-en.html`. Hand-craft a minimal page that mirrors the real `read.amazon.com/kp/notebook` structure (use the selectors from `shared/kindle-selectors.json`):

```html
<!doctype html>
<html><body>
  <div id="kp-notebook-library">
    <div class="kp-notebook-library-each-book"
         data-asin="B07TEST1"
         id="B07TEST1">
      <h2 class="kp-notebook-searchable">Test Book One</h2>
      <p class="kp-notebook-searchable">Test Author One</p>
      <img class="kp-notebook-cover-image" src="https://example.com/cover1.jpg">
    </div>
  </div>

  <div id="kp-notebook-annotations">
    <div class="a-row a-spacing-base a-spacing-top-medium" id="QID:1">
      <span id="highlight" class="kp-notebook-highlight-yellow">First highlight text.</span>
      <span id="kp-annotation-location">Location 100</span>
    </div>
    <div class="a-row a-spacing-base a-spacing-top-medium" id="QID:2">
      <span id="highlight" class="kp-notebook-highlight-blue">Second highlight.</span>
      <span id="note">A user note.</span>
      <span id="kp-annotation-location">Location 250</span>
    </div>
  </div>
</body></html>
```

- [ ] **Step 2: Write the failing test**

`test/extract.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { Window } from 'happy-dom';
import { readFileSync } from 'fs';
import { resolve } from 'path';

import { extractCurrentBookHighlights } from '../src/lib/kindle-extract';

const fixture = readFileSync(
  resolve(__dirname, 'fixtures/notebook-en.html'),
  'utf-8'
);

describe('extractCurrentBookHighlights', () => {
  it('returns the highlights present on the page', () => {
    const win = new Window();
    win.document.write(fixture);
    const highlights = extractCurrentBookHighlights(win.document as unknown as Document);
    expect(highlights).toHaveLength(2);
    expect(highlights[0]).toMatchObject({
      id: 'QID:1',
      text: 'First highlight text.',
      color: 'yellow',
      location: 100,
    });
    expect(highlights[1]).toMatchObject({
      id: 'QID:2',
      text: 'Second highlight.',
      note: 'A user note.',
      color: 'blue',
      location: 250,
    });
  });
});
```

Add `vitest.config.ts`:

```typescript
import { defineConfig } from 'vitest/config';
export default defineConfig({
  test: { environment: 'happy-dom', globals: true },
});
```

- [ ] **Step 3: Run test, expect failure**

```bash
cd extensions/kindle-importer
npm run test
```

Expected: `Cannot find module '../src/lib/kindle-extract'`.

- [ ] **Step 4: Implement selectors loader**

`src/lib/selectors.ts`:

```typescript
import sharedSelectors from '../../../../shared/kindle-selectors.json' with { type: 'json' };

export type KindleSelectors = typeof sharedSelectors;
export const SELECTORS = sharedSelectors as KindleSelectors;
```

(Adjust the relative path if the build doesn't resolve — Vite supports `import json` natively. If it complains about the `with` syntax, drop it for plain `import`.)

- [ ] **Step 5: Implement kindle-extract**

`src/lib/kindle-extract.ts`:

```typescript
import { SELECTORS } from './selectors';

export type KindleHighlight = {
  id: string;
  text: string;
  note: string | null;
  color: 'yellow' | 'blue' | 'pink' | 'orange' | null;
  location: number | null;
  page: number | null;
  created_at: null;  // Kindle never exposes this
};

export type KindleBook = {
  asin: string;
  title: string;
  author: string | null;
  cover_url: string | null;
  highlights: KindleHighlight[];
};

function querySelectorAny(root: ParentNode, selectors: string[]): Element | null {
  for (const s of selectors) {
    const found = root.querySelector(s);
    if (found) return found;
  }
  return null;
}

function parseLocation(text: string): number | null {
  // "Location 100" or "Page 45" or "Location 1,234"
  const match = text.match(/(\d[\d,]*)/);
  if (!match) return null;
  return parseInt(match[1].replace(/,/g, ''), 10);
}

function colorFromClass(el: Element): KindleHighlight['color'] {
  const prefix = SELECTORS.highlight_color_prefix;
  for (const cls of Array.from(el.classList)) {
    if (cls.startsWith(prefix)) {
      const color = cls.slice(prefix.length);
      if (['yellow', 'blue', 'pink', 'orange'].includes(color)) {
        return color as KindleHighlight['color'];
      }
    }
  }
  return null;
}

export function extractCurrentBookHighlights(doc: Document): KindleHighlight[] {
  const container = querySelectorAny(doc, SELECTORS.annotation_container);
  if (!container) return [];

  const rows = container.querySelectorAll(SELECTORS.annotation_row);
  const out: KindleHighlight[] = [];

  for (const row of Array.from(rows)) {
    const id = row.id || row.getAttribute('data-id');
    const textEl = row.querySelector(SELECTORS.highlight_text);
    if (!id || !textEl) continue;

    const noteEl = row.querySelector(SELECTORS.note_text);
    const locEl = row.querySelector(SELECTORS.location_text);
    const locText = locEl?.textContent ?? '';

    out.push({
      id,
      text: (textEl.textContent ?? '').trim(),
      note: noteEl ? (noteEl.textContent ?? '').trim() : null,
      color: colorFromClass(textEl),
      location: locText.toLowerCase().includes('location') ? parseLocation(locText) : null,
      page: locText.toLowerCase().includes('page') ? parseLocation(locText) : null,
      created_at: null,
    });
  }
  return out;
}

export function extractLibrary(doc: Document): KindleBook[] {
  const container = querySelectorAny(doc, SELECTORS.library_container);
  if (!container) return [];

  const rows = container.querySelectorAll(SELECTORS.library_row);
  const out: KindleBook[] = [];

  for (const row of Array.from(rows)) {
    const asin = row.getAttribute('data-asin') ?? row.id;
    if (!asin) continue;
    const titleEl = row.querySelector(SELECTORS.book_title);
    const authorEl = row.querySelector(SELECTORS.book_author);
    const coverEl = row.querySelector(SELECTORS.book_cover_image) as HTMLImageElement | null;
    out.push({
      asin,
      title: (titleEl?.textContent ?? '').trim(),
      author: authorEl ? (authorEl.textContent ?? '').trim() : null,
      cover_url: coverEl?.src ?? null,
      highlights: [],  // populated by extractCurrentBookHighlights() per book
    });
  }
  return out;
}
```

- [ ] **Step 6: Run tests, expect green**

```bash
npm run test
```

Expected: `extract.test.ts` passes.

- [ ] **Step 7: Commit**

```bash
cd /Users/chikaki/Development/freewise
git add extensions/kindle-importer/
git commit -m "feat(extension): kindle-extract DOM scraping core + tests

Pure-function highlight + library extractors driven by
shared/kindle-selectors.json. Tested against an HTML fixture mirroring
the real read.amazon.com/kp/notebook structure."
```

### Task H.2: Schema validator wrapper

**Files:**
- Create: `extensions/kindle-importer/src/lib/schema-validate.ts`
- Test: `extensions/kindle-importer/test/schema-validate.test.ts`

- [ ] **Step 1: Failing test**

`test/schema-validate.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { validateExportEnvelope } from '../src/lib/schema-validate';

describe('validateExportEnvelope', () => {
  it('accepts a valid minimal envelope', () => {
    const result = validateExportEnvelope({
      schema_version: '1.0',
      exported_at: '2026-04-29T00:00:00Z',
      source: 'kindle_notebook',
      books: [],
    });
    expect(result.ok).toBe(true);
  });

  it('rejects a missing books field', () => {
    const result = validateExportEnvelope({
      schema_version: '1.0',
      exported_at: '2026-04-29T00:00:00Z',
      source: 'kindle_notebook',
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors[0].path).toContain('books');
  });
});
```

- [ ] **Step 2: Implement**

`src/lib/schema-validate.ts`:

```typescript
import Ajv, { type ErrorObject } from 'ajv';
import addFormats from 'ajv-formats';
import schema from '../../../../shared/kindle-export-v1.schema.json' with { type: 'json' };

const ajv = new Ajv({ allErrors: true, strict: false });
addFormats(ajv);
const validate = ajv.compile(schema);

export type ValidationResult =
  | { ok: true }
  | { ok: false; errors: { path: string; message: string }[] };

export function validateExportEnvelope(payload: unknown): ValidationResult {
  if (validate(payload)) return { ok: true };
  const errors = (validate.errors ?? []).map((e: ErrorObject) => ({
    path: e.instancePath || e.schemaPath || '(root)',
    message: e.message ?? 'unknown error',
  }));
  return { ok: false, errors };
}
```

Add `ajv-formats` to `package.json` dependencies:

```json
"dependencies": {
  "ajv": "^8.17.1",
  "ajv-formats": "^3.0.1"
}
```

- [ ] **Step 3: Install + run tests**

```bash
cd extensions/kindle-importer
npm install
npm run test
```

Expected: green.

- [ ] **Step 4: Commit**

```bash
cd /Users/chikaki/Development/freewise
git add extensions/kindle-importer/
git commit -m "feat(extension): ajv-based schema validation against shared schema"
```

### Task H.3: Per-book scrape orchestrator + content script main loop

**Files:**
- Modify: `extensions/kindle-importer/src/content.ts`

- [ ] **Step 1: Implement the orchestrator**

Replace the stub `content.ts` with:

```typescript
import { extractLibrary, extractCurrentBookHighlights, KindleBook } from './lib/kindle-extract';
import { validateExportEnvelope } from './lib/schema-validate';
import { SELECTORS } from './lib/selectors';

const POLL_INTERVAL_MS = 200;
const POLL_MAX_TRIES = 50;  // 10s
const PER_BOOK_TIMEOUT_MS = 5000;

async function waitForLibrary(): Promise<boolean> {
  for (let i = 0; i < POLL_MAX_TRIES; i++) {
    for (const sel of SELECTORS.library_container) {
      if (document.querySelector(sel)) return true;
    }
    await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));
  }
  return false;
}

async function clickAndWaitForHighlights(asin: string): Promise<void> {
  const row = document.querySelector<HTMLElement>(`[data-asin="${asin}"], [id="${asin}"]`);
  if (!row) throw new Error(`book row not found for asin=${asin}`);
  row.click();

  const start = Date.now();
  while (Date.now() - start < PER_BOOK_TIMEOUT_MS) {
    // Check that the annotation container has rendered something for THIS book.
    // The highlight row's data-asin (or just any annotation row) is enough.
    for (const sel of SELECTORS.annotation_container) {
      const c = document.querySelector(sel);
      if (c && c.querySelectorAll(SELECTORS.annotation_row).length > 0) return;
    }
    await new Promise(r => setTimeout(r, 100));
  }
  // No highlights for this book — that's a valid empty state, not an error.
}

async function scrapeAll(port: chrome.runtime.Port): Promise<void> {
  if (document.prerendering) {
    port.postMessage({ type: 'aborted', reason: 'prerendering' });
    return;
  }

  const libraryReady = await waitForLibrary();
  if (!libraryReady) {
    port.postMessage({ type: 'error', reason: 'library not found within 10s' });
    return;
  }

  const books = extractLibrary(document);
  port.postMessage({ type: 'progress', current: 0, total: books.length });

  for (let i = 0; i < books.length; i++) {
    const book = books[i];
    try {
      await clickAndWaitForHighlights(book.asin);
      book.highlights = extractCurrentBookHighlights(document);
    } catch (err) {
      // Per-book failure: keep highlights empty, record error in port message
      port.postMessage({
        type: 'book_error',
        book_title: book.title,
        reason: String(err),
      });
    }
    port.postMessage({ type: 'progress', current: i + 1, total: books.length });
  }

  const envelope = {
    schema_version: '1.0',
    exported_at: new Date().toISOString(),
    source: 'kindle_notebook',
    books,
  };

  const validation = validateExportEnvelope(envelope);
  if (!validation.ok) {
    port.postMessage({
      type: 'error',
      reason: 'schema validation failed: ' + JSON.stringify(validation.errors),
    });
    return;
  }

  port.postMessage({ type: 'done', payload: envelope });
}

// Entry: open port to SW, wait for 'start', run scrape.
const port = chrome.runtime.connect({ name: 'kindle-sync' });

port.onMessage.addListener((msg) => {
  if (msg?.type === 'start') {
    scrapeAll(port).catch((err) => {
      port.postMessage({ type: 'error', reason: String(err) });
    });
  }
});
```

- [ ] **Step 2: Build to make sure no TS errors**

```bash
cd extensions/kindle-importer
npm run build
```

Expected: `dist/content.js` produced, no TS errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/chikaki/Development/freewise
git add extensions/kindle-importer/src/content.ts
git commit -m "feat(extension): content-script orchestrator iterates library + scrapes"
```

---

# Phase I — Popup UI

### Task I.1: Settings tab + storage

**Files:**
- Modify: `extensions/kindle-importer/src/popup.ts`
- Modify: `extensions/kindle-importer/src/popup.html`
- Modify: `extensions/kindle-importer/src/popup.css`
- Create: `extensions/kindle-importer/src/lib/storage.ts`

- [ ] **Step 1: Implement storage helpers**

`src/lib/storage.ts`:

```typescript
export type Settings = {
  server_url: string;  // e.g. 'https://freewiseapi.chikaki.com'
  token: string;
};

export async function loadSettings(): Promise<Settings | null> {
  const data = await chrome.storage.local.get(['server_url', 'token']);
  if (!data.server_url || !data.token) return null;
  return { server_url: data.server_url, token: data.token };
}

export async function saveSettings(s: Settings): Promise<void> {
  await chrome.storage.local.set({
    server_url: s.server_url.replace(/\/+$/, ''),  // strip trailing slash
    token: s.token,
  });
}
```

- [ ] **Step 2: Update popup HTML**

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="popup.css">
</head>
<body class="w-80 p-3 text-sm font-sans">
  <h1 class="text-base font-bold mb-3">FreeWise Kindle Importer</h1>

  <div id="root"></div>

  <script type="module" src="popup.ts"></script>
</body>
</html>
```

- [ ] **Step 3: Implement popup logic**

`src/popup.ts`:

```typescript
import { loadSettings, saveSettings } from './lib/storage';

const root = document.getElementById('root')!;

async function render() {
  const settings = await loadSettings();
  if (!settings) {
    renderSettings();
  } else {
    renderMain(settings);
  }
}

function renderSettings() {
  root.innerHTML = `
    <p class="mb-2">Configure your FreeWise server to start.</p>
    <label class="block mb-2">
      <span class="text-xs">Server URL</span>
      <input id="server" type="url"
             placeholder="https://freewiseapi.chikaki.com"
             class="w-full border px-1 py-0.5 mt-0.5">
    </label>
    <label class="block mb-2">
      <span class="text-xs">API Token</span>
      <input id="token" type="password"
             class="w-full border px-1 py-0.5 mt-0.5">
    </label>
    <button id="save" class="w-full py-1 bg-blue-600 text-white rounded">
      Save
    </button>
  `;
  document.getElementById('save')!.addEventListener('click', async () => {
    const server_url = (document.getElementById('server') as HTMLInputElement).value.trim();
    const token = (document.getElementById('token') as HTMLInputElement).value.trim();
    if (!server_url || !token) {
      alert('Both fields are required.');
      return;
    }
    await saveSettings({ server_url, token });
    render();
  });
}

function renderMain(settings: { server_url: string; token: string }) {
  root.innerHTML = `
    <div id="status" class="mb-3 text-xs text-gray-500">Ready</div>
    <button id="sync" class="w-full py-2 bg-blue-600 text-white rounded mb-2">
      Sync now
    </button>
    <div id="progress" class="text-xs text-gray-600"></div>
    <div id="result" class="mt-3 p-2 rounded bg-gray-50 text-xs hidden"></div>
    <button id="settings-link" class="mt-3 text-xs text-blue-600 underline">
      Edit settings
    </button>
  `;

  document.getElementById('settings-link')!.addEventListener('click', () => {
    chrome.storage.local.clear().then(render);
  });

  document.getElementById('sync')!.addEventListener('click', () => {
    chrome.runtime.sendMessage({ type: 'sync_now' });
  });

  // Subscribe to SW broadcasts.
  chrome.runtime.onMessage.addListener((msg) => {
    handlePopupMessage(msg);
  });
}

function handlePopupMessage(msg: any) {
  const status = document.getElementById('status');
  const progress = document.getElementById('progress');
  const result = document.getElementById('result');
  if (!status || !progress || !result) return;

  switch (msg?.type) {
    case 'progress':
      progress.textContent = `Scanning ${msg.current}/${msg.total} books…`;
      break;
    case 'tab_opening':
      status.textContent = 'Opening read.amazon.com…';
      break;
    case 'login_required':
      status.textContent = '';
      result.textContent = 'Please log in to read.amazon.com first.';
      result.classList.remove('hidden');
      result.classList.add('bg-yellow-50');
      break;
    case 'sync_complete': {
      const { result: r } = msg;
      result.classList.remove('hidden');
      result.classList.remove('bg-yellow-50');
      result.classList.add('bg-emerald-50');
      result.textContent = formatResult(r);
      progress.textContent = '';
      break;
    }
    case 'error':
      result.classList.remove('hidden');
      result.classList.add('bg-red-50');
      result.textContent = `Error: ${msg.reason}`;
      progress.textContent = '';
      break;
  }
}

function formatResult(r: any): string {
  const created = r.highlights_created ?? 0;
  const dup = r.highlights_skipped_duplicates ?? 0;
  if (created > 0 && dup === 0) return `✓ Synced ${created} highlights`;
  if (created > 0) return `✓ Added ${created} new · ${dup} already in your library`;
  if (dup > 0) return `✓ Library up to date (${dup} highlights, no changes)`;
  return `⚠ No highlights found.`;
}

render();
```

- [ ] **Step 4: Build + smoke**

```bash
npm run build
```

Reload extension in `chrome://extensions/`. Click icon → settings form should appear.

- [ ] **Step 5: Commit**

```bash
cd /Users/chikaki/Development/freewise
git add extensions/kindle-importer/src/
git commit -m "feat(extension): popup with settings + sync UI

Settings tab on first install (manual server_url + token paste).
Main view: Sync now button, progress, contextual result messages."
```

---

# Phase J — Background SW

### Task J.1: Implement SW: tab management + port + POST

**Files:**
- Modify: `extensions/kindle-importer/src/background.ts`

- [ ] **Step 1: Implement the SW**

```typescript
import { loadSettings } from './lib/storage';

const NOTEBOOK_URL = 'https://read.amazon.com/kp/notebook';
const TAB_LOAD_TIMEOUT_MS = 60_000;

let currentSyncTab: number | null = null;
let currentPort: chrome.runtime.Port | null = null;

chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.type === 'sync_now') {
    void startSync();
  }
});

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== 'kindle-sync') return;
  currentPort = port;

  port.onMessage.addListener((msg) => {
    if (msg?.type === 'progress') {
      void chrome.runtime.sendMessage({
        type: 'progress', current: msg.current, total: msg.total,
      });
    } else if (msg?.type === 'book_error') {
      // Forward to popup later in result.
      collectedErrors.push({ book_title: msg.book_title, reason: msg.reason });
    } else if (msg?.type === 'done') {
      void onScrapeComplete(msg.payload).catch((e) => {
        void chrome.runtime.sendMessage({ type: 'error', reason: String(e) });
      });
    } else if (msg?.type === 'error') {
      void chrome.runtime.sendMessage({ type: 'error', reason: msg.reason });
      cleanup();
    } else if (msg?.type === 'aborted') {
      cleanup();
    }
  });

  port.onDisconnect.addListener(() => {
    if (currentPort === port) currentPort = null;
  });

  // Tell content script to start.
  port.postMessage({ type: 'start' });
});

let collectedErrors: { book_title: string; reason: string }[] = [];

async function startSync(): Promise<void> {
  collectedErrors = [];
  await chrome.runtime.sendMessage({ type: 'tab_opening' });

  const tab = await chrome.tabs.create({ url: NOTEBOOK_URL, active: false });
  if (!tab.id) {
    void chrome.runtime.sendMessage({ type: 'error', reason: 'tab.create returned no id' });
    return;
  }
  currentSyncTab = tab.id;

  // Watch for login redirect.
  const tabId = tab.id;
  const start = Date.now();
  const handler = (updatedId: number, info: chrome.tabs.TabChangeInfo, t: chrome.tabs.Tab) => {
    if (updatedId !== tabId) return;
    if (info.status === 'complete' && t.url) {
      if (!t.url.startsWith('https://read.amazon.com/kp/notebook')) {
        chrome.tabs.onUpdated.removeListener(handler);
        void chrome.runtime.sendMessage({ type: 'login_required' });
        cleanup();
      }
    }
  };
  chrome.tabs.onUpdated.addListener(handler);

  // Safety timeout.
  setTimeout(() => {
    if (currentSyncTab !== null && Date.now() - start > TAB_LOAD_TIMEOUT_MS) {
      void chrome.runtime.sendMessage({
        type: 'error',
        reason: 'Tab did not finish loading within 60s',
      });
      cleanup();
    }
  }, TAB_LOAD_TIMEOUT_MS + 1000);
}

async function onScrapeComplete(payload: any): Promise<void> {
  const settings = await loadSettings();
  if (!settings) {
    void chrome.runtime.sendMessage({
      type: 'error',
      reason: 'No server configured. Open settings first.',
    });
    cleanup();
    return;
  }

  // Inject collected per-book errors into the result reporting.
  const url = `${settings.server_url}/api/v2/imports/kindle`;

  // gzip the body.
  const json = JSON.stringify(payload);
  const compressed = await gzipString(json);

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `Token ${settings.token}`,
        'Content-Type': 'application/json',
        'Content-Encoding': 'gzip',
      },
      body: compressed,
    });
  } catch (err) {
    void chrome.runtime.sendMessage({
      type: 'error',
      reason: `FreeWise unreachable: ${String(err)}`,
    });
    cleanup();
    return;
  }

  if (response.status === 401) {
    void chrome.runtime.sendMessage({ type: 'error', reason: 'Token rejected (401)' });
    cleanup();
    return;
  }
  if (!response.ok) {
    const text = await response.text();
    void chrome.runtime.sendMessage({
      type: 'error', reason: `HTTP ${response.status}: ${text.slice(0, 200)}`,
    });
    cleanup();
    return;
  }

  const result = await response.json();
  if (collectedErrors.length > 0) {
    result.errors = (result.errors ?? []).concat(collectedErrors);
  }
  void chrome.runtime.sendMessage({ type: 'sync_complete', result });
  cleanup();
}

async function gzipString(s: string): Promise<Uint8Array> {
  const stream = new Response(new Blob([s]).stream().pipeThrough(
    new CompressionStream('gzip')
  ));
  return new Uint8Array(await stream.arrayBuffer());
}

function cleanup() {
  if (currentSyncTab !== null) {
    chrome.tabs.remove(currentSyncTab).catch(() => {});
    currentSyncTab = null;
  }
  currentPort = null;
}

console.info('FreeWise Kindle Importer SW ready');
```

- [ ] **Step 2: Build + smoke**

```bash
cd extensions/kindle-importer
npm run build
```

Reload the extension in Chrome. Click icon → "Sync now" → observe network tab for the POST.

- [ ] **Step 3: Commit**

```bash
cd /Users/chikaki/Development/freewise
git add extensions/kindle-importer/src/background.ts
git commit -m "feat(extension): background SW — tab, port, POST, gzip

- Opens hidden read.amazon.com tab
- Listens for content-script port; forwards progress to popup
- Detects login-required redirect via tabs.onUpdated final URL
- gzips body via CompressionStream then POSTs with bearer token
- Surfaces error matrix from spec § 11"
```

---

# Phase K — End-to-end smoke + dogfood

### Task K.1: Manual end-to-end against production

- [ ] **Step 1: Generate a kindle:import-scoped token**

In FreeWise dashboard → `/settings/api-tokens` → create token named `chrome-extension`. (If scope picker UI not yet built, create with default and accept full-access for MVP, file scope-picker as fast-follow.)

Copy the value.

- [ ] **Step 2: Configure the extension**

Open extension popup → Settings:
- Server URL: `https://freewiseapi.chikaki.com`
- Token: pasted value
- Save.

- [ ] **Step 3: Trigger a sync**

Click toolbar icon → Sync now. Observe:
- Status: "Opening read.amazon.com…"
- Progress: "Scanning N/M books…"
- Final: "Library up to date (141 highlights, no changes)" (matches § 9 First-sync UX).

- [ ] **Step 4: Verify on FreeWise side**

```bash
ssh qnap "curl -s http://localhost:8063/highlights/api/stats" 2>&1 | head
```

Highlight count should match Amazon's notebook count, no spurious duplicates.

- [ ] **Step 5: Verify cookie upload page**

Visit `https://freewise.chikaki.com/dashboard/kindle/cookie`. Upload a known-good `storage_state.json`. Confirm status updates.

- [ ] **Step 6: Failure-mode walkthroughs**

Manually exercise:
- Log out of Amazon → click Sync now → should show "Please log in".
- Bad token → should show "Token rejected".
- Server URL wrong → should show "FreeWise unreachable".
- Upload non-JSON to cookie page → should show 400.

### Task K.2: Documentation

- [ ] **Step 1: Update README**

Add a section to `README.md` describing the extension + cookie upload + the demoted monthly fallback.

- [ ] **Step 2: Update `docs/KINDLE_JSON_SCHEMA.md`**

Add a paragraph noting `errors` is now `list[dict]`, link to the JSON Schema in `shared/`.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/KINDLE_JSON_SCHEMA.md
git commit -m "docs: extension + cookie upload + errors shape"
```

### Task K.3: Stop the daily QNAP cron

- [ ] **Step 1: Edit QNAP crontab**

```bash
ssh qnap "crontab -l | grep -v 'kindle_dl' | crontab -"
ssh qnap "crontab -l | grep kindle"
```

Expected: only the monthly entry remains.

- [ ] **Step 2: Add a monthly entry (1st of month, 03:00 JST)**

```bash
ssh qnap "(crontab -l; echo '0 3 1 * * /share/Container/freewise/kindle/kindle_dl.sh > /tmp/kindle_dl.log 2>&1') | crontab -"
ssh qnap "crontab -l | grep kindle"
```

(No commit — operational change.)

---

# Self-Review

Spec coverage check (against `docs/superpowers/specs/2026-04-29-kindle-browser-extension-design.md`):

| Spec section | Plan task |
|---|---|
| § 1 Problem & Goal | Phase 0–K (whole plan) |
| § 2a Repo consolidation | Phase 0 |
| § 4 User flow | Phase H, I, J |
| § 5 Cloudflare | Phase A |
| § 6 Extension structure | Phase G, H, I, J |
| § 7 FreeWise endpoints | Phase D (POST kindle), Phase F (cookie) |
| § 8 Shared selector + schema | Phase B (selectors), Phase C (schema) |
| § 9 First-sync UX | Phase I (`formatResult` in popup.ts) |
| § 10 Coverage & limitations | Phase K.2 (documentation) |
| § 11 Error matrix | Phase J (SW handlers) + Phase I (popup display) |
| § 12 Performance | Phase J (gzip), Phase D (request middleware) |
| § 13 Atomic write | Phase F (kindle_cookie service) |
| § 14 Testing | Phases B/C/D/E/F (Python pytest), H (Vitest), K.1 (manual E2E) |
| § 15 File layout | matches plan's File map header |
| § 16 QNAP sunset | Phase K.3 (cron pruning today; full sunset documented in spec, not in v1 plan) |
| § 17 Implementation phases | matches Phases 0–K |
| § 18 Decision log | (no implementation needed) |
| § 19 Open questions | partially addressed in Phase A (CF inspection) and Phase G.8 (icons) |

No gaps.

Placeholder scan: zero TBDs. Every code step shows code; every command shows expected output or assertion.

Type consistency check:
- `KindleImportResult.errors` type changes once (Phase C.4) and all later references match.
- `Settings` type defined in `storage.ts`, used unchanged in `popup.ts` and `background.ts`.
- Selector-loading pattern (`SELECTORS.library_container` etc.) consistent in `kindle-extract.ts` and `content.ts`.
- Port message types (`progress | book_error | done | error | aborted | start | login_required | tab_opening | sync_complete`) consistent across content / SW / popup.

No fixes required.

---

## Out of scope (recorded)

- Phase 2 background scheduling (`chrome.alarms`) — explicitly deferred per spec § 2.
- Multi-user, Firefox/Safari, Web Store distribution.
- "Verify cookie" live-test button in the cookie UI — fast-follow, not v1.
- Per-book streaming POST.
- ApiToken UI scope picker (Phase E adds the column + dependency, but the dashboard UI to pick scopes when creating a token is a v1.1 enhancement; v1 tokens default to full access if `scopes IS NULL`).
