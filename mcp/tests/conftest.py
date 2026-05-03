"""Test fixtures for the MCP server.

Strategy: each MCP tool is a thin wrapper around freewise_cli.client.Client.
We test the tools by injecting a Client wired to the in-process FastAPI app
(via Starlette TestClient), the same approach used by the CLI tests.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))            # for `app.*`
sys.path.insert(0, str(ROOT / "cli"))    # for `freewise_cli.*`
sys.path.insert(0, str(ROOT / "mcp"))    # for `freewise_mcp.*`
sys.path.insert(0, str(ROOT / "tests"))  # reuse main conftest

from conftest import _reset_db  # noqa: F401 — re-export for autouse
from conftest import _test_engine
from conftest import _override_get_session  # noqa: F401
from conftest import app

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models import ApiToken
from freewise_cli.client import Client


@pytest.fixture
def http_client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_token() -> str:
    return "fw_mcptestmcptestmcptestmcp12345"


@pytest.fixture(autouse=True)
def _seed_token(auth_token):
    with Session(_test_engine) as s:
        s.add(
            ApiToken(
                token_prefix=auth_token[:16],
                token_hash=hashlib.sha256(auth_token.encode()).hexdigest(),
                name="mcp-test",
                user_id=1,
            )
        )
        s.commit()
    yield


@pytest.fixture
def patched_client(http_client, auth_token, monkeypatch):
    """Replace freewise_mcp.server._client with one wired to the test app."""
    import freewise_mcp.server as server

    def factory():
        return Client(url="http://testserver", token=auth_token, http=http_client)

    monkeypatch.setattr(server, "_client", factory)
    yield factory
