#!/bin/sh
# Run the Kindle scraper's `login` subcommand inside Docker so the user can
# sign in to Amazon (incl. 2FA) and capture a Playwright storage_state.json.
#
# IMPORTANT — headed login is awkward on a headless QNAP NAS (no display
# server, X forwarding over SSH is brittle, MFA codes inside a remote
# container is painful). The recommended flow is to run THIS SCRIPT on your
# local Mac/Linux box (where you already have Docker Desktop), then scp the
# resulting storage_state.json over to the QNAP. See docs/KINDLE_SETUP.md.
#
# Usage:
#   ./tools/kindle_login.sh
#
# Env:
#   APP_ROOT     (default ./, the repo root for local; on QNAP this is
#                 /share/Container/freewise/kindle)
#   COMPOSE      override the compose binary (default `docker compose`)
#   ENV_FILE     override the env file (default $APP_ROOT/.env.kindle)
#
# Exit codes:
#   0  storage_state.json was saved
#   2  prerequisites missing
#   4  login workflow failed (timeout, network, …)
set -eu

APP_ROOT="${APP_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
COMPOSE="${COMPOSE:-docker compose}"
ENV_FILE="${ENV_FILE:-${APP_ROOT}/.env.kindle}"

if [ ! -f "${APP_ROOT}/docker-compose.kindle.yml" ]; then
  echo "error: ${APP_ROOT}/docker-compose.kindle.yml not found" >&2
  exit 2
fi

if [ ! -f "${ENV_FILE}" ]; then
  if [ -f "${APP_ROOT}/.env.kindle.example" ]; then
    echo "note: ${ENV_FILE} not found — copying from .env.kindle.example"
    cp "${APP_ROOT}/.env.kindle.example" "${ENV_FILE}"
  else
    echo "error: ${ENV_FILE} not found and no example available" >&2
    exit 2
  fi
fi

# QNAP docker plugin path fix (matches tools/safaribooks_dl.sh / deploy_qnap.sh).
export PATH=/share/CACHEDEV1_DATA/.qpkg/container-station/bin:$PATH
export DOCKER_CONFIG="${DOCKER_CONFIG:-${HOME}/.docker}"
mkdir -p "${DOCKER_CONFIG}"

cd "${APP_ROOT}"

echo "==> launching headed Chromium for Amazon login (in container)"
echo "    sign in to https://read.amazon.com/kp/notebook in the window that opens."
echo "    storage_state.json will land in KINDLE_STATE_DIR on this host."

# Lesson #5 from SAFARIBOOKS_STATUS: never use `if ! cmd; then rc=$?` — the
# `!` flips the exit code so $? is meaningless. Capture rc first, then branch.
set +e
${COMPOSE} -f docker-compose.kindle.yml --env-file "${ENV_FILE}" \
  run --rm \
  kindle login --state /work/state/storage_state.json
rc=$?
set -e

if [ "${rc}" -ne 0 ]; then
  echo "error: kindle login exited with rc=${rc}" >&2
  exit 4
fi

echo "==> done. storage_state.json saved to KINDLE_STATE_DIR."
