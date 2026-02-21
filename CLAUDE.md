# ChatOS — Project Memory

This file is the canonical reference for Claude Code working on this project.
Read this ENTIRELY before making any changes.
See `Docs/Planning.md` for build phases, milestones, and architecture decisions.

## What Is ChatOS?

ChatOS is an AI-driven operating system experience for OpenBSD, delivered
through a kiosk web browser. The user interacts with their machine entirely
through a chat interface — browsing the web, managing files, viewing media,
sending email, installing apps, and performing system maintenance — all via
natural language conversation with an AI agent backed by Claude.

Two interfaces exist:
- **Web UI** (kiosk browser): The end-user experience. Rich, visual, streaming.
- **CLI** (terminal): Developer/admin interface for configuration and debugging.

## Core Principles

1. **Security first, always.** pledge() and unveil() are the outer ring. Agent SDK hooks are the inner ring.
2. **Every tool call passes through PreToolUse hooks** that enforce rules.toml.
3. **The rules file is sacred.** Only root can modify /etc/chatos/rules.toml.
4. **Separation of concerns.** _chatos_ui serves the web UI. _chatos runs the agent. They communicate via WebSocket.
5. **Audit everything.** Every operation gets logged to /var/chatos/logs/.

## Development Quick Start

```bash
# Run tests (always do this before committing)
.venv/bin/python -m pytest tests/ -v

# Run the CLI test harness (requires `claude auth login` or ANTHROPIC_API_KEY)
.venv/bin/python -m src --rules etc/chatos/rules.toml --log-dir /tmp/chatos-logs

# CLI flags: --rules PATH, --log-dir PATH, --model sonnet, --cwd PATH
```

## Current File Layout

```
/usr/local/share/chatos/project/   # Project root (git repo)
├── src/
│   ├── __init__.py                 # Package init (v0.1.0)
│   ├── __main__.py                 # `python -m src` entrypoint
│   ├── models.py                   # Pydantic models (Action, Decision, AuditEntry, RulesConfig, ...)
│   ├── rules_engine.py             # TOML parser + pattern matcher (RulesEngine class)
│   ├── audit.py                    # Async JSONL audit logger (AuditLogger class)
│   ├── orchestrator.py             # SDK client wrapper with hooks (Orchestrator class)
│   ├── cli.py                      # CLI REPL test harness
│   └── tools/                      # Custom MCP tools (placeholder)
│       └── __init__.py
├── tests/
│   ├── test_rules_engine.py        # 48 tests — pattern matching, TOML loading
│   ├── test_audit.py               # 14 tests — JSONL writing, date files
│   ├── test_orchestrator.py        # 23 tests — hooks, decision mapping, options
│   ├── test_cli.py                 # 5 tests — rules resolution, arg parsing
│   └── test_integration.py         # 94 tests — full pipeline, prod rules, security edge cases
├── etc/chatos/
│   ├── rules.toml                  # Permission patterns (safe/confirm/forbidden)
│   ├── agents.toml                 # Agent definitions (system, files, web, media, mail)
│   └── mcp.toml                    # MCP server configs + credentials (Phase 2)
├── Docs/
│   └── Planning.md                 # Build plan, milestones, architecture decisions
├── .claude/                        # Agent SDK config (placeholders)
│   ├── agents/                     # Subagent definitions: system, files, web, media, mail
│   ├── skills/
│   └── commands/
├── ui/                             # Kiosk web interface (Phase 3)
├── .venv/                          # Python 3.12 virtual environment
├── pyproject.toml                  # Project config and dependencies
└── CLAUDE.md                       # This file
```

## Target Layout (Production)

```
/etc/chatos/                        # Config (root-owned)
├── rules.toml                      # Permission patterns (root:_chatos 640)
├── agents.toml                     # Agent/model config
├── mcp.toml                        # MCP server configs + credentials (root:_chatos 640)
├── kiosk.conf                      # Kiosk browser settings

/usr/local/share/chatos/            # Application (owned by _chatos)
├── venv/, src/, ui/, .claude/

/var/chatos/                        # Runtime data
├── logs/                           # Audit JSONL files (audit-YYYY-MM-DD.jsonl)
├── run/                            # Unix sockets
└── sessions/                       # Session state
```

## Claude Agent SDK — Actual API Reference

The SDK is `claude-agent-sdk` (PyPI), installed in `.venv/`.
Version 0.1.39 as of Phase 1 completion.

### How to Discover SDK Patterns

The SDK types are defined in `claude_agent_sdk.types`. To explore:

```python
# List all exports
.venv/bin/python -c "import claude_agent_sdk; print(dir(claude_agent_sdk))"

# Inspect a specific type (source code)
.venv/bin/python -c "import inspect; from claude_agent_sdk.types import SyncHookJSONOutput; print(inspect.getsource(SyncHookJSONOutput))"

# Check a class signature
.venv/bin/python -c "import inspect; from claude_agent_sdk import ClaudeAgentOptions; print(inspect.signature(ClaudeAgentOptions.__init__))"
```

### Key Types and Import Paths

```python
# Top-level imports (these work)
from claude_agent_sdk import (
    ClaudeAgentOptions,     # Dataclass — client configuration
    ClaudeSDKClient,        # Main client — connect(), query(), receive_response()
    HookMatcher,            # Routes hooks by tool name pattern (matcher=None matches all)
    AssistantMessage,       # Agent response with content blocks
    ResultMessage,          # Turn-complete signal with cost/usage info
    TextBlock,              # Text content within AssistantMessage
    PreToolUseHookInput,    # TypedDict — hook receives this before tool runs
    PostToolUseHookInput,   # TypedDict — hook receives this after tool runs
    HookContext,            # TypedDict — {"signal": Any | None}
)

# NOT in top-level — must import from .types
from claude_agent_sdk.types import SyncHookJSONOutput  # TypedDict — hook return value
```

### Hook Callback Signature

```python
async def my_hook(
    hook_input: PreToolUseHookInput,  # or PostToolUseHookInput
    matcher: str | None,              # the matcher pattern that triggered this hook
    ctx: HookContext,                 # {"signal": None} (reserved for future use)
) -> SyncHookJSONOutput:
    ...
```

### PreToolUseHookInput Fields (TypedDict)

```python
{
    "session_id": str,
    "transcript_path": str,
    "cwd": str,
    "permission_mode": str,         # NotRequired
    "hook_event_name": "PreToolUse",
    "tool_name": str,               # "Bash", "Write", "Edit", "Read", etc.
    "tool_input": dict[str, Any],   # {"command": "ls"} or {"file_path": "/tmp/x"}
    "tool_use_id": str,
}
```

### PostToolUseHookInput Fields (TypedDict)

Same as PreToolUse plus:
```python
{
    "hook_event_name": "PostToolUse",
    "tool_response": Any,           # The tool's output
}
```

### SyncHookJSONOutput — What Hooks Return

```python
# Allow a tool call:
SyncHookJSONOutput(
    hookSpecificOutput={
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",         # "allow" | "deny" | "ask"
        "permissionDecisionReason": "...",
    },
)

# Deny a tool call:
SyncHookJSONOutput(
    decision="block",
    reason="...",
    hookSpecificOutput={
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": "...",
    },
)

# Request user confirmation:
SyncHookJSONOutput(
    hookSpecificOutput={
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": "...",
    },
)
```

### ClaudeSDKClient Lifecycle

```python
client = ClaudeSDKClient(options)
await client.connect(prompt="optional initial message")
client.query("user message")
async for msg in client.receive_response():
    if isinstance(msg, AssistantMessage):
        for block in msg.content:
            if isinstance(block, TextBlock):
                print(block.text)
    elif isinstance(msg, ResultMessage):
        break
await client.disconnect()
```

## Authentication

The SDK spawns the Claude Code CLI as a subprocess. Auth is handled by the CLI,
not by the SDK itself. **No API key is needed** — we use Claude account login.

### How It Works

1. The CLI stores OAuth session tokens locally after `claude auth login`.
2. The SDK subprocess inherits those tokens — no env vars required.
3. `ClaudeAgentOptions.env` can still pass env vars if needed (e.g. for overrides).

### Auth Methods (priority order)

| Method | Command | Use Case |
|--------|---------|----------|
| **Claude account (OAuth)** | `claude auth login` | Interactive dev/admin |
| **Long-lived token** | `claude setup-token` | Headless/kiosk (production) |
| **SSO** | `claude auth login --sso` | Enterprise/org accounts |

### Production Setup (_chatos user)

The `_chatos` user has `/sbin/nologin` — authenticate during initial setup:
```bash
doas -u _chatos claude setup-token   # stores persistent token for headless use
```

### Checking Auth Status

```bash
claude auth status --json
# Returns: authMethod, apiProvider, email, subscriptionType, etc.
```

### SDK Error Handling

`AssistantMessage.error` can be `"authentication_failed"` if the CLI cannot
authenticate. The orchestrator should handle this gracefully.

## MCP Servers (Pre-configured Set)

ChatOS ships with a curated set of MCP servers that provide the agent's
extended capabilities. End users cannot add their own — the admin configures
them in `/etc/chatos/mcp.toml`.

| MCP Server | Purpose | Credentials |
|------------|---------|-------------|
| **Web search** | Internet search for the web agent | None (uses Claude's built-in) |
| **Web fetch** | Fetch/render URLs, link previews | None |
| **IMAP/SMTP** | Email read/send for the mail agent | IMAP/SMTP server, user, password |
| **File server** | Serve local files to the browser UI | None (localhost only) |

### Credential Storage

MCP server credentials live in `/etc/chatos/mcp.toml`:
- Owned by `root:_chatos`, mode `640` (root writes, `_chatos` reads)
- This is the standard OpenBSD pattern (same as smtpd, httpd, sshd)
- No env files, no vaults — just file permissions

```toml
# /etc/chatos/mcp.toml — example
[mail]
imap_server = "imap.example.com"
imap_port = 993
smtp_server = "smtp.example.com"
smtp_port = 587
username = "user@example.com"
password = "app-specific-password"
```

## Subagents

Subagents are specialist agents that the orchestrator delegates to. Each has a
focused system prompt and capability set. Defined in `.claude/agents/`.

| Agent | Role | Key Capabilities |
|-------|------|------------------|
| **system** | Machine health + maintenance | Disk space, updates, services, network status, performance |
| **files** | File management | Browse, create, organize, search, upload/download |
| **web** | Web browsing + search | Fetch URLs, summarize pages, signal UI to open iframe |
| **media** | Images, video, audio | Render images inline, video previews with links, audio playback |
| **mail** | Email | Read inbox, compose, send, search (via IMAP/SMTP MCP) |

## Web UI Architecture

### Event Stream Protocol

The orchestrator yields structured events (not raw text) over WebSocket:

```
ThinkingEvent          → animated spinner in UI
ToolCallEvent          → tool_name + args displayed
ToolOutputEvent        → 25-line preview of output, streaming
ToolCollapseEvent      → previous tool output collapses to name+args only
TextEvent              → AI response text (stays on screen)
MediaEvent             → image/video/link rendered inline
```

**UX flow:** User input → Thinking... (animated) → tool_name: args + 25-line
preview → if another tool is called, previous collapses → AI text output stays.

### Iframe Browsing

When the user asks to "open" a URL, the UI can open it in an embedded iframe
alongside the chat. Security:
- **CSP headers** restrict what the iframe can load and execute
- Default is chat-based summaries; iframe is on-demand ("open this in browser")

### File Serving

`_chatos_ui` serves local files (images, documents) to the browser via HTTP.
- Only serves from the user's home directory
- Requires the active session token
- Localhost-only binding

## Permission System (rules.toml)

Three tiers: **safe** (allow immediately) → **confirm** (ask user) → **forbidden** (deny always).
Plus `forbidden_write_paths` for Write/Edit tool calls.

**Evaluation order** (whitelist approach — unmatched = denied):
1. Forbidden patterns (substring match in full command) → deny
2. Safe patterns (prefix match with word boundary) → allow
3. Confirm patterns (prefix match with word boundary) → confirm
4. Default → deny

**Pattern matching details:**
- Forbidden: `pattern in command` — catches embedded patterns in pipes, chains, subshells
- Safe/Confirm: `_prefix_match(command, pattern)` — strips trailing space from pattern,
  checks `command == stripped` or `command.startswith(stripped + " ")`.
  Patterns with trailing space (like `"cat "`) also match via `startswith(pattern)`.

## Claude Models

All agents use a single model:

| Use | Model ID | Alias |
|-----|----------|-------|
| All agents | claude-sonnet-4-6 | sonnet |

Model map is in `src/orchestrator.py:MODEL_MAP`.

## System Users

| User | Purpose | Shell |
|------|---------|-------|
| agent01 | Human admin | /bin/ksh |
| _chatos | Agent process (SDK) | /sbin/nologin |
| _chatos_ui | Kiosk browser + web server | /sbin/nologin |

## Coding Standards

- **Python 3.12+** — match statements, modern typing (`str | None` not `Optional[str]`)
- **Type hints everywhere** — all function signatures and return types
- **Pydantic models** — for all structured data
- **async/await** — the entire stack is async
- **Tests** — every module gets a test file. Use pytest + pytest-asyncio. `asyncio_mode = "auto"` in pyproject.toml.
- **No hardcoded paths** — use constants or config, make paths configurable
- **No hardcoded secrets** — auth via `claude auth login` (account) or `claude setup-token` (headless)
- **Line length** — 100 chars (ruff config in pyproject.toml)

## OpenBSD Notes

- Shell is **ksh**, not bash. Scripts must be POSIX-compatible.
- Package manager: **pkg_add / pkg_delete / pkg_info** (not apt/yum).
- Service manager: **rcctl** (not systemd).
- Firewall: **pf** (packet filter), config at /etc/pf.conf.
- No /proc. System info via **sysctl**.
- **doas** replaces sudo. Config at /etc/doas.conf.
- Linux binaries won't work (different ELF ABI). Use OpenBSD packages.
- _chatos has /sbin/nologin — use `doas -u _chatos` to run as that user.
