"""Tests for the ChatOS CLI test harness."""

import os
from pathlib import Path

import pytest

from src.cli import load_env_file, resolve_rules_path, parse_args


# -- Environment loading tests --


class TestLoadEnvFile:
    def test_loads_key_value_pairs(self, tmp_path: Path) -> None:
        env_file = tmp_path / "env"
        env_file.write_text("TEST_CLI_KEY=test_value\n")

        os.environ.pop("TEST_CLI_KEY", None)
        load_env_file(env_file)
        assert os.environ["TEST_CLI_KEY"] == "test_value"
        os.environ.pop("TEST_CLI_KEY", None)

    def test_skips_comments_and_blanks(self, tmp_path: Path) -> None:
        env_file = tmp_path / "env"
        env_file.write_text("# comment\n\nTEST_CLI_KEY2=val2\n")

        os.environ.pop("TEST_CLI_KEY2", None)
        load_env_file(env_file)
        assert os.environ["TEST_CLI_KEY2"] == "val2"
        os.environ.pop("TEST_CLI_KEY2", None)

    def test_does_not_override_existing(self, tmp_path: Path) -> None:
        env_file = tmp_path / "env"
        env_file.write_text("TEST_CLI_KEY3=new_value\n")

        os.environ["TEST_CLI_KEY3"] = "original"
        load_env_file(env_file)
        assert os.environ["TEST_CLI_KEY3"] == "original"
        os.environ.pop("TEST_CLI_KEY3", None)

    def test_missing_file_is_noop(self, tmp_path: Path) -> None:
        load_env_file(tmp_path / "nonexistent")  # should not raise


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
            ["cli", "--rules", "/tmp/rules.toml", "--model", "opus", "--log-dir", "/tmp/logs"],
        )
        args = parse_args()
        assert args.rules == "/tmp/rules.toml"
        assert args.model == "opus"
        assert args.log_dir == "/tmp/logs"
