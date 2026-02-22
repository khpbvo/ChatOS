"""CLI test harness for the ChatOS orchestrator.

A simple stdin/stdout REPL for testing the agent from the terminal.

Usage:
    python -m src.cli [--rules PATH] [--log-dir PATH]

Authentication:
    Uses Claude account login (`claude auth login`) or `claude setup-token`.
    No API key required — the SDK delegates auth to the Claude Code CLI.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .agent_registry import AgentRegistry
from .audit import AuditLogger, DEFAULT_LOG_DIR
from .mcp_config import McpConfigLoader
from .models import (
    MediaEvent,
    TextEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolCollapseEvent,
    ToolOutputEvent,
)
from .orchestrator import Orchestrator
from .rules_engine import RulesEngine, DEFAULT_RULES_PATH

# Development fallback: use project-local rules if system rules don't exist
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEV_RULES_PATH = PROJECT_ROOT / "etc" / "chatos" / "rules.toml"
DEV_AGENTS_TOML = PROJECT_ROOT / "etc" / "chatos" / "agents.toml"
DEV_PROMPTS_DIR = PROJECT_ROOT / ".claude" / "agents"
DEV_MCP_TOML = PROJECT_ROOT / "etc" / "chatos" / "mcp.toml"

BANNER = """\
ChatOS v0.1.0 — AI-driven operating system interface for OpenBSD
Type your message, or "exit" to quit. Ctrl+C to interrupt.
"""


def resolve_rules_path(explicit: str | None) -> Path:
    """Determine which rules.toml to use."""
    if explicit:
        return Path(explicit)
    if DEFAULT_RULES_PATH.is_file():
        return DEFAULT_RULES_PATH
    if DEV_RULES_PATH.is_file():
        return DEV_RULES_PATH
    print(f"Error: No rules.toml found at {DEFAULT_RULES_PATH} or {DEV_RULES_PATH}", file=sys.stderr)
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ChatOS CLI test harness")
    parser.add_argument(
        "--rules",
        type=str,
        default=None,
        help=f"Path to rules.toml (default: {DEFAULT_RULES_PATH})",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default=None,
        help=f"Audit log directory (default: {DEFAULT_LOG_DIR})",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="sonnet",
        help="Model name or ID (default: sonnet)",
    )
    parser.add_argument(
        "--cwd",
        type=str,
        default="/usr/local/share/chatos",
        help="Working directory for the agent",
    )
    return parser.parse_args()


def _render_tool_input(tool_input: dict) -> str:
    """Render tool input as a compact summary for CLI display."""
    if "command" in tool_input:
        return tool_input["command"]
    if "file_path" in tool_input:
        return tool_input["file_path"]
    return json.dumps(tool_input, separators=(",", ":"))


async def repl(orchestrator: Orchestrator) -> None:
    """Run the read-eval-print loop."""
    print(BANNER)

    try:
        await orchestrator.start()
    except Exception as e:
        print(f"Error starting orchestrator: {e}", file=sys.stderr)
        return

    try:
        while True:
            try:
                user_input = input("\n> ").strip()
            except EOFError:
                break

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                break

            try:
                async for event in orchestrator.query_events(user_input):
                    match event:
                        case ThinkingEvent():
                            print("[Thinking...]", flush=True)
                        case ToolCallEvent():
                            summary = _render_tool_input(event.tool_input)
                            print(f"  {event.tool_name}: {summary}", flush=True)
                        case ToolOutputEvent():
                            if event.output:
                                print(event.output, flush=True)
                            if event.truncated:
                                print("  ... (output truncated)", flush=True)
                        case ToolCollapseEvent():
                            pass  # No-op in CLI (meaningful in web UI)
                        case TextEvent():
                            print(event.text, end="", flush=True)
                        case MediaEvent():
                            print(f"[Media: {event.url}]", flush=True)
                print()  # newline after response
            except Exception as e:
                print(f"\nError: {e}", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        await orchestrator.stop()
        print("Goodbye.")


def main() -> None:
    args = parse_args()

    rules_path = resolve_rules_path(args.rules)
    print(f"Loading rules from: {rules_path}", file=sys.stderr)

    rules_engine = RulesEngine.from_file(rules_path)

    log_dir = Path(args.log_dir) if args.log_dir else DEFAULT_LOG_DIR
    audit_logger = AuditLogger(log_dir)
    print(f"Audit logs: {audit_logger.log_dir}", file=sys.stderr)

    # Load agent registry (optional — graceful if agents.toml missing)
    agent_registry = None
    agents_toml = DEV_AGENTS_TOML
    if agents_toml.is_file():
        agent_registry = AgentRegistry.from_paths(agents_toml, DEV_PROMPTS_DIR)
        print(f"Loaded agents: {', '.join(agent_registry.agent_names())}", file=sys.stderr)

    # Load MCP config (optional — graceful if mcp.toml missing)
    mcp_config = McpConfigLoader.from_path(DEV_MCP_TOML)
    if mcp_config.has_email():
        print("Email MCP server configured", file=sys.stderr)

    orchestrator = Orchestrator(
        rules_engine=rules_engine,
        audit_logger=audit_logger,
        model=args.model,
        cwd=args.cwd,
        agent_registry=agent_registry,
        mcp_config=mcp_config,
    )

    asyncio.run(repl(orchestrator))


if __name__ == "__main__":
    main()
