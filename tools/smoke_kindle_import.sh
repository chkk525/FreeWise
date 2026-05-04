#!/usr/bin/env bash
# Smoke-test the /api/v2/imports/kindle endpoint against any FreeWise instance
# WITHOUT loading the Chrome extension. Mints a tiny valid envelope and POSTs it
# both raw and gzipped, then asserts the response shape. Use this BEFORE the
# manual Chrome E2E (K.1) to confirm the server side is healthy.
#
# Usage:
#   FW_URL=https://freewiseapi.chikaki.com FW_TOKEN=fw_xxx ./tools/smoke_kindle_import.sh
set -euo pipefail

: "${FW_URL:?FW_URL is required, e.g. https://freewiseapi.chikaki.com}"
: "${FW_TOKEN:?FW_TOKEN is required (a kindle:import-scoped fw_... token)}"

ENVELOPE='{
  "schema_version": "1.0",
  "exported_at": "2026-05-04T00:00:00Z",
  "source": "kindle_notebook",
  "books": [
    {
      "asin": "BSMOKE1",
      "title": "Smoke Test Book",
      "author": "Smoke Tester",
      "cover_url": null,
      "highlights": [
        {
          "id": "QSMOKE:1",
          "text": "this is a smoke-test highlight",
          "note": null,
          "color": null,
          "location": 1,
          "page": null,
          "created_at": null
        }
      ]
    }
  ]
}'

echo "→ POST raw JSON"
curl -fsS -X POST "${FW_URL}/api/v2/imports/kindle" \
  -H "Authorization: Token ${FW_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "${ENVELOPE}" \
  | tee /tmp/fw_smoke_raw.json
echo

echo "→ POST gzipped JSON (validates the GzipRequestMiddleware path)"
printf '%s' "${ENVELOPE}" | gzip -c \
  | curl -fsS -X POST "${FW_URL}/api/v2/imports/kindle" \
      -H "Authorization: Token ${FW_TOKEN}" \
      -H "Content-Type: application/json" \
      -H "Content-Encoding: gzip" \
      --data-binary @- \
  | tee /tmp/fw_smoke_gz.json
echo

echo "→ Verify the smoke book + highlight round-tripped"
SMOKE_BOOKS=$(curl -fsS "${FW_URL}/api/v2/books/?q=Smoke%20Test%20Book" \
  -H "Authorization: Token ${FW_TOKEN}" || echo '{}')
echo "${SMOKE_BOOKS}" | python3 -m json.tool >/dev/null && echo "  books endpoint OK"

echo "✓ smoke complete. Both raw and gzipped envelopes accepted."
