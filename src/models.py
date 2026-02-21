"""Pydantic models for ChatOS structured data."""

from enum import Enum
from typing import Any

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
