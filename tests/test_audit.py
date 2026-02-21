"""Tests for the ChatOS audit logger."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.audit import AuditLogger
from src.models import Action, AuditEntry, Decision


# -- Fixtures --


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    return tmp_path / "logs"


@pytest.fixture
def logger(log_dir: Path) -> AuditLogger:
    return AuditLogger(log_dir)


@pytest.fixture
def sample_entry() -> AuditEntry:
    return AuditEntry(
        timestamp="2026-02-21T10:00:00+00:00",
        session_id="sess-001",
        tool_name="Bash",
        tool_input={"command": "ls -la /tmp"},
        decision=Action.ALLOW,
        reason="Command matches safe pattern",
        matched_pattern="ls ",
    )


@pytest.fixture
def sample_decision() -> Decision:
    return Decision(
        action=Action.ALLOW,
        reason="Command matches safe pattern",
        matched_pattern="ls ",
    )


# -- Initialization tests --


class TestAuditLoggerInit:
    def test_creates_log_directory(self, log_dir: Path) -> None:
        assert not log_dir.exists()
        AuditLogger(log_dir)
        assert log_dir.is_dir()

    def test_accepts_existing_directory(self, tmp_path: Path) -> None:
        AuditLogger(tmp_path)  # should not raise

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        logger = AuditLogger(str(tmp_path / "logs"))
        assert logger.log_dir == tmp_path / "logs"


# -- Log entry tests --


class TestLogEntry:
    async def test_writes_jsonl_file(
        self, logger: AuditLogger, sample_entry: AuditEntry
    ) -> None:
        await logger.log(sample_entry)
        log_files = list(logger.log_dir.glob("audit-*.jsonl"))
        assert len(log_files) == 1

    async def test_entry_is_valid_json(
        self, logger: AuditLogger, sample_entry: AuditEntry
    ) -> None:
        await logger.log(sample_entry)
        log_file = next(logger.log_dir.glob("audit-*.jsonl"))
        line = log_file.read_text().strip()
        data = json.loads(line)
        assert data["tool_name"] == "Bash"
        assert data["decision"] == "allow"
        assert data["session_id"] == "sess-001"

    async def test_multiple_entries(
        self, logger: AuditLogger, sample_entry: AuditEntry
    ) -> None:
        await logger.log(sample_entry)
        await logger.log(sample_entry)
        await logger.log(sample_entry)
        log_file = next(logger.log_dir.glob("audit-*.jsonl"))
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 3
        for line in lines:
            json.loads(line)  # all valid JSON

    async def test_entry_fields_complete(
        self, logger: AuditLogger, sample_entry: AuditEntry
    ) -> None:
        await logger.log(sample_entry)
        log_file = next(logger.log_dir.glob("audit-*.jsonl"))
        data = json.loads(log_file.read_text().strip())
        assert data["timestamp"] == "2026-02-21T10:00:00+00:00"
        assert data["tool_input"] == {"command": "ls -la /tmp"}
        assert data["reason"] == "Command matches safe pattern"
        assert data["matched_pattern"] == "ls "
        assert data["outcome"] is None
        assert data["error"] is None

    async def test_date_based_filename(self, logger: AuditLogger) -> None:
        entry = AuditEntry(
            timestamp=datetime.now(UTC).isoformat(),
            tool_name="Bash",
            tool_input={"command": "uptime"},
            decision=Action.ALLOW,
            reason="safe",
        )
        await logger.log(entry)
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        expected = logger.log_dir / f"audit-{today}.jsonl"
        assert expected.exists()


# -- Convenience method tests --


class TestLogDecision:
    async def test_log_decision(
        self, logger: AuditLogger, sample_decision: Decision
    ) -> None:
        await logger.log_decision(
            tool_name="Bash",
            tool_input={"command": "ls -la"},
            decision=sample_decision,
            session_id="sess-002",
        )
        log_file = next(logger.log_dir.glob("audit-*.jsonl"))
        data = json.loads(log_file.read_text().strip())
        assert data["tool_name"] == "Bash"
        assert data["decision"] == "allow"
        assert data["session_id"] == "sess-002"
        assert data["matched_pattern"] == "ls "

    async def test_log_denied_decision(self, logger: AuditLogger) -> None:
        decision = Decision(
            action=Action.DENY,
            reason="Command matches forbidden pattern",
            matched_pattern="rm -rf /",
        )
        await logger.log_decision(
            tool_name="Bash",
            tool_input={"command": "rm -rf /"},
            decision=decision,
        )
        log_file = next(logger.log_dir.glob("audit-*.jsonl"))
        data = json.loads(log_file.read_text().strip())
        assert data["decision"] == "deny"
        assert data["matched_pattern"] == "rm -rf /"

    async def test_log_decision_has_timestamp(self, logger: AuditLogger) -> None:
        decision = Decision(action=Action.ALLOW, reason="safe")
        await logger.log_decision("Bash", {"command": "date"}, decision)
        log_file = next(logger.log_dir.glob("audit-*.jsonl"))
        data = json.loads(log_file.read_text().strip())
        # Timestamp should be a valid ISO format from today
        ts = datetime.fromisoformat(data["timestamp"])
        assert ts.year == datetime.now(UTC).year


class TestLogOutcome:
    async def test_log_success_outcome(self, logger: AuditLogger) -> None:
        await logger.log_outcome(
            tool_name="Bash",
            tool_input={"command": "ls /tmp"},
            outcome="success",
            session_id="sess-003",
        )
        log_file = next(logger.log_dir.glob("audit-*.jsonl"))
        data = json.loads(log_file.read_text().strip())
        assert data["outcome"] == "success"
        assert data["error"] is None

    async def test_log_error_outcome(self, logger: AuditLogger) -> None:
        await logger.log_outcome(
            tool_name="Bash",
            tool_input={"command": "cat /nonexistent"},
            outcome="error",
            error="No such file or directory",
        )
        log_file = next(logger.log_dir.glob("audit-*.jsonl"))
        data = json.loads(log_file.read_text().strip())
        assert data["outcome"] == "error"
        assert data["error"] == "No such file or directory"

    async def test_log_outcome_default_session(self, logger: AuditLogger) -> None:
        await logger.log_outcome("Bash", {"command": "uptime"}, "success")
        log_file = next(logger.log_dir.glob("audit-*.jsonl"))
        data = json.loads(log_file.read_text().strip())
        assert data["session_id"] == ""
