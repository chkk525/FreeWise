#!/bin/sh
# Run the Kindle scraper's `scrape` subcommand inside Docker (headless).
# Output JSON lands in KINDLE_OUTPUT_DIR on the host.
#
# Usage (on QNAP, or via `ssh qnap ...`):
#   ./kindle_dl.sh                 # writes /work/output/kindle_highlights.json
#   ./kindle_dl.sh my_export.json  # custom output filename (still under KINDLE_OUTPUT_DIR)
#
# Env:
#   APP_ROOT   (default /share/Container/freewise/kindle)
#   COMPOSE    override the compose binary (default `docker compose`)
#   ENV_FILE   override the env file (default $APP_ROOT/.env.kindle)
#
# Exit codes:
#   0  scrape succeeded, JSON written
#   2  prerequisites missing
#   3  storage_state.json missing — run kindle_login.sh first
#   4  scrape failed (auth expired, network, DOM change …)
set -eu

APP_ROOT="${APP_ROOT:-/share/Container/freewise/kindle}"
COMPOSE="${COMPOSE:-docker compose}"
ENV_FILE="${ENV_FILE:-${APP_ROOT}/.env.kindle}"
OUT_NAME="${1:-kindle_highlights.json}"

# QNAP docker plugin path fix.
export PATH=/share/CACHEDEV1_DATA/.qpkg/container-station/bin:$PATH
export DOCKER_CONFIG="${DOCKER_CONFIG:-${HOME}/.docker}"
mkdir -p "${DOCKER_CONFIG}"

if [ ! -f "${APP_ROOT}/docker-compose.kindle.yml" ]; then
  echo "error: ${APP_ROOT}/docker-compose.kindle.yml not found" >&2
  exit 2
fi
if [ ! -f "${ENV_FILE}" ]; then
  echo "error: ${ENV_FILE} not found — see docs/KINDLE_SETUP.md" >&2
  exit 2
fi

# Resolve KINDLE_STATE_DIR / KINDLE_OUTPUT_DIR from the env file purely so we
# can perform a useful pre-flight check; we do NOT export them — compose reads
# the same env-file directly with --env-file.
STATE_DIR=$(awk -F= '/^KINDLE_STATE_DIR=/{print $2}' "${ENV_FILE}" | tail -n1)
STATE_DIR="${STATE_DIR:-/share/Container/freewise/state/kindle}"
OUT_DIR=$(awk -F= '/^KINDLE_OUTPUT_DIR=/{print $2}' "${ENV_FILE}" | tail -n1)
OUT_DIR="${OUT_DIR:-/share/Container/freewise/imports/kindle}"

if [ ! -s "${STATE_DIR}/storage_state.json" ]; then
  echo "error: ${STATE_DIR}/storage_state.json missing or empty" >&2
  echo "       run kindle_login.sh on a desktop and scp the file here." >&2
  echo "       See docs/KINDLE_SETUP.md for the full flow." >&2
  exit 3
fi

mkdir -p "${OUT_DIR}"
cd "${APP_ROOT}"

echo "==> scraping Kindle Notebook (headless)"

set +e
${COMPOSE} -f docker-compose.kindle.yml --env-file "${ENV_FILE}" \
  run --rm \
  kindle scrape \
    --state /work/state/storage_state.json \
    --output "/work/output/${OUT_NAME}"
rc=$?
set -e

if [ "${rc}" -ne 0 ]; then
  echo "error: kindle scrape exited rc=${rc}" >&2
  echo "       common causes: storage_state.json expired (re-login), Amazon" >&2
  echo "       changed the kp/notebook DOM, or Playwright timeout." >&2
  exit 4
fi

echo "==> done. output: ${OUT_DIR}/${OUT_NAME}"
