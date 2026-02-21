"""Main agent orchestrator for ChatOS.

Wires the Claude Agent SDK client to the rules engine (PreToolUse)
and audit logger (PostToolUse) to create a permission-enforced,
fully-audited agent session.
"""

from collections.abc import AsyncIterator
from pathlib import Path

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
from .models import Action, Decision
from .rules_engine import RulesEngine

ORCHESTRATOR_SYSTEM_PROMPT = """\
You are ChatOS, an AI system administrator for an OpenBSD machine.
The user interacts with you through a chat interface instead of a traditional shell.
You perform system administration tasks on their behalf.

## Environment
- Operating system: OpenBSD (current release, amd64)
- Shell: /bin/ksh (POSIX-compatible)
- Package manager: pkg_add / pkg_delete / pkg_info
- Service manager: rcctl
- Firewall: pf (packet filter)
- Privilege escalation: doas (not sudo)
- No /proc filesystem — use sysctl for system info

## Rules
- A permission system controls what you can do. Some commands run freely, \
some require user confirmation, and some are forbidden.
- If a command is denied, explain why and suggest alternatives.
- If a command requires confirmation, tell the user what you intend to do \
and wait for their approval.
- Never attempt to bypass the permission system.

## Style
- Be concise and direct.
- Show command output when relevant.
- Warn before destructive operations.
- When multiple steps are needed, outline the plan first.
"""

MODEL_MAP: dict[str, str] = {
    "sonnet": "claude-sonnet-4-6",
}

ALLOWED_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]


class Orchestrator:
    """Permission-enforced agent session backed by the Claude Agent SDK."""

    def __init__(
        self,
        rules_engine: RulesEngine,
        audit_logger: AuditLogger,
        model: str = "sonnet",
        cwd: str | Path = "/usr/local/share/chatos",
        system_prompt: str = ORCHESTRATOR_SYSTEM_PROMPT,
    ) -> None:
        self._rules = rules_engine
        self._audit = audit_logger
        self._model = MODEL_MAP.get(model, model)
        self._cwd = str(cwd)
        self._system_prompt = system_prompt
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
        return ClaudeAgentOptions(
            allowed_tools=ALLOWED_TOOLS,
            model=self._model,
            system_prompt=self._system_prompt,
            cwd=self._cwd,
            permission_mode="bypassPermissions",
            hooks={
                "PreToolUse": [
                    HookMatcher(matcher=None, hooks=[self.pre_tool_use]),
                ],
                "PostToolUse": [
                    HookMatcher(matcher=None, hooks=[self.post_tool_use]),
                ],
            },
        )

    async def start(self, prompt: str | None = None) -> None:
        """Create and connect the SDK client."""
        options = self.build_options()
        self._client = ClaudeSDKClient(options)
        await self._client.connect(prompt=prompt)

    async def query(self, message: str) -> AsyncIterator[str]:
        """Send a user message and yield text response chunks."""
        if self._client is None:
            raise RuntimeError("Orchestrator not started — call start() first")

        self._client.query(message)

        async for msg in self._client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        yield block.text
            elif isinstance(msg, ResultMessage):
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
