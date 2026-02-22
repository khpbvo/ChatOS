"""Tests for the ChatOS event stream models and SDK block mapping."""

from datetime import datetime

import pytest

from src.models import (
    Event,
    MediaEvent,
    TextEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolCollapseEvent,
    ToolOutputEvent,
)
from src.orchestrator import MAX_OUTPUT_LINES, _cap_output, _MEDIA_URL_RE


# -- Event model creation tests --


class TestEventModels:
    def test_thinking_event(self) -> None:
        e = ThinkingEvent(text="Processing...")
        assert e.type == "thinking"
        assert e.text == "Processing..."
        assert isinstance(e.timestamp, datetime)

    def test_tool_call_event(self) -> None:
        e = ToolCallEvent(tool_name="Bash", tool_input={"command": "ls"})
        assert e.type == "tool_call"
        assert e.tool_name == "Bash"
        assert e.tool_input == {"command": "ls"}

    def test_tool_output_event(self) -> None:
        e = ToolOutputEvent(tool_name="Bash", output="file1\nfile2", truncated=False)
        assert e.type == "tool_output"
        assert e.truncated is False

    def test_tool_output_event_truncated(self) -> None:
        e = ToolOutputEvent(tool_name="Bash", output="...", truncated=True)
        assert e.truncated is True

    def test_tool_collapse_event(self) -> None:
        e = ToolCollapseEvent(tool_name="Bash")
        assert e.type == "tool_collapse"
        assert e.tool_name == "Bash"

    def test_text_event(self) -> None:
        e = TextEvent(text="Hello, how can I help?")
        assert e.type == "text"
        assert e.text == "Hello, how can I help?"

    def test_media_event_image(self) -> None:
        e = MediaEvent(media_type="image", url="https://example.com/photo.jpg")
        assert e.type == "media"
        assert e.media_type == "image"

    def test_media_event_video(self) -> None:
        e = MediaEvent(media_type="video", url="https://example.com/vid.mp4", alt="My video")
        assert e.media_type == "video"
        assert e.alt == "My video"

    def test_media_event_link(self) -> None:
        e = MediaEvent(media_type="link", url="https://example.com/song.mp3")
        assert e.media_type == "link"


class TestEventSerialization:
    def test_event_json_round_trip(self) -> None:
        e = TextEvent(text="hello")
        data = e.model_dump()
        assert data["type"] == "text"
        assert data["text"] == "hello"
        assert "timestamp" in data

    def test_tool_call_json(self) -> None:
        e = ToolCallEvent(tool_name="Write", tool_input={"file_path": "/tmp/x"})
        data = e.model_dump()
        assert data["tool_name"] == "Write"
        assert data["tool_input"]["file_path"] == "/tmp/x"

    def test_media_event_json(self) -> None:
        e = MediaEvent(media_type="image", url="https://x.com/a.png", alt="pic")
        data = e.model_dump()
        assert data["media_type"] == "image"
        assert data["alt"] == "pic"

    def test_event_is_base_class(self) -> None:
        """All event types inherit from Event."""
        for cls in (ThinkingEvent, ToolCallEvent, ToolOutputEvent,
                    ToolCollapseEvent, TextEvent, MediaEvent):
            assert issubclass(cls, Event)


# -- Output capping tests --


class TestCapOutput:
    def test_short_output_not_capped(self) -> None:
        text = "line1\nline2\nline3"
        result, truncated = _cap_output(text)
        assert result == text
        assert truncated is False

    def test_exact_max_lines_not_capped(self) -> None:
        lines = [f"line{i}" for i in range(MAX_OUTPUT_LINES)]
        text = "\n".join(lines)
        result, truncated = _cap_output(text)
        assert result == text
        assert truncated is False

    def test_over_max_lines_capped(self) -> None:
        lines = [f"line{i}" for i in range(MAX_OUTPUT_LINES + 10)]
        text = "\n".join(lines)
        result, truncated = _cap_output(text)
        assert truncated is True
        assert result.count("\n") == MAX_OUTPUT_LINES - 1

    def test_empty_output(self) -> None:
        result, truncated = _cap_output("")
        assert result == ""
        assert truncated is False

    def test_single_line(self) -> None:
        result, truncated = _cap_output("hello")
        assert result == "hello"
        assert truncated is False

    def test_custom_max_lines(self) -> None:
        text = "a\nb\nc\nd\ne"
        result, truncated = _cap_output(text, max_lines=3)
        assert truncated is True
        assert result == "a\nb\nc"


# -- Media URL regex tests --


class TestMediaUrlRegex:
    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/photo.jpg",
            "https://cdn.site.com/image.png",
            "https://example.com/pic.jpeg",
            "https://example.com/image.gif",
            "https://example.com/photo.webp",
            "https://example.com/logo.svg",
        ],
    )
    def test_matches_image_urls(self, url: str) -> None:
        assert _MEDIA_URL_RE.search(url) is not None

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/video.mp4",
            "https://example.com/clip.webm",
            "https://example.com/movie.mov",
        ],
    )
    def test_matches_video_urls(self, url: str) -> None:
        assert _MEDIA_URL_RE.search(url) is not None

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/song.mp3",
            "https://example.com/audio.ogg",
            "https://example.com/sound.wav",
        ],
    )
    def test_matches_audio_urls(self, url: str) -> None:
        assert _MEDIA_URL_RE.search(url) is not None

    def test_no_match_for_html(self) -> None:
        assert _MEDIA_URL_RE.search("https://example.com/page.html") is None

    def test_no_match_for_plain_text(self) -> None:
        assert _MEDIA_URL_RE.search("no urls here") is None

    def test_embedded_url_in_text(self) -> None:
        text = "Here is a photo: https://cdn.example.com/cats.png for you"
        m = _MEDIA_URL_RE.search(text)
        assert m is not None
        assert m.group(1) == "https://cdn.example.com/cats.png"

    def test_case_insensitive(self) -> None:
        assert _MEDIA_URL_RE.search("https://example.com/photo.JPG") is not None
