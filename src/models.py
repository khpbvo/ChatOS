"""Pydantic models for ChatOS structured data."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Action(str, Enum):
    """Decision action returned by the rules engine."""

    ALLOW = "allow"
    DENY = "deny"
    CONFIRM = "confirm"


class Decision(BaseModel):
    """Result of a rules engine check."""

    action: Action
    reason: str
    matched_pattern: str | None = None


class RulesMeta(BaseModel):
    """Metadata section of rules.toml."""

    version: str
    hostname: str


class Permissions(BaseModel):
    """Permission patterns from rules.toml."""

    safe_patterns: list[str] = Field(default_factory=list)
    confirm_patterns: list[str] = Field(default_factory=list)
    forbidden_patterns: list[str] = Field(default_factory=list)
    forbidden_write_paths: list[str] = Field(default_factory=list)


class Resources(BaseModel):
    """Resource limits from rules.toml."""

    max_concurrent_ops: int = 5
    session_timeout_minutes: int = 30


class RulesConfig(BaseModel):
    """Top-level rules configuration parsed from rules.toml."""

    meta: RulesMeta
    permissions: Permissions = Field(default_factory=Permissions)
    resources: Resources = Field(default_factory=Resources)


class AuditEntry(BaseModel):
    """A single audit log entry."""

    timestamp: str
    session_id: str = ""
    tool_name: str
    tool_input: dict[str, Any] = Field(default_factory=dict)
    decision: Action
    reason: str
    matched_pattern: str | None = None
    outcome: str | None = None
    error: str | None = None


# -- Agent configuration models --


class AgentConfig(BaseModel):
    """Single agent definition from agents.toml."""

    name: str
    model: str = "sonnet"
    description: str = ""


class AgentsConfig(BaseModel):
    """All agents from agents.toml."""

    default_model: str = "sonnet"
    agents: dict[str, AgentConfig] = Field(default_factory=dict)


# -- Event stream models --


class Event(BaseModel):
    """Base event emitted by the orchestrator."""

    type: str
    timestamp: datetime = Field(default_factory=datetime.now)


class ThinkingEvent(Event):
    """Agent is thinking/processing."""

    type: Literal["thinking"] = "thinking"
    text: str


class ToolCallEvent(Event):
    """A tool is being called."""

    type: Literal["tool_call"] = "tool_call"
    tool_name: str
    tool_input: dict[str, Any]


class ToolOutputEvent(Event):
    """Tool output (capped at 25 lines)."""

    type: Literal["tool_output"] = "tool_output"
    tool_name: str
    output: str
    truncated: bool


class ToolCollapseEvent(Event):
    """Previous tool output should collapse in the UI."""

    type: Literal["tool_collapse"] = "tool_collapse"
    tool_name: str


class TextEvent(Event):
    """AI response text."""

    type: Literal["text"] = "text"
    text: str


class MediaEvent(Event):
    """Inline media content."""

    type: Literal["media"] = "media"
    media_type: Literal["image", "video", "link"]
    url: str
    alt: str = ""


class ClientMessage(BaseModel):
    """Incoming message from the browser client."""

    type: Literal["message"]
    text: str


class ReadyEvent(Event):
    """Sent on connection to signal the UI can start sending."""

    type: Literal["ready"] = "ready"
    session_token: str = ""


class ErrorEvent(Event):
    """Server-side error reported to the client."""

    type: Literal["error"] = "error"
    error: str
    code: str  # "auth_failed" | "sdk_error" | "invalid_message" | "busy"


# -- MCP configuration models --


class EmailMcpConfig(BaseModel):
    """Email MCP server credentials from mcp.toml."""

    imap_server: str
    imap_port: int = 993
    smtp_server: str
    smtp_port: int = 587
    username: str
    password: str  # Read from root-owned file, never logged


class McpConfig(BaseModel):
    """MCP server configuration from mcp.toml."""

    email: EmailMcpConfig | None = None


# -- Kiosk configuration models --


class ChromiumConfig(BaseModel):
    """Chromium browser settings from kiosk.conf."""

    extra_flags: str = ""
    user_data_dir: str = "/var/chatos/chromium"
    disable_gpu: bool = False


class KioskConfig(BaseModel):
    """Kiosk session settings from kiosk.conf."""

    url: str = "http://127.0.0.1:8400"
    display: str = "0"
    vt: str = "vt05"
    server_timeout: int = 30
    poll_interval: int = 1


class KioskLoggingConfig(BaseModel):
    """Kiosk logging settings from kiosk.conf."""

    log_file: str = "/var/chatos/logs/kiosk.log"


class FullKioskConfig(BaseModel):
    """Top-level kiosk configuration from kiosk.conf."""

    kiosk: KioskConfig = Field(default_factory=KioskConfig)
    chromium: ChromiumConfig = Field(default_factory=ChromiumConfig)
    logging: KioskLoggingConfig = Field(default_factory=KioskLoggingConfig)
