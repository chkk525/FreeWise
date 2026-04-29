"""Decompress Content-Encoding: gzip request bodies.

Starlette's built-in GZipMiddleware compresses *responses* but does not
decompress *requests*. This middleware fills the gap so browser-extension
clients can shrink large Kindle import payloads.
"""
from __future__ import annotations

import gzip

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class GzipRequestMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.headers.get("content-encoding", "").lower() != "gzip":
            return await call_next(request)

        try:
            body = await request.body()
            decompressed = gzip.decompress(body)
        except (OSError, gzip.BadGzipFile, EOFError) as exc:
            return JSONResponse(
                {"detail": f"Invalid gzip body: {exc}"},
                status_code=400,
            )

        request._body = decompressed

        new_headers = [
            (k, v) for k, v in request.scope["headers"]
            if k.lower() not in (b"content-encoding", b"content-length")
        ]
        new_headers.append((b"content-length", str(len(decompressed)).encode()))
        request.scope["headers"] = new_headers

        return await call_next(request)
