#!/usr/bin/env bash
# End-to-end runner for the Chrome extension.
#
# 1. Boots a fresh uvicorn instance on :8064 backed by a temp SQLite file.
# 2. Mints an ApiToken via the same code path the import page uses.
# 3. Runs the Playwright spec set against http://127.0.0.1:8064.
# 4. Tears down uvicorn whether the suite passed or not.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
E2E_DIR="$REPO_ROOT/extensions/chrome/e2e"
PORT="${FREEWISE_E2E_PORT:-8064}"
DB_FILE="$(mktemp -t freewise-e2e-XXXXXX.db)"
LOG_FILE="$(mktemp -t freewise-e2e-XXXXXX.log)"

cleanup() {
  if [[ -n "${UVICORN_PID:-}" ]] && kill -0 "$UVICORN_PID" 2>/dev/null; then
    kill "$UVICORN_PID" 2>/dev/null || true
    wait "$UVICORN_PID" 2>/dev/null || true
  fi
  rm -f "$DB_FILE" "$DB_FILE-shm" "$DB_FILE-wal" "$LOG_FILE"
}
trap cleanup EXIT

cd "$REPO_ROOT"

echo "[e2e] Starting uvicorn on :$PORT (db=$DB_FILE)"
export FREEWISE_DB_URL="sqlite:///$DB_FILE"
uv run uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning \
  >"$LOG_FILE" 2>&1 &
UVICORN_PID=$!

# Wait for /healthz.
for _ in $(seq 1 60); do
  if curl -fs "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
if ! curl -fs "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
  echo "[e2e] uvicorn never came up. Tail:"
  tail -n 50 "$LOG_FILE"
  exit 1
fi

echo "[e2e] Minting API token via Python helper"
TOKEN=$(
  uv run python - <<'PY'
import secrets
import hashlib
from sqlmodel import Session, select
from app.db import get_engine, ensure_schema_migrations
from app.models import ApiToken, User

engine = get_engine()
ensure_schema_migrations(engine)
raw = "fw_e2e_" + secrets.token_hex(16)
with Session(engine) as s:
    if not s.exec(select(User).where(User.id == 1)).first():
        s.add(User(id=1, email="e2e@local", password_hash="x"))
    s.add(
        ApiToken(
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            token_prefix=raw[:16],
            name="e2e",
            user_id=1,
            scopes="kindle:import,highlights:read,highlights:write,books:read",
        )
    )
    s.commit()
print(raw)
PY
)
echo "[e2e] Token: ${TOKEN:0:12}…"

cd "$E2E_DIR"
if [[ ! -d node_modules ]]; then
  echo "[e2e] Installing JS deps"
  npm install --no-audit --no-fund --silent
  npx --yes playwright install chromium >/dev/null
fi

echo "[e2e] Running Playwright"
FREEWISE_E2E_BASE_URL="http://127.0.0.1:$PORT" \
FREEWISE_E2E_TOKEN="$TOKEN" \
  npx playwright test "$@"
