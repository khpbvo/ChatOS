"""Tests for the env file loader in src/__main__.py."""

import os
from pathlib import Path

import pytest

from src.__main__ import load_env_file


@pytest.fixture()
def env_file(tmp_path: Path) -> Path:
    return tmp_path / "env"


class TestLoadEnvFile:
    def test_loads_key_value(self, env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file.write_text("ANTHROPIC_API_KEY=sk-ant-test123\n")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        load_env_file(env_file)
        assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-test123"
        monkeypatch.delenv("ANTHROPIC_API_KEY")

    def test_skips_comments(self, env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file.write_text("# This is a comment\nMY_VAR=hello\n")
        monkeypatch.delenv("MY_VAR", raising=False)
        load_env_file(env_file)
        assert os.environ["MY_VAR"] == "hello"
        monkeypatch.delenv("MY_VAR")

    def test_skips_blank_lines(self, env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file.write_text("\n\nMY_VAR=hello\n\n")
        monkeypatch.delenv("MY_VAR", raising=False)
        load_env_file(env_file)
        assert os.environ["MY_VAR"] == "hello"
        monkeypatch.delenv("MY_VAR")

    def test_existing_env_takes_precedence(
        self, env_file: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        env_file.write_text("MY_VAR=from-file\n")
        monkeypatch.setenv("MY_VAR", "from-env")
        load_env_file(env_file)
        assert os.environ["MY_VAR"] == "from-env"

    def test_strips_quotes(self, env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file.write_text('MY_VAR="quoted-value"\n')
        monkeypatch.delenv("MY_VAR", raising=False)
        load_env_file(env_file)
        assert os.environ["MY_VAR"] == "quoted-value"
        monkeypatch.delenv("MY_VAR")

    def test_strips_single_quotes(self, env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file.write_text("MY_VAR='single-quoted'\n")
        monkeypatch.delenv("MY_VAR", raising=False)
        load_env_file(env_file)
        assert os.environ["MY_VAR"] == "single-quoted"
        monkeypatch.delenv("MY_VAR")

    def test_missing_file_is_silent(self, tmp_path: Path) -> None:
        load_env_file(tmp_path / "nonexistent")

    def test_unreadable_file_is_silent(self, env_file: Path) -> None:
        env_file.write_text("MY_VAR=hello\n")
        env_file.chmod(0o000)
        try:
            load_env_file(env_file)
        finally:
            env_file.chmod(0o644)

    def test_skips_lines_without_equals(
        self, env_file: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        env_file.write_text("NOEQUALS\nMY_VAR=good\n")
        monkeypatch.delenv("MY_VAR", raising=False)
        load_env_file(env_file)
        assert "NOEQUALS" not in os.environ
        assert os.environ["MY_VAR"] == "good"
        monkeypatch.delenv("MY_VAR")

    def test_commented_key_not_loaded(
        self, env_file: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        env_file.write_text("#ANTHROPIC_API_KEY=sk-ant-...\n")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        load_env_file(env_file)
        assert "ANTHROPIC_API_KEY" not in os.environ

    def test_multiple_keys(self, env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file.write_text("KEY_A=alpha\nKEY_B=bravo\n")
        monkeypatch.delenv("KEY_A", raising=False)
        monkeypatch.delenv("KEY_B", raising=False)
        load_env_file(env_file)
        assert os.environ["KEY_A"] == "alpha"
        assert os.environ["KEY_B"] == "bravo"
        monkeypatch.delenv("KEY_A")
        monkeypatch.delenv("KEY_B")

    def test_value_with_equals_sign(
        self, env_file: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        env_file.write_text("MY_VAR=abc=def=ghi\n")
        monkeypatch.delenv("MY_VAR", raising=False)
        load_env_file(env_file)
        assert os.environ["MY_VAR"] == "abc=def=ghi"
        monkeypatch.delenv("MY_VAR")
