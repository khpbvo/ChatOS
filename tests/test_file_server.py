"""Tests for the ChatOS HTTP file server."""

from pathlib import Path

import pytest

from websockets.datastructures import Headers
from websockets.http11 import Request

from src.file_server import FileServer, MAX_FILE_SIZE, _guess_mime
from src.orchestrator import _classify_media_ext


# -- Helpers --


def _make_request(path: str) -> Request:
    """Build a minimal Request object for testing."""
    return Request(path=path, headers=Headers())


TOKEN = "test-token-abc123"


# -- TestRouting --


class TestRouting:
    async def test_ws_path_returns_none(self) -> None:
        fs = FileServer()
        result = await fs.handle_request(None, _make_request("/ws"))
        assert result is None

    async def test_files_path_without_home_dir_returns_404(self) -> None:
        fs = FileServer()
        result = await fs.handle_request(None, _make_request("/files/test.jpg"))
        assert result is not None
        assert result.status_code == 404

    async def test_unknown_path_returns_404(self) -> None:
        fs = FileServer()
        result = await fs.handle_request(None, _make_request("/unknown"))
        assert result is not None
        assert result.status_code == 404

    async def test_root_with_static_dir_serves_index(self, tmp_path: Path) -> None:
        static = tmp_path / "static"
        static.mkdir()
        (static / "index.html").write_text("<html>Hello</html>")
        fs = FileServer(static_dir=static)
        result = await fs.handle_request(None, _make_request("/"))
        assert result is not None
        assert result.status_code == 200
        assert b"Hello" in result.body

    async def test_root_without_static_dir_returns_404(self) -> None:
        fs = FileServer()
        result = await fs.handle_request(None, _make_request("/"))
        assert result is not None
        assert result.status_code == 404

    async def test_files_path_routes_to_file_serving(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        (home / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        fs = FileServer(home_dir=home, session_token=TOKEN)
        result = await fs.handle_request(None, _make_request(f"/files/photo.jpg?token={TOKEN}"))
        assert result is not None
        assert result.status_code == 200


# -- TestTokenValidation --


class TestTokenValidation:
    @pytest.fixture
    def home_with_file(self, tmp_path: Path) -> Path:
        home = tmp_path / "home"
        home.mkdir()
        (home / "image.png").write_bytes(b"\x89PNG")
        return home

    async def test_missing_token_returns_403(self, home_with_file: Path) -> None:
        fs = FileServer(home_dir=home_with_file, session_token=TOKEN)
        result = await fs.handle_request(None, _make_request("/files/image.png"))
        assert result is not None
        assert result.status_code == 403

    async def test_empty_token_returns_403(self, home_with_file: Path) -> None:
        fs = FileServer(home_dir=home_with_file, session_token=TOKEN)
        result = await fs.handle_request(None, _make_request("/files/image.png?token="))
        assert result is not None
        assert result.status_code == 403

    async def test_wrong_token_returns_403(self, home_with_file: Path) -> None:
        fs = FileServer(home_dir=home_with_file, session_token=TOKEN)
        result = await fs.handle_request(None, _make_request("/files/image.png?token=wrong"))
        assert result is not None
        assert result.status_code == 403

    async def test_valid_token_returns_200(self, home_with_file: Path) -> None:
        fs = FileServer(home_dir=home_with_file, session_token=TOKEN)
        result = await fs.handle_request(
            None, _make_request(f"/files/image.png?token={TOKEN}")
        )
        assert result is not None
        assert result.status_code == 200


# -- TestPathValidation --


class TestPathValidation:
    @pytest.fixture
    def home_with_files(self, tmp_path: Path) -> Path:
        home = tmp_path / "home"
        home.mkdir()
        subdir = home / "photos"
        subdir.mkdir()
        (subdir / "cat.jpg").write_bytes(b"\xff\xd8")
        (home / "doc.txt").write_bytes(b"hello")
        return home

    async def test_traversal_rejected(self, home_with_files: Path) -> None:
        fs = FileServer(home_dir=home_with_files, session_token=TOKEN)
        result = await fs.handle_request(
            None, _make_request(f"/files/../../../etc/passwd?token={TOKEN}")
        )
        assert result is not None
        assert result.status_code == 403

    async def test_directory_rejected(self, home_with_files: Path) -> None:
        fs = FileServer(home_dir=home_with_files, session_token=TOKEN)
        result = await fs.handle_request(
            None, _make_request(f"/files/photos?token={TOKEN}")
        )
        assert result is not None
        assert result.status_code == 403

    async def test_nonexistent_returns_404(self, home_with_files: Path) -> None:
        fs = FileServer(home_dir=home_with_files, session_token=TOKEN)
        result = await fs.handle_request(
            None, _make_request(f"/files/nope.jpg?token={TOKEN}")
        )
        assert result is not None
        assert result.status_code == 404

    async def test_nested_path_serves(self, home_with_files: Path) -> None:
        fs = FileServer(home_dir=home_with_files, session_token=TOKEN)
        result = await fs.handle_request(
            None, _make_request(f"/files/photos/cat.jpg?token={TOKEN}")
        )
        assert result is not None
        assert result.status_code == 200
        assert result.body == b"\xff\xd8"

    async def test_empty_path_returns_400(self, home_with_files: Path) -> None:
        fs = FileServer(home_dir=home_with_files, session_token=TOKEN)
        result = await fs.handle_request(
            None, _make_request(f"/files/?token={TOKEN}")
        )
        assert result is not None
        assert result.status_code == 400

    async def test_symlink_escape_rejected(self, home_with_files: Path, tmp_path: Path) -> None:
        secret = tmp_path / "secret.txt"
        secret.write_text("top secret")
        link = home_with_files / "escape.txt"
        link.symlink_to(secret)
        fs = FileServer(home_dir=home_with_files, session_token=TOKEN)
        result = await fs.handle_request(
            None, _make_request(f"/files/escape.txt?token={TOKEN}")
        )
        assert result is not None
        assert result.status_code == 403


# -- TestFileSize --


class TestFileSize:
    async def test_oversized_file_returns_413(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        big_file = home / "big.bin"
        # Create a sparse file that reports as > MAX_FILE_SIZE
        with open(big_file, "wb") as f:
            f.seek(MAX_FILE_SIZE + 1)
            f.write(b"\x00")
        fs = FileServer(home_dir=home, session_token=TOKEN)
        result = await fs.handle_request(
            None, _make_request(f"/files/big.bin?token={TOKEN}")
        )
        assert result is not None
        assert result.status_code == 413


# -- TestMimeType --


class TestMimeType:
    def test_jpg(self) -> None:
        assert _guess_mime(Path("photo.jpg")) == "image/jpeg"

    def test_png(self) -> None:
        assert _guess_mime(Path("image.png")) == "image/png"

    def test_webp_fallback(self) -> None:
        # webp may not be in system mimetypes
        mime = _guess_mime(Path("photo.webp"))
        assert mime == "image/webp"

    def test_ogg_fallback(self) -> None:
        mime = _guess_mime(Path("sound.ogg"))
        assert "ogg" in mime or "audio" in mime

    def test_html(self) -> None:
        assert "html" in _guess_mime(Path("page.html"))

    def test_unknown_extension(self) -> None:
        assert _guess_mime(Path("file.xyz123")) == "application/octet-stream"

    def test_woff2_fallback(self) -> None:
        mime = _guess_mime(Path("font.woff2"))
        assert "woff2" in mime or "font" in mime


# -- TestSecurityHeaders --


class TestSecurityHeaders:
    async def test_file_response_has_nosniff(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        (home / "test.txt").write_bytes(b"hello")
        fs = FileServer(home_dir=home, session_token=TOKEN)
        result = await fs.handle_request(
            None, _make_request(f"/files/test.txt?token={TOKEN}")
        )
        assert result is not None
        assert result.headers["X-Content-Type-Options"] == "nosniff"

    async def test_file_response_has_csp(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        (home / "test.txt").write_bytes(b"hello")
        fs = FileServer(home_dir=home, session_token=TOKEN)
        result = await fs.handle_request(
            None, _make_request(f"/files/test.txt?token={TOKEN}")
        )
        assert result is not None
        assert "default-src 'none'" in result.headers["Content-Security-Policy"]

    async def test_file_response_has_cache_control(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        (home / "test.txt").write_bytes(b"hello")
        fs = FileServer(home_dir=home, session_token=TOKEN)
        result = await fs.handle_request(
            None, _make_request(f"/files/test.txt?token={TOKEN}")
        )
        assert result is not None
        assert result.headers["Cache-Control"] == "no-store"

    async def test_static_response_has_permissive_csp(self, tmp_path: Path) -> None:
        static = tmp_path / "static"
        static.mkdir()
        (static / "index.html").write_text("<html>Hi</html>")
        fs = FileServer(static_dir=static)
        result = await fs.handle_request(None, _make_request("/"))
        assert result is not None
        csp = result.headers["Content-Security-Policy"]
        assert "'self'" in csp
        assert "ws:" in csp

    async def test_error_response_has_nosniff(self) -> None:
        fs = FileServer()
        result = await fs.handle_request(None, _make_request("/nope"))
        assert result is not None
        assert result.headers["X-Content-Type-Options"] == "nosniff"


# -- TestStaticServing --


class TestStaticServing:
    @pytest.fixture
    def static_dir(self, tmp_path: Path) -> Path:
        static = tmp_path / "dist"
        static.mkdir()
        (static / "index.html").write_text("<!doctype html><html></html>")
        assets = static / "assets"
        assets.mkdir()
        (assets / "app.js").write_text("console.log('hi')")
        (assets / "style.css").write_text("body{}")
        return static

    async def test_root_serves_index(self, static_dir: Path) -> None:
        fs = FileServer(static_dir=static_dir)
        result = await fs.handle_request(None, _make_request("/"))
        assert result is not None
        assert result.status_code == 200
        assert b"<!doctype html>" in result.body

    async def test_asset_file_served(self, static_dir: Path) -> None:
        fs = FileServer(static_dir=static_dir)
        result = await fs.handle_request(None, _make_request("/assets/app.js"))
        assert result is not None
        assert result.status_code == 200
        assert b"console.log" in result.body

    async def test_css_served_with_correct_mime(self, static_dir: Path) -> None:
        fs = FileServer(static_dir=static_dir)
        result = await fs.handle_request(None, _make_request("/assets/style.css"))
        assert result is not None
        assert result.status_code == 200
        assert "css" in result.headers["Content-Type"]

    async def test_spa_fallback_for_unknown_path(self, static_dir: Path) -> None:
        fs = FileServer(static_dir=static_dir)
        result = await fs.handle_request(None, _make_request("/some/deep/route"))
        assert result is not None
        assert result.status_code == 200
        assert b"<!doctype html>" in result.body

    async def test_traversal_in_static_rejected(self, static_dir: Path) -> None:
        fs = FileServer(static_dir=static_dir)
        result = await fs.handle_request(None, _make_request("/../../../etc/passwd"))
        assert result is not None
        # Either 403 (traversal caught) or 200 (SPA fallback — path resolves under static)
        # In either case, must NOT serve /etc/passwd
        if result.status_code == 200:
            assert b"<!doctype html>" in result.body
        else:
            assert result.status_code == 403

    async def test_missing_index_returns_404(self, tmp_path: Path) -> None:
        empty_static = tmp_path / "empty"
        empty_static.mkdir()
        fs = FileServer(static_dir=empty_static)
        result = await fs.handle_request(None, _make_request("/"))
        assert result is not None
        assert result.status_code == 404


# -- TestClassifyMediaExt --


class TestClassifyMediaExt:
    def test_image_extensions(self) -> None:
        for ext in ("png", "jpg", "jpeg", "gif", "webp", "svg"):
            assert _classify_media_ext(ext) == "image"

    def test_video_extensions(self) -> None:
        for ext in ("mp4", "webm", "mov"):
            assert _classify_media_ext(ext) == "video"

    def test_audio_link_extensions(self) -> None:
        for ext in ("mp3", "ogg", "wav"):
            assert _classify_media_ext(ext) == "link"

    def test_case_insensitive(self) -> None:
        assert _classify_media_ext("PNG") == "image"
        assert _classify_media_ext("MP4") == "video"

    def test_unknown_defaults_to_image(self) -> None:
        assert _classify_media_ext("bmp") == "image"
