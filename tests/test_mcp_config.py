"""Tests for the ChatOS MCP configuration loader."""

from pathlib import Path

import pytest

from src.mcp_config import McpConfigLoader
from src.models import EmailMcpConfig, McpConfig


# -- Fixtures --


@pytest.fixture
def mcp_toml(tmp_path: Path) -> Path:
    """Write a valid mcp.toml with email config."""
    toml_path = tmp_path / "mcp.toml"
    toml_path.write_text("""\
[email]
imap_server = "imap.example.com"
imap_port = 993
smtp_server = "smtp.example.com"
smtp_port = 587
username = "user@example.com"
password = "secret123"
""")
    return toml_path


@pytest.fixture
def loader(mcp_toml: Path) -> McpConfigLoader:
    return McpConfigLoader.from_path(mcp_toml)


# -- File loading tests --


class TestFileLoading:
    def test_loads_email_config(self, loader: McpConfigLoader) -> None:
        assert loader.config.email is not None
        assert loader.config.email.imap_server == "imap.example.com"

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.toml"
        loader = McpConfigLoader.from_path(missing)
        assert loader.config.email is None

    def test_no_email_section(self, tmp_path: Path) -> None:
        toml_path = tmp_path / "empty.toml"
        toml_path.write_text("# No email config\n")
        loader = McpConfigLoader.from_path(toml_path)
        assert loader.config.email is None

    def test_default_ports(self, tmp_path: Path) -> None:
        toml_path = tmp_path / "defaults.toml"
        toml_path.write_text("""\
[email]
imap_server = "imap.test.com"
smtp_server = "smtp.test.com"
username = "test@test.com"
password = "pass"
""")
        loader = McpConfigLoader.from_path(toml_path)
        assert loader.config.email is not None
        assert loader.config.email.imap_port == 993
        assert loader.config.email.smtp_port == 587

    def test_custom_ports(self, mcp_toml: Path) -> None:
        mcp_toml.write_text("""\
[email]
imap_server = "imap.custom.com"
imap_port = 1993
smtp_server = "smtp.custom.com"
smtp_port = 2587
username = "u@c.com"
password = "p"
""")
        loader = McpConfigLoader.from_path(mcp_toml)
        assert loader.config.email.imap_port == 1993
        assert loader.config.email.smtp_port == 2587


# -- MCP servers dict building --


class TestBuildMcpServers:
    def test_builds_email_server(self, loader: McpConfigLoader) -> None:
        servers = loader.build_mcp_servers()
        assert "email" in servers
        assert servers["email"]["command"] == "python"
        assert servers["email"]["args"] == ["-m", "mcp_email_server", "stdio"]

    def test_email_env_vars(self, loader: McpConfigLoader) -> None:
        servers = loader.build_mcp_servers()
        env = servers["email"]["env"]
        assert env["MCP_EMAIL_SERVER_EMAIL_ADDRESS"] == "user@example.com"
        assert env["MCP_EMAIL_SERVER_PASSWORD"] == "secret123"
        assert env["MCP_EMAIL_SERVER_IMAP_HOST"] == "imap.example.com"
        assert env["MCP_EMAIL_SERVER_SMTP_HOST"] == "smtp.example.com"
        assert env["MCP_EMAIL_SERVER_IMAP_PORT"] == "993"
        assert env["MCP_EMAIL_SERVER_SMTP_PORT"] == "587"

    def test_no_email_no_servers(self, tmp_path: Path) -> None:
        missing = tmp_path / "no.toml"
        loader = McpConfigLoader.from_path(missing)
        servers = loader.build_mcp_servers()
        assert servers == {}

    def test_has_email_true(self, loader: McpConfigLoader) -> None:
        assert loader.has_email() is True

    def test_has_email_false(self, tmp_path: Path) -> None:
        loader = McpConfigLoader.from_path(tmp_path / "no.toml")
        assert loader.has_email() is False


# -- Model tests --


class TestModels:
    def test_email_mcp_config(self) -> None:
        cfg = EmailMcpConfig(
            imap_server="imap.test.com",
            smtp_server="smtp.test.com",
            username="test@test.com",
            password="secret",
        )
        assert cfg.imap_port == 993
        assert cfg.smtp_port == 587

    def test_mcp_config_no_email(self) -> None:
        cfg = McpConfig()
        assert cfg.email is None

    def test_mcp_config_with_email(self) -> None:
        email = EmailMcpConfig(
            imap_server="imap.x.com",
            smtp_server="smtp.x.com",
            username="a@b.com",
            password="pw",
        )
        cfg = McpConfig(email=email)
        assert cfg.email.username == "a@b.com"

    def test_constructor_direct(self) -> None:
        cfg = McpConfig()
        loader = McpConfigLoader(cfg)
        assert loader.config.email is None
        assert loader.build_mcp_servers() == {}
