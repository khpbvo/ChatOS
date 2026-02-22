"""Main agent orchestrator for ChatOS.

Wires the Claude Agent SDK client to the rules engine (PreToolUse)
and audit logger (PostToolUse) to create a permission-enforced,
fully-audited agent session with subagent delegation and structured
event streaming.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookContext,
    HookMatcher,
    PostToolUseHookInput,
    PreToolUseHookInput,
    ResultMessage,
    TextBlock,
)
from claude_agent_sdk.types import SyncHookJSONOutput

from .audit import AuditLogger
from .models import (
    Action,
    Decision,
    Event,
    MediaEvent,
    TextEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolCollapseEvent,
    ToolOutputEvent,
)
from .rules_engine import RulesEngine

if TYPE_CHECKING:
    from .agent_registry import AgentRegistry
    from .mcp_config import McpConfigLoader

ORCHESTRATOR_SYSTEM_PROMPT = """\
You are ChatOS, your personal computer assistant. You help the user do \
everything on their machine through this chat — browse the web, manage \
files, view photos and videos, send email, install apps, and keep the \
system running smoothly.

## What you can do
- **Files** — Browse, create, move, search, and organize files and folders.
- **Web** — Search the web, open pages, and summarize content.
- **Media** — View images, play audio/video, and manage media files.
- **Email** — Read, compose, and send email.
- **System** — Check disk space, manage apps, monitor performance, and \
handle updates.

You delegate tasks to specialist agents automatically — the user doesn't \
need to know which one handles what.

## Permissions
Some actions run immediately, some need your confirmation first, and a \
few are off-limits for safety.
- If something is **denied**, explain briefly and suggest an alternative.
- If something needs **confirmation**, describe what you're about to do \
and wait for a yes.
- Never try to work around the permission system.

## Style
- Be friendly, concise, and non-technical. Speak like a helpful assistant, \
not a sysadmin manual.
- When showing command output, keep it brief — highlight what matters.
- For multi-step tasks, give a quick overview before starting.
- If something goes wrong, explain what happened in plain language and \
offer a next step.
"""

MODEL_MAP: dict[str, str] = {
    "sonnet": "claude-sonnet-4-6",
}

ALLOWED_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]

# Max lines of tool output to include in ToolOutputEvent
MAX_OUTPUT_LINES = 25

# Pattern to detect media URLs in text
_MEDIA_URL_RE = re.compile(
    r"(https?://\S+\.(?:png|jpg|jpeg|gif|webp|svg|mp4|webm|mov|mp3|ogg|wav))\b",
    re.IGNORECASE,
)

# Pattern to detect local file paths with media extensions
_LOCAL_FILE_RE = re.compile(
    r"(/(?:home|tmp)/\S+\.(?:png|jpg|jpeg|gif|webp|svg|mp4|webm|mov|mp3|ogg|wav))\b",
    re.IGNORECASE,
)

_MEDIA_EXTENSIONS: dict[str, str] = {
    "mp4": "video", "webm": "video", "mov": "video",
    "mp3": "link", "ogg": "link", "wav": "link",
}


MediaType = Literal["image", "video", "link"]


def _classify_media_ext(ext: str) -> MediaType:
    """Classify a file extension into a media type: image, video, or link."""
    return _MEDIA_EXTENSIONS.get(ext.lower(), "image")  # type: ignore[return-value]


def _cap_output(text: str, max_lines: int = MAX_OUTPUT_LINES) -> tuple[str, bool]:
    """Cap text to max_lines. Returns (capped_text, was_truncated)."""
    lines = text.split("\n")
    if len(lines) <= max_lines:
        return text, False
    return "\n".join(lines[:max_lines]), True


class Orchestrator:
    """Permission-enforced agent session backed by the Claude Agent SDK."""

    def __init__(
        self,
        rules_engine: RulesEngine,
        audit_logger: AuditLogger,
        model: str = "sonnet",
        cwd: str | Path = "/usr/local/share/chatos",
        system_prompt: str = ORCHESTRATOR_SYSTEM_PROMPT,
        agent_registry: AgentRegistry | None = None,
        mcp_config: McpConfigLoader | None = None,
        file_server_prefix: str | None = None,
    ) -> None:
        self._rules = rules_engine
        self._audit = audit_logger
        self._model = MODEL_MAP.get(model, model)
        self._cwd = str(cwd)
        self._system_prompt = system_prompt
        self._agent_registry = agent_registry
        self._mcp_config = mcp_config
        self._file_server_prefix = file_server_prefix
        self._client: ClaudeSDKClient | None = None

    @property
    def client(self) -> ClaudeSDKClient | None:
        return self._client

    # -- Hook callbacks --

    async def pre_tool_use(
        self,
        hook_input: PreToolUseHookInput,
        matcher: str | None,
        ctx: HookContext,
    ) -> SyncHookJSONOutput:
        """PreToolUse hook: evaluate the tool call against the rules engine."""
        tool_name = hook_input["tool_name"]
        tool_input = hook_input["tool_input"]
        session_id = hook_input.get("session_id", "")

        decision = self._rules.check_tool_use(tool_name, tool_input)

        await self._audit.log_decision(
            tool_name=tool_name,
            tool_input=tool_input,
            decision=decision,
            session_id=session_id,
        )

        return self._decision_to_hook_output(decision)

    async def post_tool_use(
        self,
        hook_input: PostToolUseHookInput,
        matcher: str | None,
        ctx: HookContext,
    ) -> SyncHookJSONOutput:
        """PostToolUse hook: log the tool execution outcome."""
        tool_name = hook_input["tool_name"]
        tool_input = hook_input["tool_input"]
        tool_response = hook_input.get("tool_response", None)
        session_id = hook_input.get("session_id", "")

        is_error = isinstance(tool_response, dict) and tool_response.get("is_error", False)
        outcome = "error" if is_error else "success"
        error_msg = str(tool_response) if is_error else None

        await self._audit.log_outcome(
            tool_name=tool_name,
            tool_input=tool_input,
            outcome=outcome,
            session_id=session_id,
            error=error_msg,
        )

        return SyncHookJSONOutput()

    # -- SDK client lifecycle --

    def build_options(self) -> ClaudeAgentOptions:
        """Build the SDK client options with hooks wired up."""
        kwargs: dict = {
            "allowed_tools": ALLOWED_TOOLS,
            "model": self._model,
            "system_prompt": self._system_prompt,
            "cwd": self._cwd,
            "permission_mode": "bypassPermissions",
            "hooks": {
                "PreToolUse": [
                    HookMatcher(matcher=None, hooks=[self.pre_tool_use]),
                ],
                "PostToolUse": [
                    HookMatcher(matcher=None, hooks=[self.post_tool_use]),
                ],
            },
        }

        # Inject subagent definitions if registry is available
        if self._agent_registry is not None:
            agents = self._agent_registry.build_agent_definitions()
            if agents:
                kwargs["agents"] = agents

        # Inject MCP server configs if available
        if self._mcp_config is not None:
            mcp_servers = self._mcp_config.build_mcp_servers()
            if mcp_servers:
                kwargs["mcp_servers"] = mcp_servers

        return ClaudeAgentOptions(**kwargs)

    async def start(self, prompt: str | None = None) -> None:
        """Create and connect the SDK client."""
        options = self.build_options()
        self._client = ClaudeSDKClient(options)
        await self._client.connect(prompt=prompt)

    async def query(self, message: str) -> AsyncIterator[str]:
        """Send a user message and yield text response chunks.

        Convenience wrapper around query_events() for backward compatibility.
        Only yields text content (TextEvent.text).
        """
        if self._client is None:
            raise RuntimeError("Orchestrator not started — call start() first")

        async for event in self.query_events(message):
            if isinstance(event, TextEvent):
                yield event.text

    async def query_events(self, message: str) -> AsyncIterator[Event]:
        """Send a user message and yield structured Event objects.

        Maps SDK content blocks to ChatOS events:
        - ThinkingBlock → ThinkingEvent
        - ToolUseBlock → ToolCollapseEvent (previous) + ToolCallEvent
        - ToolResultBlock → ToolOutputEvent (capped at MAX_OUTPUT_LINES)
        - TextBlock → TextEvent or MediaEvent (if contains media URL)
        """
        if self._client is None:
            raise RuntimeError("Orchestrator not started — call start() first")

        self._client.query(message)

        last_tool_name: str | None = None

        async for msg in self._client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    block_type = getattr(block, "type", None)

                    if block_type == "thinking":
                        yield ThinkingEvent(text=getattr(block, "thinking", ""))

                    elif block_type == "tool_use":
                        # Collapse previous tool output if there was one
                        if last_tool_name is not None:
                            yield ToolCollapseEvent(tool_name=last_tool_name)

                        tool_name = getattr(block, "name", "unknown")
                        tool_input = getattr(block, "input", {})
                        last_tool_name = tool_name
                        yield ToolCallEvent(tool_name=tool_name, tool_input=tool_input)

                    elif block_type == "tool_result":
                        output_text = str(getattr(block, "content", ""))
                        capped, truncated = _cap_output(output_text)
                        yield ToolOutputEvent(
                            tool_name=last_tool_name or "unknown",
                            output=capped,
                            truncated=truncated,
                        )

                    elif isinstance(block, TextBlock):
                        text = block.text
                        # Check for HTTP media URLs
                        match = _MEDIA_URL_RE.search(text)
                        if match:
                            url = match.group(1)
                            ext = url.rsplit(".", 1)[-1].lower()
                            yield MediaEvent(
                                media_type=_classify_media_ext(ext), url=url,
                            )
                        elif self._file_server_prefix:
                            # Check for local file paths
                            local_match = _LOCAL_FILE_RE.search(text)
                            if local_match:
                                local_path = local_match.group(1)
                                ext = local_path.rsplit(".", 1)[-1].lower()
                                url = f"{self._file_server_prefix}/{local_path.lstrip('/')}"
                                yield MediaEvent(
                                    media_type=_classify_media_ext(ext), url=url,
                                )
                            else:
                                yield TextEvent(text=text)
                        else:
                            yield TextEvent(text=text)

            elif isinstance(msg, ResultMessage):
                # Collapse last tool if still open
                if last_tool_name is not None:
                    yield ToolCollapseEvent(tool_name=last_tool_name)
                    last_tool_name = None
                break

    async def stop(self) -> None:
        """Disconnect the SDK client."""
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    # -- Internal helpers --

    @staticmethod
    def _decision_to_hook_output(decision: Decision) -> SyncHookJSONOutput:
        """Convert a rules engine Decision to an SDK hook output."""
        match decision.action:
            case Action.ALLOW:
                return SyncHookJSONOutput(
                    hookSpecificOutput={
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "permissionDecisionReason": decision.reason,
                    },
                )
            case Action.DENY:
                return SyncHookJSONOutput(
                    decision="block",
                    reason=decision.reason,
                    hookSpecificOutput={
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": decision.reason,
                    },
                )
            case Action.CONFIRM:
                return SyncHookJSONOutput(
                    hookSpecificOutput={
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "ask",
                        "permissionDecisionReason": decision.reason,
                    },
                )
