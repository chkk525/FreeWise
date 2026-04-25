"""Readwise-compatible v2 API package.

Mounted under ``/api/v2`` in :mod:`app.main`. The endpoint surface mirrors the
public Readwise wire format closely enough for existing clients to work
unchanged. See :mod:`app.api_v2.router` for the request/response shapes and
``docs`` (or the route docstrings) for the compatibility scope.
"""

from app.api_v2 import router  # noqa: F401  (re-export for convenience)
