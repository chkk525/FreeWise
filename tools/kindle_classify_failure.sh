#!/bin/sh
# Classify a Kindle scrape failure based on rc + log tail.
#
# Usage:
#   echo "<log tail>" | ./kindle_classify_failure.sh <rc>
#
# Output (one line):
#   <reason>\t<hint>
#
# Reasons:
#   state_missing      rc=3
#   auth_expired       sign-in / signed-out pattern
#   dom_change         "no such element", "selector not found", or "annotations rows: 0"
#   network            "name resolution", "connection refused", "timeout"
#   scrape_failed      rc=4 with no recognised pattern
#   unexpected_rc_<N>  any other rc
#
# Designed to be sourced or piped — no side effects.
set -eu

RC="${1:-0}"
TAIL=$(cat 2>/dev/null || true)

case "${RC}" in
  0)
    printf 'success\t-\n'
    ;;
  3)
    printf 'state_missing\tstorage_state.json missing — run kindle_login.sh on a desktop and scp the file to QNAP.\n'
    ;;
  4)
    if printf '%s' "${TAIL}" | grep -qiE "ap/signin|sign-?in|/ap/cvf|signed out|please sign"; then
      printf 'auth_expired\tAmazon redirected to sign-in; storage_state has expired. Re-run kindle_login.sh.\n'
    elif printf '%s' "${TAIL}" | grep -qiE "no such (table|element)|selector .*not found|annotations rows: 0"; then
      printf 'dom_change\tSelectors did not match. Amazon may have changed kp/notebook DOM.\n'
    elif printf '%s' "${TAIL}" | grep -qiE "name resolution|temporary failure|connection refused|timeout|net::"; then
      printf 'network\tNetwork/DNS error. Confirm QNAP cloudflared / DNS config.\n'
    else
      printf 'scrape_failed\tSee the scrape log (last 50 lines).\n'
    fi
    ;;
  *)
    printf 'unexpected_rc_%s\tSee the scrape log.\n' "${RC}"
    ;;
esac
