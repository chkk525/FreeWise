#!/bin/sh
# Pre-flight check on storage_state.json freshness.
#
# Usage:
#   kindle_check_state.sh [warn_days] [error_days] [state_path]
#
# Exits:
#   0  state file is fresh (age < warn_days)
#   1  state is missing (file does not exist)
#   2  state is older than warn_days (warn — still scrapeable, refresh soon)
#   3  state is older than error_days (error — likely to fail; refresh now)
#
# Prints one machine-readable line to stdout:
#   <status>\t<age_days>\t<message>
# where <status> is one of: ok | aging | stale | missing
#
# Designed to be called by kindle_cron.sh BEFORE the scrape starts so we can
# notify proactively rather than waiting for Amazon to redirect us to /ap/signin.
set -eu

WARN_DAYS="${1:-${KINDLE_STATE_WARN_DAYS:-14}}"
ERROR_DAYS="${2:-${KINDLE_STATE_ERROR_DAYS:-28}}"
STATE_PATH="${3:-${KINDLE_STATE_PATH:-/share/Container/freewise/state/kindle/storage_state.json}}"

if [ ! -s "${STATE_PATH}" ]; then
  printf 'missing\t-\tstorage_state.json missing or empty: %s\n' "${STATE_PATH}"
  exit 1
fi

NOW=$(date +%s)
# stat -c works on QNAP (busybox + GNU coreutils) and Linux. macOS BSD stat
# uses -f, so we try -c first and fall back.
MTIME=$(stat -c %Y "${STATE_PATH}" 2>/dev/null || stat -f %m "${STATE_PATH}" 2>/dev/null)
if [ -z "${MTIME}" ]; then
  printf 'unknown\t-\tcould not stat: %s\n' "${STATE_PATH}"
  exit 1
fi

AGE_S=$((NOW - MTIME))
AGE_D=$((AGE_S / 86400))

if [ "${AGE_D}" -ge "${ERROR_DAYS}" ]; then
  printf 'stale\t%d\tstorage_state.json is %d day(s) old (>= %d) — re-run kindle_login.sh.\n' \
    "${AGE_D}" "${AGE_D}" "${ERROR_DAYS}"
  exit 3
fi
if [ "${AGE_D}" -ge "${WARN_DAYS}" ]; then
  printf 'aging\t%d\tstorage_state.json is %d day(s) old (>= %d) — refresh soon.\n' \
    "${AGE_D}" "${AGE_D}" "${WARN_DAYS}"
  exit 2
fi
printf 'ok\t%d\tstorage_state.json is %d day(s) old.\n' "${AGE_D}" "${AGE_D}"
exit 0
