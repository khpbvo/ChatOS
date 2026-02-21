"""CLI test harness for the ChatOS orchestrator.

A simple stdin/stdout REPL for testing the agent from the terminal.

Usage:
    python -m src.cli [--rules PATH] [--log-dir PATH]

Environment:
    ANTHROPIC_API_KEY  — Required. Can also be loaded from /etc/chatos/env.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .audit import AuditLogger, DEFAULT_LOG_DIR
from .orchestrator import Orchestrator
from .rules_engine import RulesEngine, DEFAULT_RULES_PATH

# Development fallback: use project-local rules if system rules don't exist
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEV_RULES_PATH = PROJECT_ROOT / "etc" / "chatos" / "rules.toml"
ENV_FILE = Path("/etc/chatos/env")

BANNER = """\
ChatOS v0.1.0 — AI-driven system administration for OpenBSD
Type your message, or "exit" to quit. Ctrl+C to interrupt.
"""


def load_env_file(path: Path) -> None:
    """Source key=value pairs from a file into os.environ."""
    if not path.is_file():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


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
                async for chunk in orchestrator.query(user_input):
                    print(chunk, end="", flush=True)
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

    # Load API key from env file if present
    load_env_file(ENV_FILE)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "Error: ANTHROPIC_API_KEY not set. "
            "Export it or add it to /etc/chatos/env.",
            file=sys.stderr,
        )
        sys.exit(1)

    rules_path = resolve_rules_path(args.rules)
    print(f"Loading rules from: {rules_path}", file=sys.stderr)

    rules_engine = RulesEngine.from_file(rules_path)

    log_dir = Path(args.log_dir) if args.log_dir else DEFAULT_LOG_DIR
    audit_logger = AuditLogger(log_dir)
    print(f"Audit logs: {audit_logger.log_dir}", file=sys.stderr)

    orchestrator = Orchestrator(
        rules_engine=rules_engine,
        audit_logger=audit_logger,
        model=args.model,
        cwd=args.cwd,
    )

    asyncio.run(repl(orchestrator))


if __name__ == "__main__":
    main()
