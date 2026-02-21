"""Integration tests for the ChatOS core engine.

Tests the full pipeline: rules.toml → RulesEngine → Orchestrator hooks → AuditLogger.
Uses the project's actual rules.toml to verify production behavior.
"""

import json
from pathlib import Path

import pytest

from src.audit import AuditLogger
from src.models import Action, RulesConfig, RulesMeta
from src.orchestrator import Orchestrator
from src.rules_engine import RulesEngine


# -- Fixtures using production rules.toml --

PROD_RULES_PATH = Path(__file__).resolve().parent.parent / "etc" / "chatos" / "rules.toml"

EMPTY_CTX = {"signal": None}


@pytest.fixture
def prod_engine() -> RulesEngine:
    """RulesEngine loaded from the project's actual rules.toml."""
    return RulesEngine.from_file(PROD_RULES_PATH)


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    return tmp_path / "logs"


@pytest.fixture
def audit_logger(log_dir: Path) -> AuditLogger:
    return AuditLogger(log_dir)


@pytest.fixture
def prod_orchestrator(prod_engine: RulesEngine, audit_logger: AuditLogger) -> Orchestrator:
    return Orchestrator(prod_engine, audit_logger)


def make_pre_hook_input(tool_name: str, tool_input: dict, session_id: str = "int-test") -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "transcript_path": "/tmp/transcript",
        "cwd": "/usr/local/share/chatos",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_use_id": "int-test-id",
    }


def make_post_hook_input(
    tool_name: str, tool_input: dict, tool_response: object = None, session_id: str = "int-test"
) -> dict:
    return {
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "transcript_path": "/tmp/transcript",
        "cwd": "/usr/local/share/chatos",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_response": tool_response,
        "tool_use_id": "int-test-id",
    }


# =============================================================================
# Production rules.toml: exhaustive safe pattern tests
# =============================================================================


class TestProdSafePatterns:
    """Verify every safe_pattern from the production rules.toml."""

    @pytest.mark.parametrize(
        "command",
        [
            "cat /etc/hosts",
            "ls -la /tmp",
            "find /var -name '*.log'",
            "grep -r 'error' /var/log",
            "wc -l /etc/hosts",
            "head -20 /var/log/messages",
            "tail -f /var/log/daemon",
            "df -h",
            "uptime",
            "uname -a",
            "whoami",
            "date",
            "cal",
            "pkg_info",
            "pkg_info -Q nginx",
            "sysctl hw.ncpu",
            "ifconfig em0",
            "netstat -an",
            "ps aux",
            "ps aux -w",
            "top -b -n 1",
            "vmstat",
            "vmstat 1 5",
            "iostat",
        ],
    )
    def test_safe_commands(self, prod_engine: RulesEngine, command: str) -> None:
        d = prod_engine.check_command(command)
        assert d.action == Action.ALLOW, f"Expected ALLOW for '{command}', got {d.action}: {d.reason}"


# =============================================================================
# Production rules.toml: exhaustive confirm pattern tests
# =============================================================================


class TestProdConfirmPatterns:
    """Verify every confirm_pattern from the production rules.toml."""

    @pytest.mark.parametrize(
        "command",
        [
            "pkg_add nginx",
            "pkg_delete vim",
            "rcctl enable nginx",
            "rcctl start httpd",
            "doas pkg_add git",
            "mv /tmp/a /tmp/b",
            "cp /etc/hosts /tmp/hosts.bak",
            "chmod 644 /tmp/test",
            "chown _chatos /tmp/test",
            "mkdir /tmp/newdir",
            "rmdir /tmp/olddir",
            "tee /tmp/output.txt",
            "dd if=/tmp/a of=/tmp/b bs=1M",
        ],
    )
    def test_confirm_commands(self, prod_engine: RulesEngine, command: str) -> None:
        d = prod_engine.check_command(command)
        assert d.action == Action.CONFIRM, (
            f"Expected CONFIRM for '{command}', got {d.action}: {d.reason}"
        )


# =============================================================================
# Production rules.toml: exhaustive forbidden pattern tests
# =============================================================================


class TestProdForbiddenPatterns:
    """Verify every forbidden_pattern from the production rules.toml."""

    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf /",
            "rm -rf /*",
            "dd if=/dev/zero of=/dev/rsd0c",
            "chmod -R 777 /",
            "halt",
            "reboot",
            "shutdown -h now",
            "passwd root",
            "vipw",
            "usermod -G wheel agent01",
            "useradd baduser",
            "userdel agent01",
            "pfctl -d",
            "echo bad >/etc/passwd",
            "echo bad >> /etc/shadow",
        ],
    )
    def test_forbidden_commands(self, prod_engine: RulesEngine, command: str) -> None:
        d = prod_engine.check_command(command)
        assert d.action == Action.DENY, (
            f"Expected DENY for '{command}', got {d.action}: {d.reason}"
        )


# =============================================================================
# Production rules.toml: exhaustive forbidden write path tests
# =============================================================================


class TestProdForbiddenWritePaths:
    """Verify every forbidden_write_path from the production rules.toml."""

    @pytest.mark.parametrize(
        "path",
        [
            "/etc/master.passwd",
            "/etc/doas.conf",
            "/etc/chatos/rules.toml",
            "/etc/pf.conf",
            "/bsd",
            "/bsd.rd",
        ],
    )
    def test_forbidden_write_paths(self, prod_engine: RulesEngine, path: str) -> None:
        d = prod_engine.check_write_path(path)
        assert d.action == Action.DENY, f"Expected DENY for write to '{path}', got {d.action}"


# =============================================================================
# Integration: full PreToolUse → audit pipeline
# =============================================================================


class TestPreToolUseAuditPipeline:
    """Test that PreToolUse hooks correctly log to audit."""

    async def test_safe_command_pipeline(
        self, prod_orchestrator: Orchestrator, log_dir: Path
    ) -> None:
        hook_input = make_pre_hook_input("Bash", {"command": "uptime"})
        result = await prod_orchestrator.pre_tool_use(hook_input, None, EMPTY_CTX)

        # Hook returns allow
        specific = result.get("hookSpecificOutput", {})
        assert specific["permissionDecision"] == "allow"

        # Audit log recorded
        log_file = next(log_dir.glob("audit-*.jsonl"))
        entry = json.loads(log_file.read_text().strip())
        assert entry["tool_name"] == "Bash"
        assert entry["decision"] == "allow"
        assert entry["session_id"] == "int-test"

    async def test_forbidden_command_pipeline(
        self, prod_orchestrator: Orchestrator, log_dir: Path
    ) -> None:
        hook_input = make_pre_hook_input("Bash", {"command": "rm -rf /"})
        result = await prod_orchestrator.pre_tool_use(hook_input, None, EMPTY_CTX)

        # Hook returns deny
        assert result.get("decision") == "block"
        specific = result.get("hookSpecificOutput", {})
        assert specific["permissionDecision"] == "deny"

        # Denial is logged
        log_file = next(log_dir.glob("audit-*.jsonl"))
        entry = json.loads(log_file.read_text().strip())
        assert entry["decision"] == "deny"
        assert entry["matched_pattern"] == "rm -rf /"

    async def test_confirm_command_pipeline(
        self, prod_orchestrator: Orchestrator, log_dir: Path
    ) -> None:
        hook_input = make_pre_hook_input("Bash", {"command": "pkg_add nginx"})
        result = await prod_orchestrator.pre_tool_use(hook_input, None, EMPTY_CTX)

        specific = result.get("hookSpecificOutput", {})
        assert specific["permissionDecision"] == "ask"

        log_file = next(log_dir.glob("audit-*.jsonl"))
        entry = json.loads(log_file.read_text().strip())
        assert entry["decision"] == "confirm"

    async def test_forbidden_write_pipeline(
        self, prod_orchestrator: Orchestrator, log_dir: Path
    ) -> None:
        hook_input = make_pre_hook_input("Edit", {"file_path": "/etc/pf.conf"})
        result = await prod_orchestrator.pre_tool_use(hook_input, None, EMPTY_CTX)

        assert result.get("decision") == "block"

        log_file = next(log_dir.glob("audit-*.jsonl"))
        entry = json.loads(log_file.read_text().strip())
        assert entry["tool_name"] == "Edit"
        assert entry["decision"] == "deny"


# =============================================================================
# Integration: full PreToolUse + PostToolUse lifecycle
# =============================================================================


class TestFullToolLifecycle:
    """Test the complete lifecycle: PreToolUse check → execution → PostToolUse log."""

    async def test_allowed_tool_full_lifecycle(
        self, prod_orchestrator: Orchestrator, log_dir: Path
    ) -> None:
        """Simulate: safe command allowed → executes → outcome logged."""
        cmd = {"command": "ls -la /tmp"}

        # PreToolUse: check and log decision
        pre_input = make_pre_hook_input("Bash", cmd, session_id="lifecycle-1")
        pre_result = await prod_orchestrator.pre_tool_use(pre_input, None, EMPTY_CTX)
        specific = pre_result.get("hookSpecificOutput", {})
        assert specific["permissionDecision"] == "allow"

        # PostToolUse: log outcome
        post_input = make_post_hook_input(
            "Bash", cmd, tool_response="total 42\ndrwxrwxrwt ...", session_id="lifecycle-1"
        )
        await prod_orchestrator.post_tool_use(post_input, None, EMPTY_CTX)

        # Verify both entries in audit log
        log_file = next(log_dir.glob("audit-*.jsonl"))
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

        pre_entry = json.loads(lines[0])
        post_entry = json.loads(lines[1])

        assert pre_entry["decision"] == "allow"
        assert pre_entry["session_id"] == "lifecycle-1"
        assert post_entry["outcome"] == "success"
        assert post_entry["session_id"] == "lifecycle-1"

    async def test_denied_tool_no_post_hook(
        self, prod_orchestrator: Orchestrator, log_dir: Path
    ) -> None:
        """Denied commands never execute, so only PreToolUse is logged."""
        pre_input = make_pre_hook_input("Bash", {"command": "halt"})
        await prod_orchestrator.pre_tool_use(pre_input, None, EMPTY_CTX)

        log_file = next(log_dir.glob("audit-*.jsonl"))
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["decision"] == "deny"

    async def test_error_tool_lifecycle(
        self, prod_orchestrator: Orchestrator, log_dir: Path
    ) -> None:
        """Simulate: allowed command → execution error → error logged."""
        cmd = {"command": "cat /nonexistent/file"}

        pre_input = make_pre_hook_input("Bash", cmd)
        await prod_orchestrator.pre_tool_use(pre_input, None, EMPTY_CTX)

        post_input = make_post_hook_input(
            "Bash", cmd, tool_response={"is_error": True, "message": "No such file"}
        )
        await prod_orchestrator.post_tool_use(post_input, None, EMPTY_CTX)

        log_file = next(log_dir.glob("audit-*.jsonl"))
        lines = log_file.read_text().strip().split("\n")
        post_entry = json.loads(lines[1])
        assert post_entry["outcome"] == "error"
        assert "is_error" in post_entry["error"]


# =============================================================================
# Integration: multi-operation session
# =============================================================================


class TestMultiOperationSession:
    """Test a realistic sequence of operations in a single session."""

    async def test_mixed_operations_session(
        self, prod_orchestrator: Orchestrator, log_dir: Path
    ) -> None:
        """Simulate a session with safe, confirm, and forbidden operations."""
        session = "multi-op-session"

        # 1. Safe: check uptime
        pre = make_pre_hook_input("Bash", {"command": "uptime"}, session_id=session)
        r1 = await prod_orchestrator.pre_tool_use(pre, None, EMPTY_CTX)
        assert r1.get("hookSpecificOutput", {})["permissionDecision"] == "allow"

        post = make_post_hook_input("Bash", {"command": "uptime"}, "up 5 days", session_id=session)
        await prod_orchestrator.post_tool_use(post, None, EMPTY_CTX)

        # 2. Safe: read a file
        pre = make_pre_hook_input("Read", {"file_path": "/etc/hosts"}, session_id=session)
        r2 = await prod_orchestrator.pre_tool_use(pre, None, EMPTY_CTX)
        assert r2.get("hookSpecificOutput", {})["permissionDecision"] == "allow"

        # 3. Confirm: install package
        pre = make_pre_hook_input("Bash", {"command": "pkg_add nginx"}, session_id=session)
        r3 = await prod_orchestrator.pre_tool_use(pre, None, EMPTY_CTX)
        assert r3.get("hookSpecificOutput", {})["permissionDecision"] == "ask"

        # 4. Forbidden: try to halt
        pre = make_pre_hook_input("Bash", {"command": "halt"}, session_id=session)
        r4 = await prod_orchestrator.pre_tool_use(pre, None, EMPTY_CTX)
        assert r4.get("decision") == "block"

        # 5. Forbidden write: try to edit pf.conf
        pre = make_pre_hook_input("Write", {"file_path": "/etc/pf.conf"}, session_id=session)
        r5 = await prod_orchestrator.pre_tool_use(pre, None, EMPTY_CTX)
        assert r5.get("decision") == "block"

        # Verify all 6 entries logged (5 PreToolUse + 1 PostToolUse)
        log_file = next(log_dir.glob("audit-*.jsonl"))
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 6

        # All entries belong to the same session
        for line in lines:
            entry = json.loads(line)
            assert entry["session_id"] == session


# =============================================================================
# Edge cases: rules engine security
# =============================================================================


class TestSecurityEdgeCases:
    """Edge cases that test the security of pattern matching."""

    def test_command_injection_via_semicolon(self, prod_engine: RulesEngine) -> None:
        """Semicolon-chained forbidden command is caught."""
        d = prod_engine.check_command("ls /tmp; halt")
        assert d.action == Action.DENY

    def test_command_injection_via_pipe(self, prod_engine: RulesEngine) -> None:
        d = prod_engine.check_command("echo | reboot")
        assert d.action == Action.DENY

    def test_command_injection_via_backticks(self, prod_engine: RulesEngine) -> None:
        d = prod_engine.check_command("echo `halt`")
        assert d.action == Action.DENY

    def test_command_injection_via_subshell(self, prod_engine: RulesEngine) -> None:
        d = prod_engine.check_command("echo $(reboot)")
        assert d.action == Action.DENY

    def test_command_injection_via_and(self, prod_engine: RulesEngine) -> None:
        d = prod_engine.check_command("ls /tmp && shutdown -h now")
        assert d.action == Action.DENY

    def test_command_injection_via_or(self, prod_engine: RulesEngine) -> None:
        d = prod_engine.check_command("false || halt")
        assert d.action == Action.DENY

    def test_path_traversal_double_dot(self, prod_engine: RulesEngine) -> None:
        d = prod_engine.check_write_path("/tmp/../etc/master.passwd")
        assert d.action == Action.DENY

    def test_path_traversal_multiple_levels(self, prod_engine: RulesEngine) -> None:
        d = prod_engine.check_write_path("/tmp/../../bsd")
        assert d.action == Action.DENY

    def test_path_with_trailing_slash(self, prod_engine: RulesEngine) -> None:
        d = prod_engine.check_write_path("/etc/master.passwd/")
        # normpath strips trailing slash, so this should still match
        assert d.action == Action.DENY

    def test_unknown_tool_default_deny(self, prod_engine: RulesEngine) -> None:
        d = prod_engine.check_tool_use("NotebookEdit", {"cell": 1})
        assert d.action == Action.DENY

    def test_bash_missing_command_key(self, prod_engine: RulesEngine) -> None:
        """Missing 'command' key in Bash tool input defaults to empty string."""
        d = prod_engine.check_tool_use("Bash", {})
        assert d.action == Action.DENY

    def test_write_missing_file_path_key(self, prod_engine: RulesEngine) -> None:
        """Missing 'file_path' key defaults to empty string, which is allowed."""
        d = prod_engine.check_tool_use("Write", {})
        assert d.action == Action.ALLOW  # empty path is not in forbidden list

    def test_dd_to_block_device_forbidden(self, prod_engine: RulesEngine) -> None:
        d = prod_engine.check_command("dd if=/dev/zero of=/dev/sd0a bs=512")
        assert d.action == Action.DENY

    def test_safe_dd_to_file_requires_confirm(self, prod_engine: RulesEngine) -> None:
        """dd to a regular file should require confirmation, not be forbidden."""
        d = prod_engine.check_command("dd if=/tmp/input of=/tmp/output bs=1M")
        assert d.action == Action.CONFIRM

    def test_known_false_positive_passwd_in_path(self, prod_engine: RulesEngine) -> None:
        """The forbidden pattern 'passwd' catches /etc/passwd in paths.

        This is a known limitation of substring matching. The 'passwd'
        pattern targets the passwd command but also matches file paths
        containing 'passwd'. A future regex-based matcher could fix this.
        """
        d = prod_engine.check_command("wc -l /etc/passwd")
        assert d.action == Action.DENY
        assert d.matched_pattern == "passwd"


# =============================================================================
# Edge cases: prefix matching
# =============================================================================


class TestPrefixMatchEdgeCases:
    """Test the _prefix_match static method edge cases."""

    def test_exact_match_no_space(self) -> None:
        assert RulesEngine._prefix_match("uptime", "uptime") is True

    def test_prefix_with_trailing_space(self) -> None:
        assert RulesEngine._prefix_match("cat /etc/hosts", "cat ") is True

    def test_no_false_prefix(self) -> None:
        """'cat' should not match 'catalog'."""
        assert RulesEngine._prefix_match("catalog", "cat ") is False

    def test_no_false_prefix_no_space(self) -> None:
        """'uptime' should not match 'uptimer'."""
        assert RulesEngine._prefix_match("uptimer", "uptime") is False

    def test_pattern_longer_than_command(self) -> None:
        assert RulesEngine._prefix_match("ls", "ls -la") is False

    def test_command_equals_stripped_pattern(self) -> None:
        """'cat' matches pattern 'cat ' (stripped = 'cat')."""
        assert RulesEngine._prefix_match("cat", "cat ") is True

    def test_multi_word_pattern(self) -> None:
        assert RulesEngine._prefix_match("ps aux", "ps aux") is True

    def test_multi_word_pattern_with_extra(self) -> None:
        assert RulesEngine._prefix_match("ps aux -w", "ps aux") is True

    def test_empty_command(self) -> None:
        assert RulesEngine._prefix_match("", "cat ") is False

    def test_empty_pattern(self) -> None:
        """Empty pattern stripped is '', which equals empty command."""
        assert RulesEngine._prefix_match("", "") is True


# =============================================================================
# Pydantic model validation
# =============================================================================


class TestModelValidation:
    """Test Pydantic model serialization and validation."""

    def test_decision_json_round_trip(self) -> None:
        from src.models import Decision

        d = Decision(action=Action.DENY, reason="test", matched_pattern="halt")
        data = json.loads(d.model_dump_json())
        assert data["action"] == "deny"
        assert data["matched_pattern"] == "halt"

        d2 = Decision.model_validate(data)
        assert d2.action == Action.DENY

    def test_audit_entry_json_round_trip(self) -> None:
        from src.models import AuditEntry

        entry = AuditEntry(
            timestamp="2026-02-21T10:00:00+00:00",
            session_id="s1",
            tool_name="Bash",
            tool_input={"command": "ls"},
            decision=Action.ALLOW,
            reason="safe",
            outcome="success",
        )
        data = json.loads(entry.model_dump_json())
        assert data["decision"] == "allow"
        assert data["outcome"] == "success"

        e2 = AuditEntry.model_validate(data)
        assert e2.tool_name == "Bash"

    def test_rules_config_defaults(self) -> None:
        config = RulesConfig(
            meta=RulesMeta(version="1.0", hostname="x"),
        )
        assert config.permissions.safe_patterns == []
        assert config.permissions.forbidden_write_paths == []
        assert config.resources.max_concurrent_ops == 5
        assert config.resources.session_timeout_minutes == 30
