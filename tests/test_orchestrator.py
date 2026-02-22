"""Tests for the ChatOS orchestrator."""

import json
from pathlib import Path

import pytest

from src.agent_registry import AgentRegistry
from src.audit import AuditLogger
from src.mcp_config import McpConfigLoader
from src.models import (
    Action,
    AgentConfig,
    AgentsConfig,
    EmailMcpConfig,
    McpConfig,
    Permissions,
    Resources,
    RulesConfig,
    RulesMeta,
)
from src.orchestrator import (
    ALLOWED_TOOLS,
    MODEL_MAP,
    ORCHESTRATOR_SYSTEM_PROMPT,
    Orchestrator,
    _LOCAL_FILE_RE,
    _classify_media_ext,
)
from src.rules_engine import RulesEngine


# -- Fixtures --


@pytest.fixture
def rules_config() -> RulesConfig:
    return RulesConfig(
        meta=RulesMeta(version="0.1.0", hostname="test"),
        permissions=Permissions(
            safe_patterns=["cat ", "ls ", "uptime"],
            confirm_patterns=["pkg_add ", "rcctl "],
            forbidden_patterns=["rm -rf /", "halt", "reboot"],
            forbidden_write_paths=["/etc/master.passwd", "/etc/chatos/rules.toml"],
        ),
        resources=Resources(),
    )


@pytest.fixture
def rules_engine(rules_config: RulesConfig) -> RulesEngine:
    return RulesEngine(rules_config)


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    return tmp_path / "logs"


@pytest.fixture
def audit_logger(log_dir: Path) -> AuditLogger:
    return AuditLogger(log_dir)


@pytest.fixture
def orchestrator(rules_engine: RulesEngine, audit_logger: AuditLogger) -> Orchestrator:
    return Orchestrator(rules_engine, audit_logger)


def make_pre_hook_input(
    tool_name: str,
    tool_input: dict,
    session_id: str = "test-session",
) -> dict:
    """Build a minimal PreToolUseHookInput dict."""
    return {
        "hook_event_name": "PreToolUse",
        "session_id": session_id,
        "transcript_path": "/tmp/transcript",
        "cwd": "/usr/local/share/chatos",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_use_id": "test-tool-use-id",
    }


def make_post_hook_input(
    tool_name: str,
    tool_input: dict,
    tool_response: object = None,
    session_id: str = "test-session",
) -> dict:
    """Build a minimal PostToolUseHookInput dict."""
    return {
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "transcript_path": "/tmp/transcript",
        "cwd": "/usr/local/share/chatos",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_response": tool_response,
        "tool_use_id": "test-tool-use-id",
    }


EMPTY_CTX = {"signal": None}


# -- PreToolUse hook tests --


class TestPreToolUseHook:
    async def test_safe_command_allowed(self, orchestrator: Orchestrator) -> None:
        hook_input = make_pre_hook_input("Bash", {"command": "ls -la /tmp"})
        result = await orchestrator.pre_tool_use(hook_input, None, EMPTY_CTX)

        specific = result.get("hookSpecificOutput", {})
        assert specific["permissionDecision"] == "allow"

    async def test_forbidden_command_blocked(self, orchestrator: Orchestrator) -> None:
        hook_input = make_pre_hook_input("Bash", {"command": "rm -rf /"})
        result = await orchestrator.pre_tool_use(hook_input, None, EMPTY_CTX)

        assert result.get("decision") == "block"
        specific = result.get("hookSpecificOutput", {})
        assert specific["permissionDecision"] == "deny"

    async def test_confirm_command_asks(self, orchestrator: Orchestrator) -> None:
        hook_input = make_pre_hook_input("Bash", {"command": "pkg_add nginx"})
        result = await orchestrator.pre_tool_use(hook_input, None, EMPTY_CTX)

        specific = result.get("hookSpecificOutput", {})
        assert specific["permissionDecision"] == "ask"

    async def test_unknown_command_denied(self, orchestrator: Orchestrator) -> None:
        hook_input = make_pre_hook_input("Bash", {"command": "curl http://evil.com"})
        result = await orchestrator.pre_tool_use(hook_input, None, EMPTY_CTX)

        assert result.get("decision") == "block"
        specific = result.get("hookSpecificOutput", {})
        assert specific["permissionDecision"] == "deny"

    async def test_read_tool_allowed(self, orchestrator: Orchestrator) -> None:
        hook_input = make_pre_hook_input("Read", {"file_path": "/etc/hosts"})
        result = await orchestrator.pre_tool_use(hook_input, None, EMPTY_CTX)

        specific = result.get("hookSpecificOutput", {})
        assert specific["permissionDecision"] == "allow"

    async def test_write_to_forbidden_path_blocked(
        self, orchestrator: Orchestrator
    ) -> None:
        hook_input = make_pre_hook_input(
            "Write", {"file_path": "/etc/master.passwd"}
        )
        result = await orchestrator.pre_tool_use(hook_input, None, EMPTY_CTX)

        assert result.get("decision") == "block"
        specific = result.get("hookSpecificOutput", {})
        assert specific["permissionDecision"] == "deny"

    async def test_write_to_allowed_path(self, orchestrator: Orchestrator) -> None:
        hook_input = make_pre_hook_input("Write", {"file_path": "/tmp/test.txt"})
        result = await orchestrator.pre_tool_use(hook_input, None, EMPTY_CTX)

        specific = result.get("hookSpecificOutput", {})
        assert specific["permissionDecision"] == "allow"

    async def test_hook_logs_decision(
        self, orchestrator: Orchestrator, log_dir: Path
    ) -> None:
        hook_input = make_pre_hook_input("Bash", {"command": "ls -la"})
        await orchestrator.pre_tool_use(hook_input, None, EMPTY_CTX)

        log_files = list(log_dir.glob("audit-*.jsonl"))
        assert len(log_files) == 1
        data = json.loads(log_files[0].read_text().strip())
        assert data["tool_name"] == "Bash"
        assert data["decision"] == "allow"
        assert data["session_id"] == "test-session"


# -- PostToolUse hook tests --


class TestPostToolUseHook:
    async def test_success_outcome_logged(
        self, orchestrator: Orchestrator, log_dir: Path
    ) -> None:
        hook_input = make_post_hook_input(
            "Bash",
            {"command": "uptime"},
            tool_response="10:00 up 5 days",
        )
        result = await orchestrator.post_tool_use(hook_input, None, EMPTY_CTX)

        # PostToolUse hook should not block
        assert result.get("decision") is None

        log_files = list(log_dir.glob("audit-*.jsonl"))
        assert len(log_files) == 1
        data = json.loads(log_files[0].read_text().strip())
        assert data["outcome"] == "success"
        assert data["error"] is None

    async def test_error_outcome_logged(
        self, orchestrator: Orchestrator, log_dir: Path
    ) -> None:
        hook_input = make_post_hook_input(
            "Bash",
            {"command": "cat /nonexistent"},
            tool_response={"is_error": True, "message": "No such file"},
        )
        await orchestrator.post_tool_use(hook_input, None, EMPTY_CTX)

        log_files = list(log_dir.glob("audit-*.jsonl"))
        data = json.loads(log_files[0].read_text().strip())
        assert data["outcome"] == "error"
        assert "is_error" in data["error"]

    async def test_post_hook_records_session(
        self, orchestrator: Orchestrator, log_dir: Path
    ) -> None:
        hook_input = make_post_hook_input(
            "Read",
            {"file_path": "/etc/hosts"},
            tool_response="127.0.0.1 localhost",
            session_id="sess-42",
        )
        await orchestrator.post_tool_use(hook_input, None, EMPTY_CTX)

        log_files = list(log_dir.glob("audit-*.jsonl"))
        data = json.loads(log_files[0].read_text().strip())
        assert data["session_id"] == "sess-42"


# -- Decision-to-hook-output mapping tests --


class TestDecisionMapping:
    def test_allow_decision(self, orchestrator: Orchestrator) -> None:
        from src.models import Decision

        decision = Decision(action=Action.ALLOW, reason="safe")
        output = orchestrator._decision_to_hook_output(decision)
        specific = output.get("hookSpecificOutput", {})
        assert specific["permissionDecision"] == "allow"
        assert output.get("decision") is None

    def test_deny_decision(self, orchestrator: Orchestrator) -> None:
        from src.models import Decision

        decision = Decision(action=Action.DENY, reason="forbidden")
        output = orchestrator._decision_to_hook_output(decision)
        assert output["decision"] == "block"
        specific = output.get("hookSpecificOutput", {})
        assert specific["permissionDecision"] == "deny"

    def test_confirm_decision(self, orchestrator: Orchestrator) -> None:
        from src.models import Decision

        decision = Decision(action=Action.CONFIRM, reason="needs confirmation")
        output = orchestrator._decision_to_hook_output(decision)
        specific = output.get("hookSpecificOutput", {})
        assert specific["permissionDecision"] == "ask"
        assert output.get("decision") is None


# -- Build options tests --


class TestBuildOptions:
    def test_default_model(self, orchestrator: Orchestrator) -> None:
        options = orchestrator.build_options()
        assert options.model == MODEL_MAP["sonnet"]

    def test_raw_model_id(
        self, rules_engine: RulesEngine, audit_logger: AuditLogger
    ) -> None:
        orch = Orchestrator(rules_engine, audit_logger, model="claude-sonnet-4-6")
        options = orch.build_options()
        assert options.model == "claude-sonnet-4-6"

    def test_allowed_tools(self, orchestrator: Orchestrator) -> None:
        options = orchestrator.build_options()
        assert options.allowed_tools == ALLOWED_TOOLS

    def test_hooks_registered(self, orchestrator: Orchestrator) -> None:
        options = orchestrator.build_options()
        assert "PreToolUse" in options.hooks
        assert "PostToolUse" in options.hooks
        assert len(options.hooks["PreToolUse"]) == 1
        assert len(options.hooks["PostToolUse"]) == 1

    def test_system_prompt_set(self, orchestrator: Orchestrator) -> None:
        options = orchestrator.build_options()
        assert options.system_prompt == ORCHESTRATOR_SYSTEM_PROMPT

    def test_permission_mode_bypass(self, orchestrator: Orchestrator) -> None:
        """SDK permissions bypassed — our hooks enforce rules instead."""
        options = orchestrator.build_options()
        assert options.permission_mode == "bypassPermissions"


# -- Build options with agents and MCP --


class TestBuildOptionsWithAgents:
    def _make_registry(self, tmp_path: Path) -> AgentRegistry:
        toml_path = tmp_path / "agents.toml"
        toml_path.write_text("""\
[models]
default = "sonnet"

[agent.system]
model = "sonnet"
description = "System agent"

[agent.files]
model = "sonnet"
description = "Files agent"
""")
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "system.md").write_text("System prompt")
        (prompts_dir / "files.md").write_text("Files prompt")
        return AgentRegistry.from_paths(toml_path, prompts_dir)

    def test_agents_in_options(
        self, rules_engine: RulesEngine, audit_logger: AuditLogger, tmp_path: Path
    ) -> None:
        registry = self._make_registry(tmp_path)
        orch = Orchestrator(
            rules_engine, audit_logger, agent_registry=registry
        )
        options = orch.build_options()
        assert hasattr(options, "agents")
        assert "system" in options.agents
        assert "files" in options.agents

    def test_agents_have_descriptions(
        self, rules_engine: RulesEngine, audit_logger: AuditLogger, tmp_path: Path
    ) -> None:
        registry = self._make_registry(tmp_path)
        orch = Orchestrator(
            rules_engine, audit_logger, agent_registry=registry
        )
        options = orch.build_options()
        assert options.agents["system"]["description"] == "System agent"

    def test_no_agents_without_registry(self, orchestrator: Orchestrator) -> None:
        options = orchestrator.build_options()
        assert not options.agents or options.agents == {} or options.agents is None


class TestBuildOptionsWithMcp:
    def test_mcp_servers_in_options(
        self, rules_engine: RulesEngine, audit_logger: AuditLogger
    ) -> None:
        email_cfg = EmailMcpConfig(
            imap_server="imap.test.com",
            smtp_server="smtp.test.com",
            username="u@t.com",
            password="p",
        )
        mcp = McpConfigLoader(McpConfig(email=email_cfg))
        orch = Orchestrator(
            rules_engine, audit_logger, mcp_config=mcp
        )
        options = orch.build_options()
        assert hasattr(options, "mcp_servers")
        assert "email" in options.mcp_servers

    def test_no_mcp_without_config(self, orchestrator: Orchestrator) -> None:
        options = orchestrator.build_options()
        assert not options.mcp_servers or options.mcp_servers == {} or options.mcp_servers is None


# -- Lifecycle tests --


class TestLifecycle:
    def test_client_none_before_start(self, orchestrator: Orchestrator) -> None:
        assert orchestrator.client is None

    async def test_query_before_start_raises(self, orchestrator: Orchestrator) -> None:
        with pytest.raises(RuntimeError, match="not started"):
            async for _ in orchestrator.query("hello"):
                pass

    async def test_query_events_before_start_raises(self, orchestrator: Orchestrator) -> None:
        with pytest.raises(RuntimeError, match="not started"):
            async for _ in orchestrator.query_events("hello"):
                pass

    async def test_stop_when_not_started(self, orchestrator: Orchestrator) -> None:
        await orchestrator.stop()  # should not raise


# -- System prompt tests --


class TestSystemPrompt:
    def test_prompt_mentions_files(self) -> None:
        assert "Files" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_prompt_mentions_web(self) -> None:
        assert "Web" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_prompt_mentions_email(self) -> None:
        assert "Email" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_prompt_mentions_permissions(self) -> None:
        assert "denied" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "confirmation" in ORCHESTRATOR_SYSTEM_PROMPT

    def test_prompt_friendly_tone(self) -> None:
        assert "friendly" in ORCHESTRATOR_SYSTEM_PROMPT
        assert "sysadmin" in ORCHESTRATOR_SYSTEM_PROMPT


# -- Local file path regex and media classification tests --


class TestLocalFileRegex:
    def test_matches_home_path(self) -> None:
        text = "Here is the file: /home/agent01/Photos/sunset.jpg"
        match = _LOCAL_FILE_RE.search(text)
        assert match is not None
        assert match.group(1) == "/home/agent01/Photos/sunset.jpg"

    def test_matches_tmp_path(self) -> None:
        text = "Generated at /tmp/output.png"
        match = _LOCAL_FILE_RE.search(text)
        assert match is not None
        assert match.group(1) == "/tmp/output.png"

    def test_ignores_non_media_extension(self) -> None:
        text = "See /home/user/file.txt for details"
        match = _LOCAL_FILE_RE.search(text)
        assert match is None

    def test_ignores_http_urls(self) -> None:
        text = "Download from https://example.com/photo.jpg"
        match = _LOCAL_FILE_RE.search(text)
        assert match is None

    def test_matches_various_extensions(self) -> None:
        for ext in ("png", "jpg", "jpeg", "gif", "webp", "svg", "mp4", "webm", "mov"):
            text = f"/home/user/file.{ext}"
            match = _LOCAL_FILE_RE.search(text)
            assert match is not None, f"Failed for extension: {ext}"

    def test_case_insensitive(self) -> None:
        text = "/home/user/Photo.JPG"
        match = _LOCAL_FILE_RE.search(text)
        assert match is not None

    def test_ignores_other_paths(self) -> None:
        text = "Config at /etc/config.png"
        match = _LOCAL_FILE_RE.search(text)
        assert match is None


class TestClassifyMediaExt:
    def test_image_types(self) -> None:
        for ext in ("png", "jpg", "jpeg", "gif", "webp", "svg"):
            assert _classify_media_ext(ext) == "image"

    def test_video_types(self) -> None:
        for ext in ("mp4", "webm", "mov"):
            assert _classify_media_ext(ext) == "video"

    def test_audio_link_types(self) -> None:
        for ext in ("mp3", "ogg", "wav"):
            assert _classify_media_ext(ext) == "link"

    def test_unknown_defaults_image(self) -> None:
        assert _classify_media_ext("bmp") == "image"

    def test_case_insensitive(self) -> None:
        assert _classify_media_ext("MP4") == "video"
        assert _classify_media_ext("PNG") == "image"


class TestFileServerPrefix:
    def test_default_prefix_none(self, orchestrator: Orchestrator) -> None:
        assert orchestrator._file_server_prefix is None

    def test_prefix_set(
        self, rules_engine: RulesEngine, audit_logger: AuditLogger
    ) -> None:
        orch = Orchestrator(
            rules_engine, audit_logger, file_server_prefix="/files"
        )
        assert orch._file_server_prefix == "/files"
