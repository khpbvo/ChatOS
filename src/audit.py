"""Audit logging for ChatOS.

Writes structured JSON Lines (one JSON object per line) to date-based
log files in the configured log directory. Every tool call — whether
allowed, denied, or requiring confirmation — is recorded.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import Action, AuditEntry, Decision, WatchdogAlert

DEFAULT_LOG_DIR = Path("/var/chatos/logs")


class AuditLogger:
    """Async audit logger writing JSONL to date-based files."""

    def __init__(self, log_dir: Path | str = DEFAULT_LOG_DIR) -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)

    @property
    def log_dir(self) -> Path:
        return self._log_dir

    def _log_path(self) -> Path:
        """Return today's log file path."""
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        return self._log_dir / f"audit-{date_str}.jsonl"

    async def log(self, entry: AuditEntry) -> None:
        """Write an audit entry to the current day's log file."""
        line = entry.model_dump_json() + "\n"
        await asyncio.to_thread(self._write_line, line)

    async def log_decision(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        decision: Decision,
        session_id: str = "",
    ) -> None:
        """Log a PreToolUse rules engine decision."""
        entry = AuditEntry(
            timestamp=datetime.now(UTC).isoformat(),
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            decision=decision.action,
            reason=decision.reason,
            matched_pattern=decision.matched_pattern,
        )
        await self.log(entry)

    async def log_outcome(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        outcome: str,
        session_id: str = "",
        error: str | None = None,
    ) -> None:
        """Log a PostToolUse outcome (success/failure/error)."""
        entry = AuditEntry(
            timestamp=datetime.now(UTC).isoformat(),
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            decision=Action.ALLOW,
            reason="PostToolUse outcome",
            outcome=outcome,
            error=error,
        )
        await self.log(entry)

    async def log_watchdog_alert(self, alert: WatchdogAlert, session_id: str = "") -> None:
        """Log a watchdog anomaly alert."""
        entry = AuditEntry(
            timestamp=datetime.now(UTC).isoformat(),
            session_id=session_id,
            tool_name="watchdog",
            tool_input={
                "kind": alert.kind.value,
                "count": alert.count,
                "threshold": alert.threshold,
            },
            decision=Action.DENY,
            reason=alert.message,
        )
        await self.log(entry)

    def _write_line(self, line: str) -> None:
        """Synchronous file append (called via asyncio.to_thread)."""
        with open(self._log_path(), "a") as f:
            f.write(line)
