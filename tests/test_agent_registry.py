"""Tests for the ChatOS agent registry."""

from pathlib import Path

import pytest

from src.agent_registry import TOOL_SETS, NON_SUBAGENTS, AgentRegistry
from src.models import AgentConfig, AgentsConfig


# -- Fixtures --


@pytest.fixture
def agents_toml(tmp_path: Path) -> Path:
    """Write a valid agents.toml to a temp dir."""
    toml_path = tmp_path / "agents.toml"
    toml_path.write_text("""\
[models]
default = "sonnet"

[agent.orchestrator]
model = "sonnet"
description = "Main routing agent"

[agent.system]
model = "sonnet"
description = "Machine health and maintenance"

[agent.files]
model = "sonnet"
description = "File management"

[agent.web]
model = "sonnet"
description = "Web browsing and search"

[agent.media]
model = "sonnet"
description = "Media handling"

[agent.mail]
model = "sonnet"
description = "Email"
""")
    return toml_path


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    """Create a prompts directory with markdown files for each subagent."""
    d = tmp_path / "agents"
    d.mkdir()
    for name in ("system", "files", "web", "media", "mail"):
        (d / f"{name}.md").write_text(f"You are the **{name}** agent.")
    return d


@pytest.fixture
def registry(agents_toml: Path, prompts_dir: Path) -> AgentRegistry:
    return AgentRegistry.from_paths(agents_toml, prompts_dir)


# -- TOML parsing tests --


class TestTOMLParsing:
    def test_loads_default_model(self, registry: AgentRegistry) -> None:
        assert registry.config.default_model == "sonnet"

    def test_loads_all_agents(self, registry: AgentRegistry) -> None:
        names = set(registry.config.agents.keys())
        assert names == {"orchestrator", "system", "files", "web", "media", "mail"}

    def test_agent_has_description(self, registry: AgentRegistry) -> None:
        assert registry.config.agents["system"].description == "Machine health and maintenance"

    def test_agent_has_model(self, registry: AgentRegistry) -> None:
        assert registry.config.agents["files"].model == "sonnet"

    def test_orchestrator_excluded_from_subagents(self, registry: AgentRegistry) -> None:
        assert "orchestrator" not in registry.agent_names()

    def test_all_subagents_listed(self, registry: AgentRegistry) -> None:
        names = set(registry.agent_names())
        assert names == {"system", "files", "web", "media", "mail"}


# -- Prompt loading tests --


class TestPromptLoading:
    def test_loads_all_prompts(self, registry: AgentRegistry) -> None:
        assert len(registry.prompts) == 5
        for name in ("system", "files", "web", "media", "mail"):
            assert name in registry.prompts

    def test_prompt_content(self, registry: AgentRegistry) -> None:
        assert "**system** agent" in registry.prompts["system"]

    def test_missing_prompt_file(self, agents_toml: Path, tmp_path: Path) -> None:
        """Missing .md file means agent has no prompt but doesn't crash."""
        empty_dir = tmp_path / "empty_prompts"
        empty_dir.mkdir()
        reg = AgentRegistry.from_paths(agents_toml, empty_dir)
        assert len(reg.prompts) == 0

    def test_orchestrator_prompt_not_loaded(
        self, agents_toml: Path, prompts_dir: Path
    ) -> None:
        """Orchestrator is a non-subagent, so its prompt isn't loaded even if it exists."""
        (prompts_dir / "orchestrator.md").write_text("Orchestrator prompt")
        reg = AgentRegistry.from_paths(agents_toml, prompts_dir)
        assert "orchestrator" not in reg.prompts


# -- AgentDefinition building tests --


class TestBuildAgentDefinitions:
    def test_builds_five_definitions(self, registry: AgentRegistry) -> None:
        defs = registry.build_agent_definitions()
        assert len(defs) == 5

    def test_orchestrator_not_in_definitions(self, registry: AgentRegistry) -> None:
        defs = registry.build_agent_definitions()
        assert "orchestrator" not in defs

    def test_definition_has_description(self, registry: AgentRegistry) -> None:
        defs = registry.build_agent_definitions()
        assert defs["system"]["description"] == "Machine health and maintenance"

    def test_definition_has_model(self, registry: AgentRegistry) -> None:
        defs = registry.build_agent_definitions()
        assert defs["files"]["model"] == "claude-sonnet-4-6"

    def test_definition_has_instructions(self, registry: AgentRegistry) -> None:
        defs = registry.build_agent_definitions()
        assert "**files** agent" in defs["files"]["instructions"]

    def test_definition_has_allowed_tools(self, registry: AgentRegistry) -> None:
        defs = registry.build_agent_definitions()
        assert defs["system"]["allowed_tools"] == ["Bash", "Read", "Glob", "Grep"]

    def test_web_agent_tools(self, registry: AgentRegistry) -> None:
        defs = registry.build_agent_definitions()
        assert "WebSearch" in defs["web"]["allowed_tools"]
        assert "WebFetch" in defs["web"]["allowed_tools"]

    def test_mail_agent_tools(self, registry: AgentRegistry) -> None:
        defs = registry.build_agent_definitions()
        assert defs["mail"]["allowed_tools"] == ["Read"]

    def test_empty_prompt_for_missing_md(self, agents_toml: Path, tmp_path: Path) -> None:
        """Agent with no .md file gets empty instructions."""
        empty_dir = tmp_path / "no_prompts"
        empty_dir.mkdir()
        reg = AgentRegistry.from_paths(agents_toml, empty_dir)
        defs = reg.build_agent_definitions()
        assert defs["system"]["instructions"] == ""


# -- Tool set tests --


class TestToolSets:
    def test_system_tools(self, registry: AgentRegistry) -> None:
        assert registry.get_tool_set("system") == ["Bash", "Read", "Glob", "Grep"]

    def test_files_tools(self, registry: AgentRegistry) -> None:
        tools = registry.get_tool_set("files")
        assert "Write" in tools
        assert "Edit" in tools
        assert "MultiEdit" in tools

    def test_web_tools(self, registry: AgentRegistry) -> None:
        tools = registry.get_tool_set("web")
        assert "WebSearch" in tools
        assert "WebFetch" in tools

    def test_media_tools(self, registry: AgentRegistry) -> None:
        assert registry.get_tool_set("media") == ["Bash", "Read", "Glob"]

    def test_mail_tools(self, registry: AgentRegistry) -> None:
        assert registry.get_tool_set("mail") == ["Read"]

    def test_unknown_agent_returns_empty(self, registry: AgentRegistry) -> None:
        assert registry.get_tool_set("unknown") == []

    def test_tool_sets_constant_complete(self) -> None:
        """All expected agents have tool set entries."""
        expected = {"system", "files", "web", "media", "mail"}
        assert set(TOOL_SETS.keys()) == expected

    def test_tool_sets_are_lists_not_references(self, registry: AgentRegistry) -> None:
        """get_tool_set returns a copy, not a reference to the constant."""
        tools = registry.get_tool_set("system")
        tools.append("EXTRA")
        assert "EXTRA" not in TOOL_SETS["system"]


# -- Model override tests --


class TestModelOverride:
    def test_custom_model_override(self, prompts_dir: Path, tmp_path: Path) -> None:
        toml_path = tmp_path / "custom.toml"
        toml_path.write_text("""\
[models]
default = "sonnet"

[agent.system]
model = "claude-custom-model"
description = "Custom model agent"
""")
        reg = AgentRegistry.from_paths(toml_path, prompts_dir)
        defs = reg.build_agent_definitions()
        # Unknown model passes through as-is
        assert defs["system"]["model"] == "claude-custom-model"

    def test_inherits_default_model(self, prompts_dir: Path, tmp_path: Path) -> None:
        toml_path = tmp_path / "default_model.toml"
        toml_path.write_text("""\
[models]
default = "sonnet"

[agent.system]
description = "No model specified"
""")
        reg = AgentRegistry.from_paths(toml_path, prompts_dir)
        assert reg.config.agents["system"].model == "sonnet"


# -- Constructor tests --


class TestConstructor:
    def test_from_config_and_prompts(self) -> None:
        config = AgentsConfig(
            default_model="sonnet",
            agents={"test": AgentConfig(name="test", description="Test agent")},
        )
        reg = AgentRegistry(config, {"test": "You are test."})
        assert reg.agent_names() == ["test"]
        assert reg.prompts["test"] == "You are test."

    def test_non_subagents_constant(self) -> None:
        assert "orchestrator" in NON_SUBAGENTS
