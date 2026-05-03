"""Decompress Content-Encoding: gzip request bodies.

Starlette's built-in GZipMiddleware compresses *responses* but does not
decompress *requests*. This middleware fills the gap so browser-extension
clients can shrink large Kindle import payloads.

Defends against gzip-bomb DoS: a tiny compressed payload can decompress
to multiple gigabytes. Two ceilings:

* compressed body must fit in :data:`MAX_COMPRESSED_BYTES` (returns 413)
* decompressed body must fit in :data:`MAX_DECOMPRESSED_BYTES` (returns 413)

The decompressed cap is the meaningful one — without it, an attacker can
spend ~10 KB of upload bandwidth and OOM-kill the worker. The endpoint
sits outside Cloudflare Access, so unauthenticated callers reach this
code path and the cap MUST be enforced before any DB work runs.
"""
from __future__ import annotations

import gzip

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# 10 MB compressed → enough for a 30 MB Kindle export at typical 3:1
# ratio. A real export of 25k highlights gzipped is ~300 KB.
MAX_COMPRESSED_BYTES = 10 * 1024 * 1024

# 50 MB decompressed → covers a pathological notebook and still leaves
# the worker headroom to JSON-decode + import. Adjust upward only if
# real exports start to exceed this.
MAX_DECOMPRESSED_BYTES = 50 * 1024 * 1024


class GzipRequestMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.headers.get("content-encoding", "").lower() != "gzip":
            return await call_next(request)

        body = await request.body()
        if len(body) > MAX_COMPRESSED_BYTES:
            return JSONResponse(
                {
                    "detail": (
                        f"Compressed body exceeds {MAX_COMPRESSED_BYTES} byte limit "
                        f"(got {len(body)} bytes)."
                    )
                },
                status_code=413,
            )

        try:
            decompressed = gzip.decompress(body)
        except (OSError, gzip.BadGzipFile, EOFError) as exc:
            return JSONResponse(
                {"detail": f"Invalid gzip body: {exc}"},
                status_code=400,
            )

        if len(decompressed) > MAX_DECOMPRESSED_BYTES:
            return JSONResponse(
                {
                    "detail": (
                        f"Decompressed body exceeds {MAX_DECOMPRESSED_BYTES} "
                        f"byte limit (got {len(decompressed)} bytes)."
                    )
                },
                status_code=413,
            )

        request._body = decompressed

        new_headers = [
            (k, v)
            for k, v in request.scope["headers"]
            if k.lower() not in (b"content-encoding", b"content-length")
        ]
        new_headers.append((b"content-length", str(len(decompressed)).encode()))
        request.scope["headers"] = new_headers

        return await call_next(request)
