#!/bin/sh
# Pre-flight check on storage_state.json freshness — based on the actual
# cookie expiry timestamps inside the file (not its mtime).
#
# Why this exists alongside kindle_check_state.sh: the mtime-based check is a
# coarse heuristic ("file is N days old → probably stale"). It can mislead in
# both directions:
#   - false-positive: a freshly re-saved storage_state still containing
#     long-since-expired Amazon cookies (impossible in practice but
#     defensible as a sanity check).
#   - false-negative: a never-touched storage_state whose Amazon cookies
#     are 360 days young (plausible for cookies with a 1-year TTL).
#
# This script reads the actual `expires` field from each cookie whose domain
# is on amazon.com, and reports the soonest non-session expiry as the
# worst-case session death time.
#
# Usage:
#   kindle_check_state_cookies.sh [warn_days] [error_days] [state_path]
#
# Exit codes (mirrors kindle_check_state.sh so callers can treat them the same):
#   0  ok       — soonest amazon cookie expires > warn_days from now
#   1  unknown  — file missing, unreadable, no usable amazon cookies, or parse error
#   2  aging    — soonest amazon cookie expires within warn_days
#   3  stale    — soonest amazon cookie expires within error_days
#   3  expired  — soonest amazon cookie has already expired (still rc=3)
#
# Output (one line, tab-separated):
#   <status>\t<min_days>\t<message>
# where <status> ∈ {ok, aging, stale, expired, unknown}
#
# Parsing strategy:
#   1. Prefer `jq` if present on $PATH (one binary, fast, no docker).
#   2. Fallback: invoke python3 INSIDE the kindle-scraper-qnap:latest image
#      (QNAP busybox has no python3). Same pattern as
#      tools/cookies_normalize.py being run by safaribooks_dl.sh in the
#      freewise-qnap-deploy worktree.
set -eu

WARN_DAYS="${1:-${KINDLE_COOKIE_WARN_DAYS:-7}}"
ERROR_DAYS="${2:-${KINDLE_COOKIE_ERROR_DAYS:-3}}"
STATE_PATH="${3:-${KINDLE_STATE_PATH:-/share/Container/freewise/state/kindle/storage_state.json}}"

# Optional comma-separated allowlist of cookie names to consider. If set,
# only cookies whose `name` is in this list contribute to the verdict.
# Default empty → fall back to "all amazon.com cookies", which is the
# conservative behaviour that may flag non-auth cookies (id_pkel etc).
# Once you've correlated auth failures with specific cookies (see Lessons
# Learned #6 in docs/KINDLE_STATUS.md), set this to e.g.
#   at-main,sess-at-main,ubid-main,session-id
# to silence false-positive alerts.
COOKIE_NAMES="${KINDLE_COOKIE_FILTER_NAMES:-}"

if [ ! -s "${STATE_PATH}" ]; then
  printf 'unknown\t-\tstorage_state.json missing or empty: %s\n' "${STATE_PATH}"
  exit 1
fi

NOW=$(date +%s)

# Compute "<min_expires_epoch>\t<cookie_name>" for the soonest-expiring
# amazon.com cookie that has a real (non-session) expiry. Empty stdout =>
# no usable cookies (all session-only or no amazon cookies at all).
parse_with_jq() {
  # `expires > 0` filters out -1 (session) and 0 (some exporters use 0 for session).
  # `domain` is stored with or without leading dot (".amazon.com" / "www.amazon.com");
  # `endswith("amazon.com")` covers both.
  # COOKIE_NAMES (env): if set, restrict to cookies whose name is in the list.
  jq -r --arg names "${COOKIE_NAMES}" '
    ($names | split(",") | map(select(. != ""))) as $allow
    | [ .cookies[]?
        | select((.expires | type) == "number")
        | select(.expires > 0)
        | select(.domain | type == "string")
        | select(.domain | endswith("amazon.com"))
        | select(($allow | length) == 0 or (.name as $n | $allow | index($n)))
      ]
    | sort_by(.expires)
    | .[0]
    | if . == null then empty else "\(.expires)\t\(.name)" end
  ' "${STATE_PATH}" 2>/dev/null
}

parse_with_docker_python() {
  # Run python3 inside the kindle-scraper-qnap image (the same image kindle_dl.sh
  # uses), with the storage_state file bind-mounted read-only at a known path.
  STATE_DIR=$(dirname "${STATE_PATH}")
  STATE_FILE=$(basename "${STATE_PATH}")
  docker run --rm \
    -v "${STATE_DIR}:/work/state:ro" \
    -e COOKIE_NAMES="${COOKIE_NAMES}" \
    --entrypoint python3 kindle-scraper-qnap:latest -c '
import json, os, sys
try:
    with open("/work/state/'"${STATE_FILE}"'") as f:
        data = json.load(f)
except Exception as e:
    sys.exit(0)  # silent: emits nothing → caller treats as unknown
allow = {n for n in (os.environ.get("COOKIE_NAMES") or "").split(",") if n}
best = None
for c in data.get("cookies", []) or []:
    exp = c.get("expires")
    dom = c.get("domain") or ""
    name = c.get("name") or "?"
    if not isinstance(exp, (int, float)):
        continue
    if exp <= 0:
        continue
    if not dom.endswith("amazon.com"):
        continue
    if allow and name not in allow:
        continue
    if best is None or exp < best[0]:
        best = (exp, name)
if best is not None:
    print("%s\t%s" % (int(best[0]), best[1]))
' 2>/dev/null
}

# QNAP's Container Station ships docker outside of any default PATH. We append
# the canonical install location so the docker fallback is reachable when this
# script is invoked via plain `ssh qnap script.sh` (which gets a sparse env).
export PATH="${PATH}:/share/CACHEDEV1_DATA/.qpkg/container-station/bin"

LINE=""
if command -v jq >/dev/null 2>&1; then
  set +e
  LINE=$(parse_with_jq)
  rc=$?
  set -e
  if [ "${rc}" -ne 0 ]; then
    printf 'unknown\t-\tjq failed to parse %s\n' "${STATE_PATH}"
    exit 1
  fi
elif command -v docker >/dev/null 2>&1; then
  set +e
  LINE=$(parse_with_docker_python)
  rc=$?
  set -e
  if [ "${rc}" -ne 0 ]; then
    printf 'unknown\t-\tcould not invoke docker python fallback (rc=%d)\n' "${rc}"
    exit 1
  fi
else
  printf 'unknown\t-\tneither jq nor docker available to parse cookies\n'
  exit 1
fi

if [ -z "${LINE}" ]; then
  printf 'unknown\t-\tno amazon.com cookies with non-session expiry in %s\n' "${STATE_PATH}"
  exit 1
fi

EXPIRES=$(printf '%s' "${LINE}" | awk -F'\t' '{print $1}')
NAME=$(printf '%s' "${LINE}"    | awk -F'\t' '{print $2}')

# Defensive: if jq emitted floats ("1811683446.5"), trim to integer seconds.
EXPIRES=$(printf '%s' "${EXPIRES}" | awk -F'.' '{print $1}')

case "${EXPIRES}" in
  ''|*[!0-9-]*)
    printf 'unknown\t-\tunparseable expires value: %s\n' "${EXPIRES}"
    exit 1
    ;;
esac

DELTA_S=$((EXPIRES - NOW))
# Round toward zero; for negative we still get the right bucket.
if [ "${DELTA_S}" -lt 0 ]; then
  # Already expired. Days since expiry, negated, useful for messaging.
  ABS_S=$((0 - DELTA_S))
  DAYS=$((0 - ABS_S / 86400))
else
  DAYS=$((DELTA_S / 86400))
fi

# Human-readable date for the message. `date -d @<epoch>` works on busybox
# and GNU; macOS BSD date uses `-r`.
WHEN=$(date -u -d "@${EXPIRES}" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null \
       || date -u -r "${EXPIRES}" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null \
       || printf 'epoch=%s' "${EXPIRES}")

# Bucket assignment. Most-pessimistic-first.
if [ "${DELTA_S}" -le 0 ]; then
  printf 'expired\t%d\tcookie %s expired on %s.\n' "${DAYS}" "${NAME}" "${WHEN}"
  exit 3
fi
if [ "${DAYS}" -le "${ERROR_DAYS}" ]; then
  printf 'stale\t%d\tcookie %s expires in %d day(s) (<= %d) at %s — re-run kindle_login.sh.\n' \
    "${DAYS}" "${NAME}" "${DAYS}" "${ERROR_DAYS}" "${WHEN}"
  exit 3
fi
if [ "${DAYS}" -le "${WARN_DAYS}" ]; then
  printf 'aging\t%d\tcookie %s expires in %d day(s) (<= %d) at %s — refresh soon.\n' \
    "${DAYS}" "${NAME}" "${DAYS}" "${WARN_DAYS}" "${WHEN}"
  exit 2
fi
printf 'ok\t%d\tcookie %s expires in %d day(s) at %s.\n' \
  "${DAYS}" "${NAME}" "${DAYS}" "${WHEN}"
exit 0
