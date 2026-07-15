import hmac
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class CSRFMiddleware(BaseHTTPMiddleware):
    """Origin and double-submit protection for cookie-authenticated API writes."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method not in {
            "GET",
            "HEAD",
            "OPTIONS",
        }:
            settings = request.app.state.settings
            origin = request.headers.get("origin")
            allowed_origin = _origin(settings.FRONTEND_URL)
            if origin and _origin(origin) != allowed_origin:
                return JSONResponse({"detail": "Origin not allowed"}, status_code=403)

            if request.cookies.get(settings.SESSION_COOKIE_NAME):
                cookie_token = request.cookies.get("citepilot_csrf", "")
                header_token = request.headers.get("x-csrf-token", "")
                if not cookie_token or not hmac.compare_digest(cookie_token, header_token):
                    return JSONResponse({"detail": "CSRF validation failed"}, status_code=403)

        response = await call_next(request)
        if request.url.path.startswith("/api/auth/"):
            response.headers["Cache-Control"] = "no-store"
        return response


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme.lower()}://{(parsed.hostname or '').lower()}{port}"
