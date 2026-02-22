"""Tests for the ChatOS watchdog behavioral monitor."""

import time

import pytest

from src.models import Action, AlertKind, WatchdogAlert, WatchdogStatus
from src.watchdog import Watchdog, _input_key


# -- TestWatchdogModels --


class TestWatchdogModels:
    """AlertKind values, WatchdogAlert serialization, WatchdogStatus defaults."""

    def test_alert_kind_values(self) -> None:
        assert AlertKind.DENIAL_CASCADE == "denial_cascade"
        assert AlertKind.FORBIDDEN_REPEAT == "forbidden_repeat"
        assert AlertKind.HIGH_ERROR_RATE == "high_error_rate"
        assert AlertKind.RUNAWAY_TOOL_LOOP == "runaway_tool_loop"
        assert AlertKind.IDENTICAL_CALL_LOOP == "identical_call_loop"

    def test_watchdog_alert_serialization(self) -> None:
        alert = WatchdogAlert(
            kind=AlertKind.DENIAL_CASCADE,
            message="5 denials in 10s",
            count=5,
            threshold=5,
        )
        data = alert.model_dump()
        assert data["kind"] == "denial_cascade"
        assert data["message"] == "5 denials in 10s"
        assert data["count"] == 5
        assert data["threshold"] == 5

    def test_watchdog_status_defaults(self) -> None:
        status = WatchdogStatus()
        assert status.blocked is False
        assert status.alerts == []


# -- TestWatchdogDefaults --


class TestWatchdogDefaults:
    """Default thresholds, custom thresholds, initial state, return type."""

    def test_default_thresholds(self) -> None:
        wd = Watchdog()
        assert wd._denial_cascade_count == 5
        assert wd._denial_cascade_window == 10.0
        assert wd._forbidden_repeat_limit == 3
        assert wd._error_rate_count == 5
        assert wd._error_rate_window == 30.0
        assert wd._runaway_tool_limit == 50
        assert wd._identical_call_limit == 5

    def test_custom_thresholds(self) -> None:
        wd = Watchdog(
            denial_cascade_count=10,
            denial_cascade_window=20.0,
            forbidden_repeat_limit=5,
            error_rate_count=8,
            error_rate_window=60.0,
            runaway_tool_limit=100,
            identical_call_limit=10,
        )
        assert wd._denial_cascade_count == 10
        assert wd._denial_cascade_window == 20.0
        assert wd._forbidden_repeat_limit == 5
        assert wd._error_rate_count == 8
        assert wd._error_rate_window == 60.0
        assert wd._runaway_tool_limit == 100
        assert wd._identical_call_limit == 10

    def test_initial_state_not_blocked(self) -> None:
        wd = Watchdog()
        assert wd.is_blocked is False

    def test_record_decision_returns_watchdog_status(self) -> None:
        wd = Watchdog()
        status = wd.record_decision("Bash", {"command": "ls"}, Action.ALLOW)
        assert isinstance(status, WatchdogStatus)


# -- TestDenialCascade --


class TestDenialCascade:
    """Denial cascade sliding window tests."""

    def test_below_threshold_no_alert(self) -> None:
        wd = Watchdog(denial_cascade_count=5, forbidden_repeat_limit=999)
        for i in range(4):
            status = wd.record_decision("Bash", {"command": f"bad{i}"}, Action.DENY)
        assert status.blocked is False
        assert len(status.alerts) == 0

    def test_at_threshold_triggers_alert(self) -> None:
        wd = Watchdog(denial_cascade_count=5)
        for i in range(5):
            status = wd.record_decision(
                "Bash", {"command": f"bad{i}"}, Action.DENY,
            )
        assert status.blocked is True
        assert len(status.alerts) >= 1
        kinds = [a.kind for a in status.alerts]
        assert AlertKind.DENIAL_CASCADE in kinds

    def test_window_expiry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Old denials outside the window are pruned."""
        clock = [0.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])

        wd = Watchdog(denial_cascade_count=3, denial_cascade_window=5.0)
        # Two denials at t=0
        wd.record_decision("Bash", {"command": "a"}, Action.DENY)
        wd.record_decision("Bash", {"command": "b"}, Action.DENY)

        # Advance past the window
        clock[0] = 6.0
        status = wd.record_decision("Bash", {"command": "c"}, Action.DENY)
        # Only 1 denial in window (the one at t=6), not 3
        assert status.blocked is False

    def test_allow_decisions_ignored(self) -> None:
        wd = Watchdog(denial_cascade_count=3, runaway_tool_limit=999, identical_call_limit=999)
        for i in range(10):
            status = wd.record_decision("Bash", {"command": f"ls{i}"}, Action.ALLOW)
        assert status.blocked is False

    def test_sets_blocked_flag(self) -> None:
        wd = Watchdog(denial_cascade_count=2)
        wd.record_decision("Bash", {"command": "a"}, Action.DENY)
        wd.record_decision("Bash", {"command": "b"}, Action.DENY)
        assert wd.is_blocked is True


# -- TestForbiddenRepeat --


class TestForbiddenRepeat:
    """Forbidden pattern repeat tests."""

    def test_below_threshold_no_alert(self) -> None:
        wd = Watchdog(forbidden_repeat_limit=3, denial_cascade_count=999)
        for _ in range(2):
            status = wd.record_decision("Bash", {"command": "rm -rf /"}, Action.DENY)
        assert status.blocked is False

    def test_at_threshold_triggers_alert(self) -> None:
        wd = Watchdog(forbidden_repeat_limit=3, denial_cascade_count=999)
        for _ in range(3):
            status = wd.record_decision("Bash", {"command": "rm -rf /"}, Action.DENY)
        assert status.blocked is True
        kinds = [a.kind for a in status.alerts]
        assert AlertKind.FORBIDDEN_REPEAT in kinds

    def test_different_patterns_independent(self) -> None:
        wd = Watchdog(forbidden_repeat_limit=3, denial_cascade_count=999)
        for _ in range(2):
            wd.record_decision("Bash", {"command": "rm -rf /"}, Action.DENY)
        for _ in range(2):
            status = wd.record_decision("Bash", {"command": "halt"}, Action.DENY)
        assert status.blocked is False

    def test_persists_across_query_reset(self) -> None:
        wd = Watchdog(forbidden_repeat_limit=3, denial_cascade_count=999)
        for _ in range(2):
            wd.record_decision("Bash", {"command": "rm -rf /"}, Action.DENY)
        wd.reset_query()
        status = wd.record_decision("Bash", {"command": "rm -rf /"}, Action.DENY)
        assert status.blocked is True
        kinds = [a.kind for a in status.alerts]
        assert AlertKind.FORBIDDEN_REPEAT in kinds


# -- TestHighErrorRate --


class TestHighErrorRate:
    """Error rate sliding window tests."""

    def test_below_threshold_no_alert(self) -> None:
        wd = Watchdog(error_rate_count=5)
        for _ in range(4):
            status = wd.record_outcome("Bash", {"command": "x"}, "error")
        assert status.blocked is False

    def test_at_threshold_triggers_alert(self) -> None:
        wd = Watchdog(error_rate_count=5)
        for _ in range(5):
            status = wd.record_outcome("Bash", {"command": "x"}, "error")
        assert status.blocked is True
        kinds = [a.kind for a in status.alerts]
        assert AlertKind.HIGH_ERROR_RATE in kinds

    def test_window_expiry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = [0.0]
        monkeypatch.setattr(time, "monotonic", lambda: clock[0])

        wd = Watchdog(error_rate_count=3, error_rate_window=10.0)
        wd.record_outcome("Bash", {"command": "a"}, "error")
        wd.record_outcome("Bash", {"command": "b"}, "error")

        clock[0] = 11.0
        status = wd.record_outcome("Bash", {"command": "c"}, "error")
        assert status.blocked is False

    def test_success_ignored(self) -> None:
        wd = Watchdog(error_rate_count=3)
        for _ in range(10):
            status = wd.record_outcome("Bash", {"command": "x"}, "success")
        assert status.blocked is False


# -- TestRunawayToolLoop --


class TestRunawayToolLoop:
    """Runaway tool loop (per-query) tests."""

    def test_below_limit_no_alert(self) -> None:
        wd = Watchdog(runaway_tool_limit=5)
        for i in range(4):
            status = wd.record_decision("Bash", {"command": f"ls{i}"}, Action.ALLOW)
        assert status.blocked is False

    def test_at_limit_triggers_alert(self) -> None:
        wd = Watchdog(runaway_tool_limit=5)
        for i in range(5):
            status = wd.record_decision("Bash", {"command": f"ls{i}"}, Action.ALLOW)
        assert status.blocked is True
        kinds = [a.kind for a in status.alerts]
        assert AlertKind.RUNAWAY_TOOL_LOOP in kinds

    def test_reset_clears_count(self) -> None:
        wd = Watchdog(runaway_tool_limit=5)
        for i in range(4):
            wd.record_decision("Bash", {"command": f"ls{i}"}, Action.ALLOW)
        wd.reset_query()
        for i in range(4):
            status = wd.record_decision("Bash", {"command": f"ls{i}"}, Action.ALLOW)
        assert status.blocked is False

    def test_blocks_further_calls(self) -> None:
        wd = Watchdog(runaway_tool_limit=3)
        for i in range(3):
            wd.record_decision("Bash", {"command": f"x{i}"}, Action.ALLOW)
        assert wd.is_blocked is True
        # Further calls should return blocked immediately
        status = wd.record_decision("Bash", {"command": "y"}, Action.ALLOW)
        assert status.blocked is True
        assert status.alerts == []  # No new alerts when already blocked

    def test_allows_and_denies_both_count(self) -> None:
        wd = Watchdog(runaway_tool_limit=4, denial_cascade_count=999)
        wd.record_decision("Bash", {"command": "a"}, Action.ALLOW)
        wd.record_decision("Bash", {"command": "b"}, Action.DENY)
        wd.record_decision("Bash", {"command": "c"}, Action.ALLOW)
        status = wd.record_decision("Bash", {"command": "d"}, Action.DENY)
        assert status.blocked is True
        kinds = [a.kind for a in status.alerts]
        assert AlertKind.RUNAWAY_TOOL_LOOP in kinds


# -- TestIdenticalCallLoop --


class TestIdenticalCallLoop:
    """Identical call loop (per-query) tests."""

    def test_below_limit_no_alert(self) -> None:
        wd = Watchdog(identical_call_limit=5)
        for _ in range(4):
            status = wd.record_decision("Bash", {"command": "ls"}, Action.ALLOW)
        assert status.blocked is False

    def test_at_limit_triggers_alert(self) -> None:
        wd = Watchdog(identical_call_limit=5, runaway_tool_limit=999)
        for _ in range(5):
            status = wd.record_decision("Bash", {"command": "ls"}, Action.ALLOW)
        assert status.blocked is True
        kinds = [a.kind for a in status.alerts]
        assert AlertKind.IDENTICAL_CALL_LOOP in kinds

    def test_different_inputs_independent(self) -> None:
        wd = Watchdog(identical_call_limit=3, runaway_tool_limit=999)
        wd.record_decision("Bash", {"command": "ls"}, Action.ALLOW)
        wd.record_decision("Bash", {"command": "pwd"}, Action.ALLOW)
        status = wd.record_decision("Bash", {"command": "ls"}, Action.ALLOW)
        assert status.blocked is False

    def test_different_tools_independent(self) -> None:
        wd = Watchdog(identical_call_limit=3, runaway_tool_limit=999)
        wd.record_decision("Bash", {"command": "ls"}, Action.ALLOW)
        wd.record_decision("Read", {"command": "ls"}, Action.ALLOW)
        status = wd.record_decision("Bash", {"command": "ls"}, Action.ALLOW)
        assert status.blocked is False

    def test_reset_clears_signatures(self) -> None:
        wd = Watchdog(identical_call_limit=3, runaway_tool_limit=999)
        wd.record_decision("Bash", {"command": "ls"}, Action.ALLOW)
        wd.record_decision("Bash", {"command": "ls"}, Action.ALLOW)
        wd.reset_query()
        wd.record_decision("Bash", {"command": "ls"}, Action.ALLOW)
        status = wd.record_decision("Bash", {"command": "ls"}, Action.ALLOW)
        assert status.blocked is False


# -- TestResetQuery --


class TestResetQuery:
    """Per-query reset behaviour."""

    def test_resets_tool_count(self) -> None:
        wd = Watchdog(runaway_tool_limit=5)
        for i in range(4):
            wd.record_decision("Bash", {"command": f"x{i}"}, Action.ALLOW)
        wd.reset_query()
        assert wd._query_tool_count == 0

    def test_resets_signatures(self) -> None:
        wd = Watchdog()
        wd.record_decision("Bash", {"command": "ls"}, Action.ALLOW)
        wd.reset_query()
        assert len(wd._query_signatures) == 0

    def test_resets_blocked_flag(self) -> None:
        wd = Watchdog(runaway_tool_limit=2)
        wd.record_decision("Bash", {"command": "a"}, Action.ALLOW)
        wd.record_decision("Bash", {"command": "b"}, Action.ALLOW)
        assert wd.is_blocked is True
        wd.reset_query()
        assert wd.is_blocked is False

    def test_preserves_session_counters(self) -> None:
        wd = Watchdog(denial_cascade_count=999, forbidden_repeat_limit=999)
        wd.record_decision("Bash", {"command": "bad"}, Action.DENY)
        wd.record_outcome("Bash", {"command": "x"}, "error")
        wd.reset_query()
        # Session-scoped state should survive
        assert len(wd._denial_times) > 0
        assert sum(wd._forbidden_counts.values()) > 0
        assert len(wd._error_times) > 0


# -- TestResetSession --


class TestResetSession:
    """Full session reset."""

    def test_clears_denial_times(self) -> None:
        wd = Watchdog(denial_cascade_count=999)
        wd.record_decision("Bash", {"command": "x"}, Action.DENY)
        wd.reset_session()
        assert len(wd._denial_times) == 0

    def test_clears_forbidden_counts(self) -> None:
        wd = Watchdog(denial_cascade_count=999)
        wd.record_decision("Bash", {"command": "x"}, Action.DENY)
        wd.reset_session()
        assert sum(wd._forbidden_counts.values()) == 0

    def test_clears_error_times_and_query_state(self) -> None:
        wd = Watchdog(runaway_tool_limit=999)
        wd.record_outcome("Bash", {"command": "x"}, "error")
        wd.record_decision("Bash", {"command": "y"}, Action.ALLOW)
        wd.reset_session()
        assert len(wd._error_times) == 0
        assert wd._query_tool_count == 0
        assert wd.is_blocked is False


# -- TestMultipleAlerts --


class TestMultipleAlerts:
    """Simultaneous alert scenarios."""

    def test_simultaneous_denial_and_forbidden(self) -> None:
        """Denial cascade + forbidden repeat in the same call."""
        wd = Watchdog(denial_cascade_count=3, forbidden_repeat_limit=3)
        for _ in range(3):
            status = wd.record_decision("Bash", {"command": "rm -rf /"}, Action.DENY)
        kinds = {a.kind for a in status.alerts}
        assert AlertKind.DENIAL_CASCADE in kinds
        assert AlertKind.FORBIDDEN_REPEAT in kinds
        assert status.blocked is True

    def test_simultaneous_runaway_and_identical(self) -> None:
        """Runaway tool loop + identical call loop in the same call."""
        wd = Watchdog(runaway_tool_limit=5, identical_call_limit=5)
        for _ in range(5):
            status = wd.record_decision("Bash", {"command": "ls"}, Action.ALLOW)
        kinds = {a.kind for a in status.alerts}
        assert AlertKind.RUNAWAY_TOOL_LOOP in kinds
        assert AlertKind.IDENTICAL_CALL_LOOP in kinds

    def test_blocked_persists_across_calls(self) -> None:
        wd = Watchdog(runaway_tool_limit=2)
        wd.record_decision("Bash", {"command": "a"}, Action.ALLOW)
        wd.record_decision("Bash", {"command": "b"}, Action.ALLOW)
        assert wd.is_blocked is True
        # Further calls still blocked
        s1 = wd.record_decision("Bash", {"command": "c"}, Action.ALLOW)
        s2 = wd.record_decision("Bash", {"command": "d"}, Action.ALLOW)
        assert s1.blocked is True
        assert s2.blocked is True


# -- TestInputKey --


class TestInputKey:
    """_input_key helper function tests."""

    def test_deterministic(self) -> None:
        k1 = _input_key("Bash", {"command": "ls"})
        k2 = _input_key("Bash", {"command": "ls"})
        assert k1 == k2
        assert len(k1) == 16

    def test_different_inputs_differ(self) -> None:
        k1 = _input_key("Bash", {"command": "ls"})
        k2 = _input_key("Bash", {"command": "pwd"})
        assert k1 != k2

    def test_key_order_independent(self) -> None:
        k1 = _input_key("Bash", {"a": 1, "b": 2})
        k2 = _input_key("Bash", {"b": 2, "a": 1})
        assert k1 == k2
