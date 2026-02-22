"""Tests for the ChatOS CLI test harness."""

from pathlib import Path

import pytest

from src.cli import resolve_rules_path, parse_args, _render_tool_input


# -- Rules path resolution tests --


class TestResolveRulesPath:
    def test_explicit_path(self, tmp_path: Path) -> None:
        rules = tmp_path / "custom.toml"
        rules.touch()
        result = resolve_rules_path(str(rules))
        assert result == rules

    def test_falls_back_to_dev_path(self, tmp_path: Path, monkeypatch) -> None:
        """When system path doesn't exist, uses project-local rules."""
        import src.cli as cli_mod

        dev_rules = tmp_path / "rules.toml"
        dev_rules.write_text('[meta]\nversion = "1.0"\nhostname = "x"\n')

        monkeypatch.setattr(cli_mod, "DEFAULT_RULES_PATH", tmp_path / "nope.toml")
        monkeypatch.setattr(cli_mod, "DEV_RULES_PATH", dev_rules)

        result = resolve_rules_path(None)
        assert result == dev_rules

    def test_exits_when_no_rules_found(self, tmp_path: Path, monkeypatch) -> None:
        import src.cli as cli_mod

        monkeypatch.setattr(cli_mod, "DEFAULT_RULES_PATH", tmp_path / "nope1.toml")
        monkeypatch.setattr(cli_mod, "DEV_RULES_PATH", tmp_path / "nope2.toml")

        with pytest.raises(SystemExit):
            resolve_rules_path(None)


# -- Argument parsing tests --


class TestParseArgs:
    def test_defaults(self, monkeypatch) -> None:
        monkeypatch.setattr("sys.argv", ["cli"])
        args = parse_args()
        assert args.rules is None
        assert args.log_dir is None
        assert args.model == "sonnet"

    def test_custom_args(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["cli", "--rules", "/tmp/rules.toml", "--model", "sonnet", "--log-dir", "/tmp/logs"],
        )
        args = parse_args()
        assert args.rules == "/tmp/rules.toml"
        assert args.model == "sonnet"
        assert args.log_dir == "/tmp/logs"


# -- Event rendering tests --


class TestRenderToolInput:
    def test_bash_command(self) -> None:
        result = _render_tool_input({"command": "ls -la"})
        assert result == "ls -la"

    def test_file_path(self) -> None:
        result = _render_tool_input({"file_path": "/tmp/test.txt"})
        assert result == "/tmp/test.txt"

    def test_other_input(self) -> None:
        result = _render_tool_input({"pattern": "*.py"})
        assert "*.py" in result

    def test_empty_input(self) -> None:
        result = _render_tool_input({})
        assert result == "{}"
