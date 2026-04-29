#!/bin/sh
# Cron-friendly wrapper around kindle_dl.sh.
#
# - Writes a date-stamped JSON next to ${KINDLE_OUTPUT_DIR}.
# - Maintains a stable symlink `kindle_highlights_latest.json` -> last success.
# - Appends a single status line per run to `${LOG_FILE}` (rotation handled
#   externally; the file is small).
# - On scrape failure: writes/updates `last_failure.txt`, classifies the
#   failure reason from the log tail, calls kindle_notify.sh, and exits
#   non-zero so QNAP cron mail (if configured) carries the rc.
#
# Designed to be called from /etc/config/crontab on QNAP. The QNAP cron daemon
# runs jobs as root with a near-empty PATH, so this script is paranoid about
# absolute paths and explicit env.
#
# Run manually:
#   /share/Container/freewise/kindle/kindle_cron.sh
#
# Notification config (optional, env or sourced from $APP_ROOT/.env.kindle):
#   KINDLE_NOTIFY_URL   Webhook URL (Slack-compatible). Empty → notify disabled.
#   KINDLE_NOTIFY_ON    failure (default) | always | never
#
# Exit codes:
#   0  scrape succeeded
#   3  storage_state.json missing (re-login needed)
#   4  scrape failed (auth expired, network, DOM change …)
set -eu

APP_ROOT="${APP_ROOT:-/share/Container/freewise/kindle}"
ENV_FILE="${ENV_FILE:-${APP_ROOT}/.env.kindle}"
LOG_FILE="${LOG_FILE:-${APP_ROOT}/scrape.log}"
NOTIFY="${APP_ROOT}/kindle_notify.sh"

# QNAP cron has a sparse PATH and HOME. Restore what kindle_dl.sh expects.
export PATH=/share/CACHEDEV1_DATA/.qpkg/container-station/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export HOME="${HOME:-/root}"
export DOCKER_CONFIG="${DOCKER_CONFIG:-${HOME}/.docker}"
mkdir -p "${DOCKER_CONFIG}"

# Load notify config from .env.kindle if present (Source-style: NAME=value lines).
if [ -f "${ENV_FILE}" ]; then
  for var in KINDLE_NOTIFY_URL KINDLE_NOTIFY_ON KINDLE_NOTIFY_HOST KINDLE_COOKIE_WARN_DAYS KINDLE_COOKIE_ERROR_DAYS KINDLE_COOKIE_FILTER_NAMES; do
    val=$(awk -F= -v k="${var}" '$1==k {sub(/^[^=]*=/,""); print; exit}' "${ENV_FILE}")
    if [ -n "${val}" ]; then
      export "${var}=${val}"
    fi
  done
fi

OUT_DIR=$(awk -F= '/^KINDLE_OUTPUT_DIR=/{print $2}' "${ENV_FILE}" 2>/dev/null | tail -n1)
OUT_DIR="${OUT_DIR:-/share/Container/freewise/imports/kindle}"

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT_NAME="kindle_highlights_${STAMP}.json"

START_TS=$(date '+%Y-%m-%d %H:%M:%S %Z')
echo "[${START_TS}] kindle scrape starting (output=${OUT_NAME})" >>"${LOG_FILE}"

# Pre-flight: warn (but don't abort) if storage_state is aging or stale, so
# the user gets actionable notice BEFORE Amazon redirects to /ap/signin.
#
# We run TWO checks and take the more pessimistic verdict:
#   1. mtime-based (kindle_check_state.sh) — catches "old file even if cookies
#      look ok" (e.g. file was never refreshed but contains long-lived cookies
#      that may already be invalidated server-side).
#   2. cookie-expiry based (kindle_check_state_cookies.sh) — catches "freshly
#      touched file but actually dead" (e.g. someone re-saved the same dead
#      session, or Amazon shortened the at-main TTL).
#
# Either one returning rc>=2 escalates to a notification. Scrape ALWAYS runs:
# Amazon may extend the session opportunistically and we'd rather try and fail
# than skip a window.
STATE_PATH=$(awk -F= '/^KINDLE_STATE_DIR=/{print $2}' "${ENV_FILE}" 2>/dev/null | tail -n1)
STATE_PATH="${STATE_PATH:-/share/Container/freewise/state/kindle}"
STATE_FILE="${STATE_PATH}/storage_state.json"

worst_rc=0
worst_status=""
worst_msg=""

merge_check() {
  # $1 = label, $2 = rc, $3 = full <status>\t<n>\t<message> line
  _label="$1"
  _rc="$2"
  _line="$3"
  _status=$(printf '%s' "${_line}" | awk -F'\t' '{print $1}')
  _msg=$(printf '%s' "${_line}"    | awk -F'\t' '{print $3}')
  echo "[${START_TS}] state check (${_label}): ${_line}" >>"${LOG_FILE}"
  if [ "${_rc}" -gt "${worst_rc}" ]; then
    worst_rc="${_rc}"
    worst_status="${_label}_${_status}"
    worst_msg="${_msg}"
  fi
}

STATE_CHECK="${APP_ROOT}/kindle_check_state.sh"
if [ -x "${STATE_CHECK}" ]; then
  set +e
  STATE_LINE=$("${STATE_CHECK}" 14 28 "${STATE_FILE}")
  rc=$?
  set -e
  merge_check "mtime" "${rc}" "${STATE_LINE}"
fi

COOKIE_CHECK="${APP_ROOT}/kindle_check_state_cookies.sh"
if [ -x "${COOKIE_CHECK}" ]; then
  WARN_D="${KINDLE_COOKIE_WARN_DAYS:-7}"
  ERR_D="${KINDLE_COOKIE_ERROR_DAYS:-3}"
  set +e
  COOKIE_LINE=$("${COOKIE_CHECK}" "${WARN_D}" "${ERR_D}" "${STATE_FILE}")
  rc=$?
  set -e
  merge_check "cookies" "${rc}" "${COOKIE_LINE}"
fi

# rc=2 (aging) or rc=3 (stale/expired) → warn now; scrape continues.
case "${worst_rc}" in
  2|3)
    if [ -x "${NOTIFY}" ]; then
      "${NOTIFY}" failure "state_${worst_status}: ${worst_msg}" "${worst_rc}" || true
    fi
    ;;
esac

set +e
"${APP_ROOT}/kindle_dl.sh" "${OUT_NAME}" >>"${LOG_FILE}" 2>&1
rc=$?
set -e

END_TS=$(date '+%Y-%m-%d %H:%M:%S %Z')
if [ "${rc}" -eq 0 ] && [ -s "${OUT_DIR}/${OUT_NAME}" ]; then
  ln -sfn "${OUT_DIR}/${OUT_NAME}" "${OUT_DIR}/kindle_highlights_latest.json"
  rm -f "${APP_ROOT}/last_failure.txt"
  BYTES=$(stat -c %s "${OUT_DIR}/${OUT_NAME}")
  # Pull book/highlight count from the scraper's final log line.
  SUMMARY=$(grep -E "Wrote [0-9]+ books / [0-9]+ total highlights" "${LOG_FILE}" | tail -1 \
            | sed -E 's/.*Wrote ([0-9]+) books \/ ([0-9]+) total highlights.*/\1 books, \2 highlights/' )
  [ -z "${SUMMARY}" ] && SUMMARY="${BYTES} bytes"
  echo "[${END_TS}] kindle scrape OK (${BYTES} bytes)" >>"${LOG_FILE}"
  # Trim log to last 1000 lines to avoid unbounded growth.
  tail -n 1000 "${LOG_FILE}" >"${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "${LOG_FILE}"
  if [ -x "${NOTIFY}" ]; then
    "${NOTIFY}" success "${SUMMARY}" 0 || true
  fi
  exit 0
fi

# Failure path. Classify the reason from the log tail via the standalone
# helper so the same logic can be unit-tested against synthetic inputs.
CLASSIFY="${APP_ROOT}/kindle_classify_failure.sh"
if [ -x "${CLASSIFY}" ]; then
  CLASS_LINE=$(tail -n 50 "${LOG_FILE}" 2>/dev/null | "${CLASSIFY}" "${rc}")
  REASON=$(printf '%s' "${CLASS_LINE}" | awk -F'\t' '{print $1}')
  HINT=$(printf '%s' "${CLASS_LINE}"   | awk -F'\t' '{print $2}')
else
  REASON="unknown"
  HINT="See ${LOG_FILE}."
fi

echo "[${END_TS}] kindle scrape FAILED rc=${rc} reason=${REASON}" >>"${LOG_FILE}"
{
  echo "Last kindle scrape failed."
  echo "  when:   ${END_TS}"
  echo "  rc:     ${rc}"
  echo "  reason: ${REASON}"
  echo "  hint:   ${HINT}"
  echo "  log:    ${LOG_FILE}"
} >"${APP_ROOT}/last_failure.txt"

if [ -x "${NOTIFY}" ]; then
  "${NOTIFY}" failure "${REASON}: ${HINT}" "${rc}" || true
fi

exit "${rc}"
