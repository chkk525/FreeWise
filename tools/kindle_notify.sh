#!/bin/sh
# Send a webhook notification about a Kindle scrape outcome.
#
# Reads from env / args. Designed to be called by kindle_cron.sh, but
# usable standalone:
#   ./kindle_notify.sh success "scraped 49 books / 704 highlights"
#   ./kindle_notify.sh failure "scrape failed (auth expired)" 4
#
# Configuration (env):
#   KINDLE_NOTIFY_URL    Webhook to POST to. If empty/unset → no-op (exit 0).
#   KINDLE_NOTIFY_ON     "failure" (default) | "always" | "never"
#                        Controls whether success notifications are also sent.
#   KINDLE_NOTIFY_HOST   Override hostname in payload (default: $(hostname))
#
# Payload format (Slack-compatible):
#   {"text": "<emoji> Kindle scrape <status> on <host>: <message>"}
#
# Slack incoming webhooks accept this directly. ntfy.sh accepts JSON via the
# X-Title / Body convention (we send plain text + JSON; receivers pick what
# they understand). Custom HTTP receivers can parse the JSON body.
#
# Exit codes:
#   0  notification sent (or skipped because KINDLE_NOTIFY_URL is unset / mode
#      is "never" / mode is "failure" with success status)
#   1  curl/wget invocation failed (network, 5xx, etc.)
set -eu

STATUS="${1:-unknown}"      # success | failure
MESSAGE="${2:-}"
RC="${3:-}"

URL="${KINDLE_NOTIFY_URL:-}"
MODE="${KINDLE_NOTIFY_ON:-failure}"
HOST="${KINDLE_NOTIFY_HOST:-$(hostname 2>/dev/null || echo unknown)}"

if [ -z "${URL}" ]; then
  exit 0
fi
case "${MODE}" in
  never) exit 0 ;;
  failure) [ "${STATUS}" = "success" ] && exit 0 ;;
  always|*) ;;
esac

case "${STATUS}" in
  success) emoji=":white_check_mark:" ;;
  failure) emoji=":x:" ;;
  *)       emoji=":warning:" ;;
esac

rc_part=""
[ -n "${RC}" ] && rc_part=" (rc=${RC})"

text="${emoji} Kindle scrape ${STATUS} on ${HOST}${rc_part}: ${MESSAGE}"

# Build JSON safely. Messages may include newlines (from grep over the
# scrape log when classify_failure dumps a multi-line excerpt) and arbitrary
# Unicode; previously the manual sed escape only handled \\ and " and could
# produce invalid JSON for log content with embedded quotes/CRs.
#
# Prefer jq -Rs (raw input → JSON string) when available; fall back to a
# defensive pure-sh escape that handles \\ " and converts \r and \n to their
# JSON escape sequences.
escape() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$1" | jq -Rs .
    return 0
  fi
  # Fallback: \\, ", CR, LF — the four bytes most likely to wreck a JSON
  # round-trip from real-world log content.
  printf '%s' "$1" | awk '
    BEGIN { ORS="" }
    NR > 1 { printf "\\n" }
    {
      gsub(/\\/, "\\\\");
      gsub(/"/, "\\\"");
      gsub(/\r/, "\\r");
      print
    }
  ' | sed 's/^/"/; s/$/"/'
}
# escape() now returns the FULL JSON string including surrounding quotes,
# so we no longer wrap the call in another pair of "...".
text_json=$(escape "${text}")
status_json=$(escape "${STATUS}")
host_json=$(escape "${HOST}")
json="{\"text\":${text_json},\"status\":${status_json},\"host\":${host_json}"
[ -n "${RC}" ] && json="${json},\"rc\":${RC}"
json="${json}}"

if command -v curl >/dev/null 2>&1; then
  if curl -fsS -X POST -H 'Content-Type: application/json' \
       --data "${json}" --max-time 10 "${URL}" >/dev/null 2>&1; then
    exit 0
  fi
elif command -v wget >/dev/null 2>&1; then
  if wget -q --post-data="${json}" --header='Content-Type: application/json' \
       --timeout=10 -O /dev/null "${URL}"; then
    exit 0
  fi
fi
exit 1
