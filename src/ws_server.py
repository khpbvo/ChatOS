"""WebSocket server bridging the kiosk browser to the ChatOS agent.

Accepts a single WebSocket connection at a time, receives JSON messages
from the browser client, streams structured events back, and enforces
the single-connection guard (AD-14).

Usage:
    python -m src --serve [--host HOST] [--port PORT] [--rules PATH] [--log-dir PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import secrets
import sys
from pathlib import Path

from pydantic import ValidationError
from websockets.asyncio.server import ServerConnection, serve

from .file_server import FileServer

from .agent_registry import AgentRegistry
from .audit import AuditLogger, DEFAULT_LOG_DIR
from .cli import (
    DEV_AGENTS_TOML,
    DEV_MCP_TOML,
    DEV_PROMPTS_DIR,
    resolve_rules_path,
)
from .mcp_config import McpConfigLoader
from .models import ClientMessage, ErrorEvent, Event, ReadyEvent
from .orchestrator import Orchestrator
from .rules_engine import RulesEngine

log = logging.getLogger(__name__)


class ChatOSWebSocketServer:
    """Single-connection WebSocket server for the ChatOS kiosk UI."""

    def __init__(
        self,
        orchestrator: Orchestrator,
        audit_logger: AuditLogger,
        host: str = "127.0.0.1",
        port: int = 8400,
        home_dir: Path | None = None,
        static_dir: Path | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._audit = audit_logger
        self._host = host
        self._port = port
        self._session_token = secrets.token_urlsafe(32)
        self._file_server = FileServer(home_dir, self._session_token, static_dir)
        self._server: object | None = None
        self._active_connection: ServerConnection | None = None
        self._ready = asyncio.Event()

    @property
    def port(self) -> int:
        """Actual bound port (useful when started with port=0)."""
        if self._server is not None:
            for sock in self._server.sockets:
                return sock.getsockname()[1]
        return self._port

    @property
    def is_connected(self) -> bool:
        """Whether a client is currently connected."""
        return self._active_connection is not None

    async def serve(self) -> None:
        """Start the server and block until stopped."""
        self._server = await serve(
            self._handler,
            self._host,
            self._port,
            process_request=self._file_server.handle_request,
        )
        self._ready.set()
        log.info("ChatOS WebSocket server listening on %s:%d", self._host, self.port)
        await self._server.wait_closed()

    async def stop(self) -> None:
        """Shut down the server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handler(self, websocket: ServerConnection) -> None:
        """Handle a single WebSocket connection lifecycle."""
        # Single-connection guard
        if self._active_connection is not None:
            error = ErrorEvent(error="Another client is already connected", code="busy")
            await websocket.send(json.dumps(error.model_dump(mode="json")))
            await websocket.close(4000, "busy")
            return

        self._active_connection = websocket
        await self._audit.log_outcome(
            tool_name="ws_server",
            tool_input={"event": "connect", "remote": str(websocket.remote_address)},
            outcome="connect",
        )

        try:
            await self._orchestrator.start()
        except Exception as exc:
            error = ErrorEvent(error=str(exc), code="auth_failed")
            await self._send_event(websocket, error)
            await websocket.close(4001, "auth_failed")
            return
        finally:
            # If start() fails, clear active connection so next client can try
            if self._orchestrator.client is None:
                self._active_connection = None

        try:
            await self._send_event(
                websocket, ReadyEvent(session_token=self._session_token)
            )

            async for raw in websocket:
                await self._process_message(websocket, raw)
        except Exception as exc:
            log.exception("Unexpected error in handler: %s", exc)
        finally:
            await self._orchestrator.stop()
            self._active_connection = None
            await self._audit.log_outcome(
                tool_name="ws_server",
                tool_input={"event": "disconnect"},
                outcome="disconnect",
            )

    async def _process_message(self, websocket: ServerConnection, raw: str | bytes) -> None:
        """Parse and handle a single client message."""
        # Parse JSON
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            await self._send_event(
                websocket, ErrorEvent(error="Invalid JSON", code="invalid_message")
            )
            return

        # Validate against ClientMessage schema
        try:
            msg = ClientMessage(**data)
        except (ValidationError, TypeError):
            await self._send_event(
                websocket, ErrorEvent(error="Invalid message format", code="invalid_message")
            )
            return

        # Check non-empty text
        if not msg.text.strip():
            await self._send_event(
                websocket, ErrorEvent(error="Empty message text", code="invalid_message")
            )
            return

        # Stream events for this query
        try:
            await self._stream_events(websocket, msg.text)
        except Exception as exc:
            log.exception("Error during query: %s", exc)
            await self._send_event(
                websocket, ErrorEvent(error=str(exc), code="sdk_error")
            )

    async def _stream_events(self, websocket: ServerConnection, text: str) -> None:
        """Send orchestrator events to the client."""
        async for event in self._orchestrator.query_events(text):
            await self._send_event(websocket, event)

    async def _send_event(self, websocket: ServerConnection, event: Event) -> None:
        """Serialize and send a single event."""
        data = event.model_dump(mode="json")
        await websocket.send(json.dumps(data))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ChatOS WebSocket server")
    parser.add_argument(
        "--host", type=str, default="127.0.0.1", help="Bind address (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=8400, help="Bind port (default: 8400)"
    )
    parser.add_argument(
        "--rules", type=str, default=None, help="Path to rules.toml"
    )
    parser.add_argument(
        "--log-dir", type=str, default=None, help="Audit log directory"
    )
    parser.add_argument(
        "--model", type=str, default="sonnet", help="Model name or ID (default: sonnet)"
    )
    parser.add_argument(
        "--cwd", type=str, default="/usr/local/share/chatos", help="Working directory for the agent"
    )
    parser.add_argument(
        "--home-dir", type=str, default=None,
        help="Home directory for local file serving via /files/"
    )
    parser.add_argument(
        "--static-dir", type=str, default=None,
        help="Static UI directory to serve (e.g. ui/dist)"
    )
    parser.add_argument(
        "--cli-path", type=str, default=None,
        help="Path to the claude CLI binary (for ClaudeAgentOptions.cli_path)"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    rules_path = resolve_rules_path(args.rules)
    print(f"Loading rules from: {rules_path}", file=sys.stderr)
    rules_engine = RulesEngine.from_file(rules_path)

    log_dir = Path(args.log_dir) if args.log_dir else DEFAULT_LOG_DIR
    audit_logger = AuditLogger(log_dir)
    print(f"Audit logs: {audit_logger.log_dir}", file=sys.stderr)

    agent_registry = None
    agents_toml = DEV_AGENTS_TOML
    if agents_toml.is_file():
        agent_registry = AgentRegistry.from_paths(agents_toml, DEV_PROMPTS_DIR)
        print(f"Loaded agents: {', '.join(agent_registry.agent_names())}", file=sys.stderr)

    mcp_config = McpConfigLoader.from_path(DEV_MCP_TOML)
    if mcp_config.has_email():
        print("Email MCP server configured", file=sys.stderr)

    home_dir = Path(args.home_dir) if args.home_dir else None
    static_dir = Path(args.static_dir) if args.static_dir else None

    orchestrator = Orchestrator(
        rules_engine=rules_engine,
        audit_logger=audit_logger,
        model=args.model,
        cwd=args.cwd,
        agent_registry=agent_registry,
        mcp_config=mcp_config,
        file_server_prefix="/files" if home_dir else None,
        cli_path=args.cli_path,
    )

    server = ChatOSWebSocketServer(
        orchestrator=orchestrator,
        audit_logger=audit_logger,
        host=args.host,
        port=args.port,
        home_dir=home_dir,
        static_dir=static_dir,
    )

    # Apply process sandbox (after all config loaded, before event loop)
    from .sandbox_profiles import build_server_sandbox
    sandbox = build_server_sandbox(
        log_dir=str(log_dir),
        home_dir=str(home_dir) if home_dir else None,
        static_dir=str(static_dir) if static_dir else None,
        app_dir=str(Path(__file__).resolve().parent.parent),
        cli_path=args.cli_path,
        service_home=str(Path.home()),
    )
    try:
        sandbox.apply()
        print("Sandbox applied: pledge + unveil active", file=sys.stderr)
    except Exception as exc:
        print(f"Warning: Sandbox not applied: {exc}", file=sys.stderr)

    print(f"Starting WebSocket server on {args.host}:{args.port}", file=sys.stderr)
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
