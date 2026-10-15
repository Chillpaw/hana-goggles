"""Request checks for a loopback-only app that still runs in a browser next to other sites.

- Host header: only 127.0.0.1 / localhost (TrustedHostMiddleware), so a DNS-rebinding
  page cannot talk to the app under its own host name.
- Unsafe methods (anything but GET/HEAD/OPTIONS) must come from this app's own pages:
  `Sec-Fetch-Site` absent or same-origin/none, and `Origin`, when sent, equal to
  `http://<Host>`. Otherwise 403. Their body must be a plain urlencoded form, else 415
  (a cross-site page cannot send that content type without the checks above seeing it).
- Every response, refusals included, carries `X-Content-Type-Options: nosniff`, so a
  browser never reads a text download (such as a .mmd file) as HTML or script.
"""
from __future__ import annotations

from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
SAME_SITE_VALUES = frozenset({"same-origin", "none"})
FORM_TYPE = "application/x-www-form-urlencoded"


class SameOriginMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        site = headers.get("sec-fetch-site")
        origin = headers.get("origin")
        host = headers.get("host", "")
        if (site is not None and site.lower() not in SAME_SITE_VALUES) or (
                origin is not None and origin != f"http://{host}"):
            response = PlainTextResponse("Refused: this request did not come from this app.",
                                         status_code=403)
        elif headers.get("content-type", "").split(";")[0].strip().lower() != FORM_TYPE:
            response = PlainTextResponse(f"Refused: only {FORM_TYPE} bodies are accepted.",
                                         status_code=415)
        else:
            await self.app(scope, receive, send)
            return
        await response(scope, receive, send)


class NoSniffMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
            await send(message)

        await self.app(scope, receive, send_with_header)


def add_security_middleware(app) -> None:
    """Order matters: the last added runs first. The host check runs before the origin
    check; the nosniff header wraps both, so their refusals carry it too."""
    app.add_middleware(SameOriginMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
    app.add_middleware(NoSniffMiddleware)
