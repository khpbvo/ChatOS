"""HTTP file server integrated into the WebSocket server via process_request.

Routes:
  /ws          → return None (WebSocket upgrade)
  /files/*     → serve local files from home_dir (session-token gated)
  /*           → serve static UI from static_dir (if configured)
  otherwise    → 404

Security:
  - Session token validated via secrets.compare_digest (timing-safe)
  - Path traversal blocked via Path.resolve() + relative_to()
  - Symlink escape blocked (resolve follows symlinks before checking)
  - Max file size enforced (HTTP 413)
  - Security headers on all responses
"""

from __future__ import annotations

import asyncio
import mimetypes
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from websockets.asyncio.server import ServerConnection
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

# 100 MB
MAX_FILE_SIZE = 100 * 1024 * 1024

# Extra MIME types that may be missing from system mimetypes db
_EXTRA_MIME: dict[str, str] = {
    ".webp": "image/webp",
    ".ogg": "audio/ogg",
    ".woff2": "font/woff2",
    ".webm": "video/webm",
    ".avif": "image/avif",
}


def _guess_mime(path: Path) -> str:
    """Guess MIME type with fallbacks for common extensions."""
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime
    return _EXTRA_MIME.get(path.suffix.lower(), "application/octet-stream")


def _security_headers() -> Headers:
    """Base security headers for all responses."""
    headers = Headers()
    headers["X-Content-Type-Options"] = "nosniff"
    headers["Cache-Control"] = "no-store"
    return headers


def _file_response(status: int, reason: str, body: bytes, content_type: str) -> Response:
    """Build an HTTP response with security headers."""
    headers = _security_headers()
    headers["Content-Type"] = content_type
    headers["Content-Length"] = str(len(body))
    headers["Content-Security-Policy"] = "default-src 'none'"
    return Response(status, reason, headers, body)


def _error_response(status: int, reason: str) -> Response:
    """Build a plain-text error response."""
    body = f"{status} {reason}\n".encode()
    return _file_response(status, reason, body, "text/plain; charset=utf-8")


def _static_response(body: bytes, content_type: str) -> Response:
    """Build a response for static UI files (permissive CSP)."""
    headers = _security_headers()
    headers["Content-Type"] = content_type
    headers["Content-Length"] = str(len(body))
    headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "connect-src 'self' ws: wss:; img-src 'self' data: blob:"
    )
    return Response(200, "OK", headers, body)


class FileServer:
    """HTTP request handler for local files and static UI assets.

    Designed to be used as the ``process_request`` callback of
    ``websockets.asyncio.server.serve()``.
    """

    def __init__(
        self,
        home_dir: Path | None = None,
        session_token: str = "",
        static_dir: Path | None = None,
    ) -> None:
        self._home_dir = home_dir.resolve() if home_dir else None
        self._session_token = session_token
        self._static_dir = static_dir.resolve() if static_dir else None

    async def handle_request(
        self,
        _connection: ServerConnection,
        request: Request,
    ) -> Response | None:
        """Route incoming HTTP requests.

        Returns ``None`` for ``/ws`` so the WebSocket handshake proceeds.
        Returns a ``Response`` for file/static requests or errors.
        """
        parsed = urlparse(request.path)
        path = parsed.path

        # WebSocket upgrade
        if path == "/ws":
            return None

        # Local file serving
        if path.startswith("/files/"):
            return await self._serve_file(parsed.path, parsed.query)

        # Static UI serving
        if self._static_dir is not None:
            return await self._serve_static(path)

        return _error_response(404, "Not Found")

    async def _serve_file(self, path: str, query: str) -> Response:
        """Serve a local file from home_dir with token validation."""
        if self._home_dir is None:
            return _error_response(404, "Not Found")

        # Validate session token
        params = parse_qs(query)
        token_values = params.get("token", [])
        if not token_values or not token_values[0]:
            return _error_response(403, "Forbidden")
        if not secrets.compare_digest(token_values[0], self._session_token):
            return _error_response(403, "Forbidden")

        # Extract relative path after /files/
        rel = path[len("/files/"):]
        if not rel:
            return _error_response(400, "Bad Request")

        # Resolve and validate path
        try:
            resolved = (self._home_dir / rel).resolve()
        except (ValueError, OSError):
            return _error_response(403, "Forbidden")

        # Ensure the resolved path is under home_dir
        try:
            resolved.relative_to(self._home_dir)
        except ValueError:
            return _error_response(403, "Forbidden")

        # Must be a regular file
        if not resolved.is_file():
            if resolved.is_dir():
                return _error_response(403, "Forbidden")
            return _error_response(404, "Not Found")

        # Check file size
        try:
            size = resolved.stat().st_size
        except OSError:
            return _error_response(404, "Not Found")
        if size > MAX_FILE_SIZE:
            return _error_response(413, "Payload Too Large")

        # Read file in a thread to avoid blocking the event loop
        try:
            body = await asyncio.to_thread(resolved.read_bytes)
        except OSError:
            return _error_response(500, "Internal Server Error")

        content_type = _guess_mime(resolved)
        return _file_response(200, "OK", body, content_type)

    async def _serve_static(self, path: str) -> Response:
        """Serve static UI files from static_dir with SPA fallback."""
        assert self._static_dir is not None

        # Normalize: / → /index.html
        if path == "/":
            path = "/index.html"

        # Strip leading slash for relative path
        rel = path.lstrip("/")
        if not rel:
            rel = "index.html"

        # Resolve and validate
        try:
            resolved = (self._static_dir / rel).resolve()
        except (ValueError, OSError):
            return _error_response(403, "Forbidden")

        try:
            resolved.relative_to(self._static_dir)
        except ValueError:
            return _error_response(403, "Forbidden")

        # If file doesn't exist, SPA fallback to index.html
        if not resolved.is_file():
            index = self._static_dir / "index.html"
            if index.is_file():
                body = await asyncio.to_thread(index.read_bytes)
                return _static_response(body, "text/html; charset=utf-8")
            return _error_response(404, "Not Found")

        body = await asyncio.to_thread(resolved.read_bytes)
        content_type = _guess_mime(resolved)
        return _static_response(body, content_type)
