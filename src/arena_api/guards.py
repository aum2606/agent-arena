"""Checks on every state-changing request, before any route runs (D-070)."""

from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from arena_api.auth import public_url, public_url_is_local

MAX_BODY_BYTES = 64 * 1024  # the biggest real body (a persona of 2,000 characters) is a few KB
_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _origin_of(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _origin_allowed(origin: str) -> bool:
    """The app's own origin, or on a local address any local one (`npm run dev` is on :3000)."""
    if origin == _origin_of(public_url()):
        return True
    return public_url_is_local() and urlparse(origin).hostname in _LOOPBACK


def _refuse(status: int, detail: str) -> Response:
    return JSONResponse({"detail": detail}, status_code=status)


def add_guards(app: FastAPI) -> None:
    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method in _UNSAFE:
            # A browser says where a write comes from; a script or curl says nothing and is let
            # through (SameSite=Lax already keeps the session cookie off cross-site writes, D-033).
            site = request.headers.get("sec-fetch-site")
            origin = request.headers.get("origin")
            if site not in (None, "same-origin", "none") or (
                origin is not None and not _origin_allowed(origin)
            ):
                return _refuse(403, "cross-site requests are not allowed")
            length = request.headers.get("content-length")
            if length is None and request.headers.get("transfer-encoding"):
                return _refuse(411, "send a Content-Length")
            if length is not None and (not length.isdigit() or int(length) > MAX_BODY_BYTES):
                return _refuse(413, "the request is too large")
        return await call_next(request)
