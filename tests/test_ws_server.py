"""Tests for the ChatOS WebSocket server."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime

import pytest
from pydantic import ValidationError
from websockets import connect
from websockets.exceptions import ConnectionClosed

from src.audit import AuditLogger
from src.models import (
    ClientMessage,
    ErrorEvent,
    Event,
    MediaEvent,
    ReadyEvent,
    TextEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolCollapseEvent,
    ToolOutputEvent,
)
from src.ws_server import ChatOSWebSocketServer


# -- Fake Orchestrator --


class FakeOrchestrator:
    """Test double that yields predetermined events without the SDK."""

    def __init__(
        self,
        events: list[Event] | None = None,
        start_error: Exception | None = None,
        query_error: Exception | None = None,
    ) -> None:
        self.events = events or [TextEvent(text="Hello!")]
        self.start_error = start_error
        self.query_error = query_error
        self.started = False
        self.stopped = False
        self.queries: list[str] = []
        self._client = None

    @property
    def client(self) -> object | None:
        return self._client

    async def start(self, prompt: str | None = None) -> None:
        if self.start_error:
            raise self.start_error
        self.started = True
        self._client = object()  # non-None sentinel

    async def stop(self) -> None:
        self.stopped = True
        self._client = None

    async def query_events(self, message: str) -> AsyncIterator[Event]:
        self.queries.append(message)
        if self.query_error:
            raise self.query_error
        for event in self.events:
            yield event

    def query(self, message: str) -> AsyncIterator[str]:
        raise NotImplementedError("Use query_events")


# -- Fixtures --


@pytest.fixture
async def ws_env(tmp_path):
    """Start a real server on ephemeral port with a FakeOrchestrator."""
    audit = AuditLogger(tmp_path / "logs")
    fake = FakeOrchestrator(events=[TextEvent(text="Hello!")])
    server = ChatOSWebSocketServer(fake, audit, port=0)
    task = asyncio.create_task(server.serve())
    await server._ready.wait()
    yield server, f"ws://127.0.0.1:{server.port}/ws", fake, audit
    await server.stop()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


@pytest.fixture
async def ws_env_factory(tmp_path):
    """Factory fixture to create servers with custom FakeOrchestrators."""
    servers = []

    async def _make(fake: FakeOrchestrator):
        audit = AuditLogger(tmp_path / "logs")
        server = ChatOSWebSocketServer(fake, audit, port=0)
        t = asyncio.create_task(server.serve())
        await server._ready.wait()
        servers.append((server, t))
        return server, f"ws://127.0.0.1:{server.port}/ws", fake, audit

    yield _make

    for server, t in servers:
        await server.stop()
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t


import contextlib


def _send_msg(text: str) -> str:
    """Build a valid client message JSON string."""
    return json.dumps({"type": "message", "text": text})


# -- TestServerLifecycle --


class TestServerLifecycle:
    async def test_server_binds_to_localhost(self, ws_env) -> None:
        server, url, _, _ = ws_env
        assert server.port > 0
        assert "127.0.0.1" in url

    async def test_ready_event_sent_on_connect(self, ws_env) -> None:
        _, url, _, _ = ws_env
        async with connect(url) as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            assert data["type"] == "ready"

    async def test_ready_event_includes_session_token(self, ws_env) -> None:
        _, url, _, _ = ws_env
        async with connect(url) as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            assert data["type"] == "ready"
            assert "session_token" in data
            assert isinstance(data["session_token"], str)
            assert len(data["session_token"]) > 0

    async def test_orchestrator_started_on_connect(self, ws_env) -> None:
        _, url, fake, _ = ws_env
        async with connect(url) as ws:
            await asyncio.wait_for(ws.recv(), timeout=2)  # ready
            assert fake.started

    async def test_orchestrator_stopped_on_disconnect(self, ws_env) -> None:
        _, url, fake, _ = ws_env
        async with connect(url) as ws:
            await asyncio.wait_for(ws.recv(), timeout=2)  # ready
        # After disconnect, give server a moment to clean up
        await asyncio.sleep(0.1)
        assert fake.stopped

    async def test_connect_logged_to_audit(self, ws_env, tmp_path) -> None:
        _, url, _, audit = ws_env
        async with connect(url) as ws:
            await asyncio.wait_for(ws.recv(), timeout=2)
        await asyncio.sleep(0.1)
        log_files = list(audit.log_dir.glob("audit-*.jsonl"))
        assert len(log_files) >= 1
        entries = [json.loads(line) for line in log_files[0].read_text().strip().splitlines()]
        outcomes = [e["outcome"] for e in entries]
        assert "connect" in outcomes

    async def test_disconnect_logged_to_audit(self, ws_env, tmp_path) -> None:
        _, url, _, audit = ws_env
        async with connect(url) as ws:
            await asyncio.wait_for(ws.recv(), timeout=2)
        await asyncio.sleep(0.1)
        log_files = list(audit.log_dir.glob("audit-*.jsonl"))
        assert len(log_files) >= 1
        entries = [json.loads(line) for line in log_files[0].read_text().strip().splitlines()]
        outcomes = [e["outcome"] for e in entries]
        assert "disconnect" in outcomes


# -- TestMessageProtocol --


class TestMessageProtocol:
    async def test_text_event_streams(self, ws_env) -> None:
        _, url, _, _ = ws_env
        async with connect(url) as ws:
            await ws.recv()  # ready
            await ws.send(_send_msg("hello"))
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            assert data["type"] == "text"
            assert data["text"] == "Hello!"

    async def test_thinking_event_streams(self, ws_env_factory) -> None:
        fake = FakeOrchestrator(events=[ThinkingEvent(text="Hmm...")])
        _, url, _, _ = await ws_env_factory(fake)
        async with connect(url) as ws:
            await ws.recv()  # ready
            await ws.send(_send_msg("think"))
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            assert data["type"] == "thinking"
            assert data["text"] == "Hmm..."

    async def test_tool_call_event_streams(self, ws_env_factory) -> None:
        fake = FakeOrchestrator(events=[
            ToolCallEvent(tool_name="Bash", tool_input={"command": "ls"}),
        ])
        _, url, _, _ = await ws_env_factory(fake)
        async with connect(url) as ws:
            await ws.recv()  # ready
            await ws.send(_send_msg("list"))
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            assert data["type"] == "tool_call"
            assert data["tool_name"] == "Bash"
            assert data["tool_input"] == {"command": "ls"}

    async def test_tool_output_event_streams(self, ws_env_factory) -> None:
        fake = FakeOrchestrator(events=[
            ToolOutputEvent(tool_name="Bash", output="file.txt", truncated=False),
        ])
        _, url, _, _ = await ws_env_factory(fake)
        async with connect(url) as ws:
            await ws.recv()  # ready
            await ws.send(_send_msg("output"))
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            assert data["type"] == "tool_output"
            assert data["output"] == "file.txt"
            assert data["truncated"] is False

    async def test_tool_collapse_event_streams(self, ws_env_factory) -> None:
        fake = FakeOrchestrator(events=[ToolCollapseEvent(tool_name="Bash")])
        _, url, _, _ = await ws_env_factory(fake)
        async with connect(url) as ws:
            await ws.recv()  # ready
            await ws.send(_send_msg("collapse"))
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            assert data["type"] == "tool_collapse"
            assert data["tool_name"] == "Bash"

    async def test_media_event_streams(self, ws_env_factory) -> None:
        fake = FakeOrchestrator(events=[
            MediaEvent(media_type="image", url="https://example.com/photo.png", alt="Photo"),
        ])
        _, url, _, _ = await ws_env_factory(fake)
        async with connect(url) as ws:
            await ws.recv()  # ready
            await ws.send(_send_msg("media"))
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            assert data["type"] == "media"
            assert data["media_type"] == "image"
            assert data["url"] == "https://example.com/photo.png"

    async def test_multiple_events_arrive_in_order(self, ws_env_factory) -> None:
        fake = FakeOrchestrator(events=[
            ThinkingEvent(text="Thinking..."),
            ToolCallEvent(tool_name="Bash", tool_input={"command": "uptime"}),
            ToolOutputEvent(tool_name="Bash", output="up 5 days", truncated=False),
            TextEvent(text="System has been up for 5 days."),
        ])
        _, url, _, _ = await ws_env_factory(fake)
        async with connect(url) as ws:
            await ws.recv()  # ready
            await ws.send(_send_msg("uptime"))
            types = []
            for _ in range(4):
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
                types.append(json.loads(raw)["type"])
            assert types == ["thinking", "tool_call", "tool_output", "text"]

    async def test_events_have_iso_timestamps(self, ws_env) -> None:
        _, url, _, _ = ws_env
        async with connect(url) as ws:
            raw = await ws.recv()  # ready
            data = json.loads(raw)
            # Should be a valid ISO 8601 timestamp
            ts = datetime.fromisoformat(data["timestamp"])
            assert isinstance(ts, datetime)

    async def test_multiple_sequential_queries(self, ws_env) -> None:
        _, url, fake, _ = ws_env
        async with connect(url) as ws:
            await ws.recv()  # ready

            # First query
            await ws.send(_send_msg("first"))
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            assert json.loads(raw)["type"] == "text"

            # Second query
            await ws.send(_send_msg("second"))
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            assert json.loads(raw)["type"] == "text"

            assert fake.queries == ["first", "second"]


# -- TestErrorHandling --


class TestErrorHandling:
    async def test_invalid_json_returns_error(self, ws_env) -> None:
        _, url, _, _ = ws_env
        async with connect(url) as ws:
            await ws.recv()  # ready
            await ws.send("not valid json {{{")
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            assert data["type"] == "error"
            assert data["code"] == "invalid_message"

    async def test_missing_type_field_returns_error(self, ws_env) -> None:
        _, url, _, _ = ws_env
        async with connect(url) as ws:
            await ws.recv()  # ready
            await ws.send(json.dumps({"text": "hello"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            assert data["type"] == "error"
            assert data["code"] == "invalid_message"

    async def test_wrong_type_field_returns_error(self, ws_env) -> None:
        _, url, _, _ = ws_env
        async with connect(url) as ws:
            await ws.recv()  # ready
            await ws.send(json.dumps({"type": "command", "text": "hello"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            assert data["type"] == "error"
            assert data["code"] == "invalid_message"

    async def test_empty_text_returns_error(self, ws_env) -> None:
        _, url, _, _ = ws_env
        async with connect(url) as ws:
            await ws.recv()  # ready
            await ws.send(json.dumps({"type": "message", "text": "   "}))
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            assert data["type"] == "error"
            assert data["code"] == "invalid_message"
            assert "Empty" in data["error"]

    async def test_error_does_not_close_connection(self, ws_env) -> None:
        _, url, _, _ = ws_env
        async with connect(url) as ws:
            await ws.recv()  # ready
            # Send invalid message
            await ws.send("bad json")
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            assert json.loads(raw)["type"] == "error"
            # Connection should still work — send valid message
            await ws.send(_send_msg("still works"))
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            assert json.loads(raw)["type"] == "text"

    async def test_orchestrator_start_failure(self, ws_env_factory) -> None:
        fake = FakeOrchestrator(start_error=RuntimeError("auth failed"))
        server, url, _, _ = await ws_env_factory(fake)
        async with connect(url) as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            assert data["type"] == "error"
            assert data["code"] == "auth_failed"
            assert "auth failed" in data["error"]

    async def test_orchestrator_start_failure_closes_connection(self, ws_env_factory) -> None:
        fake = FakeOrchestrator(start_error=RuntimeError("auth failed"))
        server, url, _, _ = await ws_env_factory(fake)
        async with connect(url) as ws:
            await ws.recv()  # error event
            # Server should close the connection
            with pytest.raises((ConnectionClosed, StopAsyncIteration)):
                await asyncio.wait_for(ws.recv(), timeout=2)

    async def test_query_exception_returns_sdk_error(self, ws_env_factory) -> None:
        fake = FakeOrchestrator(query_error=RuntimeError("SDK blew up"))
        _, url, _, _ = await ws_env_factory(fake)
        async with connect(url) as ws:
            await ws.recv()  # ready
            await ws.send(_send_msg("boom"))
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            assert data["type"] == "error"
            assert data["code"] == "sdk_error"

    async def test_query_error_keeps_connection_open(self, ws_env_factory) -> None:
        fake = FakeOrchestrator(query_error=RuntimeError("oops"))
        _, url, _, _ = await ws_env_factory(fake)
        async with connect(url) as ws:
            await ws.recv()  # ready
            await ws.send(_send_msg("fail"))
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            assert json.loads(raw)["code"] == "sdk_error"
            # Clear the error for next query
            fake.query_error = None
            await ws.send(_send_msg("retry"))
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            assert json.loads(raw)["type"] == "text"


# -- TestSingleConnectionGuard --


class TestSingleConnectionGuard:
    async def test_second_connection_rejected(self, ws_env) -> None:
        _, url, _, _ = ws_env
        async with connect(url) as ws1:
            await ws1.recv()  # ready
            # Try second connection
            async with connect(url) as ws2:
                raw = await asyncio.wait_for(ws2.recv(), timeout=2)
                data = json.loads(raw)
                assert data["type"] == "error"
                assert data["code"] == "busy"

    async def test_reconnect_after_first_disconnects(self, ws_env) -> None:
        server, url, _, _ = ws_env
        async with connect(url) as ws1:
            await ws1.recv()  # ready
        await asyncio.sleep(0.1)  # let cleanup run
        assert not server.is_connected
        # Now reconnect
        async with connect(url) as ws2:
            raw = await asyncio.wait_for(ws2.recv(), timeout=2)
            data = json.loads(raw)
            assert data["type"] == "ready"


# -- TestNewModels --


class TestNewModels:
    def test_client_message_valid(self) -> None:
        msg = ClientMessage(type="message", text="Hello")
        assert msg.type == "message"
        assert msg.text == "Hello"

    def test_client_message_missing_text(self) -> None:
        with pytest.raises(ValidationError):
            ClientMessage(type="message")

    def test_client_message_wrong_type(self) -> None:
        with pytest.raises(ValidationError):
            ClientMessage(type="command", text="Hello")

    def test_ready_event_serialization(self) -> None:
        event = ReadyEvent()
        data = event.model_dump(mode="json")
        assert data["type"] == "ready"
        assert "timestamp" in data

    def test_ready_event_with_session_token(self) -> None:
        event = ReadyEvent(session_token="abc123")
        data = event.model_dump(mode="json")
        assert data["session_token"] == "abc123"

    def test_ready_event_default_empty_token(self) -> None:
        event = ReadyEvent()
        assert event.session_token == ""

    def test_error_event_serialization(self) -> None:
        event = ErrorEvent(error="Something went wrong", code="sdk_error")
        data = event.model_dump(mode="json")
        assert data["type"] == "error"
        assert data["error"] == "Something went wrong"
        assert data["code"] == "sdk_error"
        assert "timestamp" in data
