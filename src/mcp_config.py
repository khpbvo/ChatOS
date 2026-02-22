"""MCP server configuration for ChatOS.

Parses /etc/chatos/mcp.toml to build mcp_servers dicts for the Claude
Agent SDK. If the file doesn't exist, no MCP servers are configured —
graceful degradation.
"""

import tomllib
from pathlib import Path

from .models import EmailMcpConfig, McpConfig


class McpConfigLoader:
    """Load MCP server configs from mcp.toml."""

    def __init__(self, config: McpConfig) -> None:
        self._config = config

    @classmethod
    def from_path(cls, path: Path) -> "McpConfigLoader":
        """Load MCP config from a TOML file.

        If the file doesn't exist, returns an empty config (no MCP servers).
        """
        if not path.is_file():
            return cls(McpConfig())

        with open(path, "rb") as f:
            raw = tomllib.load(f)

        email_cfg = None
        if "email" in raw:
            email_data = raw["email"]
            email_cfg = EmailMcpConfig(
                imap_server=email_data["imap_server"],
                imap_port=email_data.get("imap_port", 993),
                smtp_server=email_data["smtp_server"],
                smtp_port=email_data.get("smtp_port", 587),
                username=email_data["username"],
                password=email_data["password"],
            )

        return cls(McpConfig(email=email_cfg))

    @property
    def config(self) -> McpConfig:
        return self._config

    def build_mcp_servers(self) -> dict[str, dict]:
        """Build the mcp_servers dict for ClaudeAgentOptions."""
        servers: dict[str, dict] = {}

        if self._config.email:
            servers["email"] = {
                "command": "python",
                "args": ["-m", "mcp_email_server", "stdio"],
                "env": {
                    "MCP_EMAIL_SERVER_EMAIL_ADDRESS": self._config.email.username,
                    "MCP_EMAIL_SERVER_PASSWORD": self._config.email.password,
                    "MCP_EMAIL_SERVER_IMAP_HOST": self._config.email.imap_server,
                    "MCP_EMAIL_SERVER_IMAP_PORT": str(self._config.email.imap_port),
                    "MCP_EMAIL_SERVER_SMTP_HOST": self._config.email.smtp_server,
                    "MCP_EMAIL_SERVER_SMTP_PORT": str(self._config.email.smtp_port),
                },
            }

        return servers

    def has_email(self) -> bool:
        """Check if email MCP server is configured."""
        return self._config.email is not None
