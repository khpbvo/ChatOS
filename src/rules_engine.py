"""Rules engine for ChatOS permission system.

Parses /etc/chatos/rules.toml and evaluates tool calls against
the defined permission tiers: safe (allow), confirm, forbidden (deny).
Uses a whitelist approach — unmatched operations are denied by default.
"""

import os
import tomllib
from pathlib import Path

from .models import Action, Decision, Permissions, Resources, RulesConfig, RulesMeta

DEFAULT_RULES_PATH = Path("/etc/chatos/rules.toml")


class RulesEngine:
    """Evaluates tool calls against the permission rules."""

    def __init__(self, config: RulesConfig) -> None:
        self._config = config

    @classmethod
    def from_file(cls, path: Path | str = DEFAULT_RULES_PATH) -> "RulesEngine":
        """Load rules from a TOML file."""
        path = Path(path)
        with open(path, "rb") as f:
            raw = tomllib.load(f)

        config = RulesConfig(
            meta=RulesMeta(**raw.get("meta", {})),
            permissions=Permissions(**raw.get("permissions", {})),
            resources=Resources(**raw.get("resources", {})),
        )
        return cls(config)

    @property
    def config(self) -> RulesConfig:
        return self._config

    def check_command(self, command: str) -> Decision:
        """Check a shell command against permission patterns.

        Evaluation order (per CLAUDE.md):
        1. Forbidden patterns (substring match) -> deny
        2. Safe patterns (prefix match) -> allow
        3. Confirm patterns (prefix match) -> confirm
        4. Default -> deny (whitelist approach)
        """
        cmd = command.strip()
        if not cmd:
            return Decision(
                action=Action.DENY,
                reason="Empty command",
            )

        # 1. Forbidden patterns — substring match anywhere in command
        for pattern in self._config.permissions.forbidden_patterns:
            if pattern in cmd:
                return Decision(
                    action=Action.DENY,
                    reason="Command matches forbidden pattern",
                    matched_pattern=pattern,
                )

        # 2. Safe patterns — prefix match
        for pattern in self._config.permissions.safe_patterns:
            if self._prefix_match(cmd, pattern):
                return Decision(
                    action=Action.ALLOW,
                    reason="Command matches safe pattern",
                    matched_pattern=pattern,
                )

        # 3. Confirm patterns — prefix match
        for pattern in self._config.permissions.confirm_patterns:
            if self._prefix_match(cmd, pattern):
                return Decision(
                    action=Action.CONFIRM,
                    reason="Command requires user confirmation",
                    matched_pattern=pattern,
                )

        # 4. Default deny
        return Decision(
            action=Action.DENY,
            reason="Command does not match any allowed pattern",
        )

    def check_write_path(self, path: str) -> Decision:
        """Check if a file path is allowed for writing."""
        normalized = os.path.normpath(path)

        for forbidden in self._config.permissions.forbidden_write_paths:
            forbidden_norm = os.path.normpath(forbidden)
            if normalized == forbidden_norm or normalized.startswith(forbidden_norm + "/"):
                return Decision(
                    action=Action.DENY,
                    reason="Path is forbidden for writing",
                    matched_pattern=forbidden,
                )

        return Decision(
            action=Action.ALLOW,
            reason="Path is not in the forbidden write list",
        )

    def check_tool_use(self, tool_name: str, tool_input: dict) -> Decision:
        """Main entry point for PreToolUse hook.

        Dispatches to the appropriate check based on tool type.
        """
        match tool_name:
            case "Bash":
                command = tool_input.get("command", "")
                return self.check_command(command)
            case "Write" | "Edit":
                file_path = tool_input.get("file_path", "")
                return self.check_write_path(file_path)
            case "Read" | "Glob" | "Grep":
                return Decision(
                    action=Action.ALLOW,
                    reason=f"{tool_name} is a read-only operation",
                )
            case _:
                return Decision(
                    action=Action.DENY,
                    reason=f"Unknown tool: {tool_name}",
                )

    @staticmethod
    def _prefix_match(command: str, pattern: str) -> bool:
        """Check if a command matches a pattern by prefix.

        Handles patterns with and without trailing spaces:
        - "cat " matches "cat /etc/hosts" (trailing space acts as word boundary)
        - "uptime" matches "uptime" and "uptime -a"
        """
        stripped = pattern.rstrip()
        if command == stripped:
            return True
        if pattern.endswith(" "):
            # Pattern has trailing space — use it as-is for prefix match
            return command.startswith(pattern)
        # Pattern has no trailing space — require a word boundary
        return command.startswith(stripped + " ")
