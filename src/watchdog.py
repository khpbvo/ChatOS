"""Behavioral watchdog for ChatOS.

Pure synchronous state machine that detects anomalous tool call patterns:
denial cascades, forbidden repeats, error storms, runaway loops, and
identical call loops.  No I/O — the orchestrator handles all logging.

AD-34: Pure synchronous state machine (no I/O, no async).
AD-35: Per-query blocking with user-message reset.
AD-36: Monotonic clock for sliding windows.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter, deque
from typing import Any

from .models import Action, AlertKind, WatchdogAlert, WatchdogStatus


def _input_key(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Deterministic hash of tool_name + tool_input for bounded memory.

    Returns a 16-hex-char SHA-256 prefix.  JSON keys are sorted so that
    key order does not affect the result.
    """
    raw = f"{tool_name}:{json.dumps(tool_input, sort_keys=True)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class Watchdog:
    """Application-level behavioral monitor.

    Tracks tool call patterns per session and per query, raising alerts
    and blocking the session when anomalous behaviour is detected.
    """

    def __init__(
        self,
        *,
        denial_cascade_count: int = 5,
        denial_cascade_window: float = 10.0,
        forbidden_repeat_limit: int = 3,
        error_rate_count: int = 5,
        error_rate_window: float = 30.0,
        runaway_tool_limit: int = 50,
        identical_call_limit: int = 5,
    ) -> None:
        # Thresholds
        self._denial_cascade_count = denial_cascade_count
        self._denial_cascade_window = denial_cascade_window
        self._forbidden_repeat_limit = forbidden_repeat_limit
        self._error_rate_count = error_rate_count
        self._error_rate_window = error_rate_window
        self._runaway_tool_limit = runaway_tool_limit
        self._identical_call_limit = identical_call_limit

        # Session-scoped state (survives query resets)
        self._denial_times: deque[float] = deque()
        self._forbidden_counts: Counter[str] = Counter()
        self._error_times: deque[float] = deque()

        # Query-scoped state (cleared by reset_query)
        self._query_tool_count: int = 0
        self._query_signatures: Counter[str] = Counter()
        self._blocked: bool = False

    @property
    def is_blocked(self) -> bool:
        """Whether the current query is blocked."""
        return self._blocked

    # -- Public API --

    def record_decision(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        decision: Action,
        session_id: str = "",
    ) -> WatchdogStatus:
        """Record a rules-engine decision and check for anomalies.

        Called after the rules engine evaluates a tool call.
        """
        alerts: list[WatchdogAlert] = []

        if self._blocked:
            return WatchdogStatus(blocked=True, alerts=[])

        # -- Per-query counters (allow + deny both count) --
        self._query_tool_count += 1
        key = _input_key(tool_name, tool_input)
        self._query_signatures[key] += 1

        # -- Denial cascade (session sliding window) --
        if decision == Action.DENY:
            now = time.monotonic()
            self._denial_times.append(now)
            self._prune_window(self._denial_times, self._denial_cascade_window, now)
            if len(self._denial_times) >= self._denial_cascade_count:
                alert = WatchdogAlert(
                    kind=AlertKind.DENIAL_CASCADE,
                    message=(
                        f"{len(self._denial_times)} denials in "
                        f"{self._denial_cascade_window}s"
                    ),
                    count=len(self._denial_times),
                    threshold=self._denial_cascade_count,
                )
                alerts.append(alert)
                self._blocked = True

        # -- Forbidden repeat (session cumulative) --
        if decision == Action.DENY:
            self._forbidden_counts[key] += 1
            if self._forbidden_counts[key] >= self._forbidden_repeat_limit:
                alert = WatchdogAlert(
                    kind=AlertKind.FORBIDDEN_REPEAT,
                    message=(
                        f"Same forbidden pattern hit "
                        f"{self._forbidden_counts[key]} times"
                    ),
                    count=self._forbidden_counts[key],
                    threshold=self._forbidden_repeat_limit,
                )
                alerts.append(alert)
                self._blocked = True

        # -- Runaway tool loop (per-query) --
        if self._query_tool_count >= self._runaway_tool_limit:
            alert = WatchdogAlert(
                kind=AlertKind.RUNAWAY_TOOL_LOOP,
                message=f"{self._query_tool_count} tool calls in single query",
                count=self._query_tool_count,
                threshold=self._runaway_tool_limit,
            )
            alerts.append(alert)
            self._blocked = True

        # -- Identical call loop (per-query) --
        if self._query_signatures[key] >= self._identical_call_limit:
            alert = WatchdogAlert(
                kind=AlertKind.IDENTICAL_CALL_LOOP,
                message=(
                    f"Identical tool call repeated "
                    f"{self._query_signatures[key]} times"
                ),
                count=self._query_signatures[key],
                threshold=self._identical_call_limit,
            )
            alerts.append(alert)
            self._blocked = True

        return WatchdogStatus(blocked=self._blocked, alerts=alerts)

    def record_outcome(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        outcome: str,
        session_id: str = "",
    ) -> WatchdogStatus:
        """Record a tool execution outcome and check for error storms.

        Called after tool execution completes.
        """
        alerts: list[WatchdogAlert] = []

        if outcome == "error":
            now = time.monotonic()
            self._error_times.append(now)
            self._prune_window(self._error_times, self._error_rate_window, now)
            if len(self._error_times) >= self._error_rate_count:
                alert = WatchdogAlert(
                    kind=AlertKind.HIGH_ERROR_RATE,
                    message=(
                        f"{len(self._error_times)} errors in "
                        f"{self._error_rate_window}s"
                    ),
                    count=len(self._error_times),
                    threshold=self._error_rate_count,
                )
                alerts.append(alert)
                self._blocked = True

        return WatchdogStatus(blocked=self._blocked, alerts=alerts)

    def reset_query(self) -> None:
        """Reset per-query state. Called at the start of each user message."""
        self._query_tool_count = 0
        self._query_signatures = Counter()
        self._blocked = False

    def reset_session(self) -> None:
        """Reset all state. Called when a new session starts."""
        self._denial_times.clear()
        self._forbidden_counts.clear()
        self._error_times.clear()
        self.reset_query()

    # -- Internal helpers --

    @staticmethod
    def _prune_window(timestamps: deque[float], window: float, now: float) -> None:
        """Remove timestamps older than `window` seconds from the left."""
        cutoff = now - window
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()
