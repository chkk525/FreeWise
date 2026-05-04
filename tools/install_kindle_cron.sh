#!/usr/bin/env bash
# Install the Kindle scrape cron entry on QNAP.
#
# QNAP's cron lives in /etc/config/crontab (NOT the user crontab — `crontab -e`
# rewrites a runtime file that gets clobbered on boot). To install a durable
# entry we must edit that file and reload crond. Both require sudo because
# `/etc/config/crontab` is admin-owned.
#
# Run this on a workstation; it ssh's into QNAP and asks for the sudo password
# interactively (one prompt).
#
# Run:
#   ./tools/install_kindle_cron.sh
#
# Env:
#   QNAP_HOST     (default qnap)
#   CRON_SCHEDULE (default '0 3 * * *' — 03:00 JST daily)
#   KINDLE_SH     (default /share/Container/freewise/kindle/kindle_cron.sh)
set -euo pipefail

QNAP_HOST="${QNAP_HOST:-qnap}"
CRON_SCHEDULE="${CRON_SCHEDULE:-0 3 * * *}"
KINDLE_SH="${KINDLE_SH:-/share/Container/freewise/kindle/kindle_cron.sh}"

LINE="${CRON_SCHEDULE} ${KINDLE_SH} >/dev/null 2>&1"
MARKER="# kindle scrape (managed by install_kindle_cron.sh)"

echo "Will append the following entry to QNAP's /etc/config/crontab:"
echo "  ${MARKER}"
echo "  ${LINE}"
echo
echo "Connecting to ${QNAP_HOST}; sudo will prompt for your password ONCE."

ssh -t "${QNAP_HOST}" "
  set -e
  CRON_FILE=/etc/config/crontab
  if sudo grep -qF '${KINDLE_SH}' \"\${CRON_FILE}\"; then
    echo 'kindle cron entry already present — leaving as is.'
  else
    sudo cp \"\${CRON_FILE}\" \"\${CRON_FILE}.bak.\$(date +%Y%m%d-%H%M%S)\"
    echo '${MARKER}'  | sudo tee -a \"\${CRON_FILE}\" >/dev/null
    echo '${LINE}'    | sudo tee -a \"\${CRON_FILE}\" >/dev/null
    echo 'appended kindle cron entry.'
  fi
  echo
  echo 'reloading cron…'
  sudo crontab /etc/config/crontab
  sudo /etc/init.d/crond.sh restart
  echo
  echo 'final crontab tail:'
  sudo tail -5 /etc/config/crontab
"
