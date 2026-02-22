"""Agent registry for ChatOS subagent management.

Parses agents.toml and loads system prompts from markdown files to build
AgentDefinition objects for the Claude Agent SDK.
"""

import tomllib
from pathlib import Path

from .models import AgentConfig, AgentsConfig
from .orchestrator import MODEL_MAP

# Tool sets scoped per subagent (from CLAUDE.md)
TOOL_SETS: dict[str, list[str]] = {
    "system": ["Bash", "Read", "Glob", "Grep"],
    "files": ["Bash", "Read", "Write", "Edit", "MultiEdit", "Glob", "Grep"],
    "web": ["Bash", "Read", "WebSearch", "WebFetch"],
    "media": ["Bash", "Read", "Glob"],
    "mail": ["Read"],  # + mcp__email__* added when mcp.toml provides creds
}

# Agents that are not subagents (excluded from AgentDefinition building)
NON_SUBAGENTS = {"orchestrator"}


class AgentRegistry:
    """Loads agent configs from TOML + system prompts from markdown files."""

    def __init__(
        self,
        config: AgentsConfig,
        prompts: dict[str, str],
    ) -> None:
        self._config = config
        self._prompts = prompts

    @classmethod
    def from_paths(cls, agents_toml: Path, prompts_dir: Path) -> "AgentRegistry":
        """Parse agents.toml and load .md prompts from prompts_dir."""
        with open(agents_toml, "rb") as f:
            raw = tomllib.load(f)

        default_model = raw.get("models", {}).get("default", "sonnet")

        agents: dict[str, AgentConfig] = {}
        for name, data in raw.get("agent", {}).items():
            agents[name] = AgentConfig(
                name=name,
                model=data.get("model", default_model),
                description=data.get("description", ""),
            )

        config = AgentsConfig(default_model=default_model, agents=agents)

        # Load markdown prompts for each subagent
        prompts: dict[str, str] = {}
        for name in agents:
            if name in NON_SUBAGENTS:
                continue
            md_path = prompts_dir / f"{name}.md"
            if md_path.is_file():
                prompts[name] = md_path.read_text()

        return cls(config, prompts)

    @property
    def config(self) -> AgentsConfig:
        return self._config

    @property
    def prompts(self) -> dict[str, str]:
        return self._prompts

    def build_agent_definitions(self) -> dict[str, dict]:
        """Build SDK AgentDefinition dict for ClaudeAgentOptions.agents.

        Returns a dict mapping agent name to its definition dict, ready
        to pass as ClaudeAgentOptions(agents=...).
        """
        definitions: dict[str, dict] = {}

        for name, agent_cfg in self._config.agents.items():
            if name in NON_SUBAGENTS:
                continue

            prompt = self._prompts.get(name, "")
            model = MODEL_MAP.get(agent_cfg.model, agent_cfg.model)
            tools = self.get_tool_set(name)

            definitions[name] = {
                "description": agent_cfg.description,
                "model": model,
                "instructions": prompt,
                "allowed_tools": tools,
            }

        return definitions

    def get_tool_set(self, agent_name: str) -> list[str]:
        """Return the allowed tools for a given agent."""
        return list(TOOL_SETS.get(agent_name, []))

    def agent_names(self) -> list[str]:
        """Return the list of subagent names (excluding orchestrator)."""
        return [n for n in self._config.agents if n not in NON_SUBAGENTS]
