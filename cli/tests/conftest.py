"""Shared fixtures for CLI tests.

The CLI talks HTTP to the FreeWise server. We don't want to spin up a real
socket per test, so we wrap the FastAPI app in an httpx ASGITransport and
hand it to the CLI's Client. Tests assert behavior end-to-end:
CLI argv → Client → ASGI app → DB → response → CLI stdout.

The DB and app fixtures are reused from the main project conftest.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

# Make the main app + cli packages importable.
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))             # for `app.*`
sys.path.insert(0, str(ROOT / "cli"))     # for `freewise_cli.*`
sys.path.insert(0, str(ROOT / "tests"))   # reuse main conftest's fixtures

# Importing the project conftest runs its module-level setup (engine patch +
# fixture registration). After this import the fixtures live on the pytest
# default scope.
from conftest import _reset_db  # noqa: F401  — re-export for collection
from conftest import _test_engine  # noqa: F401
from conftest import _override_get_session  # noqa: F401
from conftest import app  # the FastAPI instance

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import ApiToken
from freewise_cli.client import Client


@pytest.fixture
def http_client():
    """Starlette TestClient that routes CLI requests into the FastAPI app."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_token() -> str:
    """Stable raw token that we'll seed into the test DB before each test."""
    return "fw_clitestclitestclitestcli12345"


@pytest.fixture(autouse=True)
def _seed_token(auth_token):
    """Insert an ApiToken row that maps to the raw token used by all CLI tests."""
    with Session(_test_engine) as s:
        s.add(
            ApiToken(
                token_prefix=auth_token[:16],
                token_hash=hashlib.sha256(auth_token.encode()).hexdigest(),
                name="cli-test",
                user_id=1,
            )
        )
        s.commit()
    yield


@pytest.fixture
def cli_client(http_client, auth_token) -> Client:
    """A CLI HTTP client wired to the in-process FastAPI app via TestClient."""
    return Client(url="http://testserver", token=auth_token, http=http_client)
