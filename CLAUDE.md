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

# Run the WebSocket server
.venv/bin/python -m src --serve --port 8400 --rules etc/chatos/rules.toml --log-dir /tmp/chatos-logs

# Run the WebSocket server with file serving + static UI
.venv/bin/python -m src --serve --port 8400 --rules etc/chatos/rules.toml --log-dir /tmp/chatos-logs --home-dir /home/agent01 --static-dir ui/dist

# Run the UI dev server (separate terminal, proxies WS to :8400)
cd ui && npm run dev

# Export kiosk config as shell variables
.venv/bin/python -m src.kiosk_config etc/chatos/kiosk.conf

# CLI flags: --rules PATH, --log-dir PATH, --model sonnet, --cwd PATH
# WS server flags: --serve, --host HOST, --port PORT, --home-dir PATH, --static-dir PATH (plus CLI flags above)
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
│   ├── file_server.py              # HTTP file server (local files + static UI)
│   ├── kiosk_config.py             # Kiosk TOML parser + Chromium flag builder + shell exporter
│   ├── sandbox.py                  # pledge(2)/unveil(2) ctypes bindings (Sandbox builder)
│   ├── cli.py                      # CLI REPL test harness
│   ├── ws_server.py                # WebSocket server + HTTP file server for kiosk browser
│   └── tools/                      # Custom MCP tools (placeholder)
│       └── __init__.py
├── tests/
│   ├── test_rules_engine.py        # 48 tests — pattern matching, TOML loading
│   ├── test_audit.py               # 14 tests — JSONL writing, date files
│   ├── test_orchestrator.py        # 48 tests — hooks, decision mapping, options, local file regex
│   ├── test_cli.py                 # 5 tests — rules resolution, arg parsing
│   ├── test_integration.py         # 94 tests — full pipeline, prod rules, security edge cases
│   ├── test_ws_server.py           # 34 tests — WebSocket server, protocol, single-conn guard, session token
│   ├── test_file_server.py        # 40 tests — HTTP file server, path validation, token auth, MIME, static
│   ├── test_kiosk_config.py       # 29 tests — file loading, Chromium flags, shell export, models
│   ├── test_rc_scripts.py         # 45 tests — rc.d structure, pexp patterns, paths, rc.conf
│   └── test_sandbox.py            # 52 tests — pledge/unveil bindings, builder, state guards, subprocess
├── etc/chatos/
│   ├── rules.toml                  # Permission patterns (safe/confirm/forbidden)
│   ├── agents.toml                 # Agent definitions (system, files, web, media, mail)
│   ├── mcp.toml                    # MCP server configs + credentials (Phase 2)
│   └── kiosk.conf                  # Kiosk browser settings (URL, display, Chromium flags)
├── deploy/
│   ├── kiosk/                      # Kiosk launch scripts (Step 15)
│   │   ├── launch-kiosk.sh         # Entry point: DRI perms, ulimit, doas → xinit
│   │   ├── xinitrc                 # X session: xset, wait for server, exec Chromium
│   │   └── reset-console.sh        # Cleanup: restore DRI/console ownership
│   └── rc.d/                       # OpenBSD service scripts (Step 16)
│       ├── chatos_agent            # rc.d script: agent WebSocket server
│       ├── chatos_ui               # rc.d script: kiosk browser
│       └── rc.conf.local.example   # Example /etc/rc.conf.local entries
├── Docs/
│   └── Planning.md                 # Build plan, milestones, architecture decisions
├── .claude/                        # Agent SDK config (placeholders)
│   ├── agents/                     # Subagent definitions: system, files, web, media, mail
│   ├── skills/
│   └── commands/
├── ui/                             # Kiosk web interface (React + Vite + TypeScript)
│   ├── index.html                  # Vite entry HTML
│   ├── package.json                # Node deps + @rollup/wasm-node override for OpenBSD arm64
│   ├── vite.config.ts              # Vite config (WS proxy in dev)
│   ├── tsconfig.json               # TypeScript config (ES2022, strict, react-jsx)
│   └── src/
│       ├── main.tsx                # ReactDOM.createRoot entry point
│       ├── App.tsx                 # useReducer + useWebSocket wiring
│       ├── types/events.ts         # TypeScript mirrors of Python Event models
│       ├── state/reducer.ts        # ChatState, ChatAction, chatReducer
│       ├── hooks/
│       │   ├── useWebSocket.ts     # WS connect, reconnect, event→action mapping
│       │   └── useAutoScroll.ts    # Smart auto-scroll (skip if user scrolled up)
│       ├── styles/
│       │   ├── variables.css       # CSS custom properties (dark theme)
│       │   └── global.css          # Reset, body, root layout
│       └── components/             # Chat UI components (*.tsx + *.css)
│           ├── ChatPanel.tsx       # Layout: ConnectionStatus + MessageList + InputBar
│           ├── MessageList.tsx     # Scrollable list, renders ChatItem[]
│           ├── InputBar.tsx        # Text input + send button
│           ├── ConnectionStatus.tsx # Green/yellow/red dot indicator
│           ├── UserMessage.tsx     # Right-aligned user bubble
│           ├── ThinkingIndicator.tsx # Animated dots spinner
│           ├── ToolCallMessage.tsx # Tool name+args, collapsible output
│           ├── TextMessage.tsx     # AI response text
│           ├── MediaMessage.tsx    # Inline image/video/link
│           └── ErrorMessage.tsx    # Red error box with code
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

## Built-in Tools (from Claude Code CLI)

The Claude Agent SDK spawns the Claude Code CLI, which provides these tools
natively — no MCP servers needed. Tools are scoped per subagent via the
`allowed_tools` parameter on `ClaudeAgentOptions`.

### Core Tools (available to all agents)

| Tool | Description |
|------|-------------|
| **Bash** | Execute shell commands. Subject to rules.toml permission checks. |
| **Read** | Read files (text, images, PDFs, notebooks). |
| **Write** | Create/overwrite files. Subject to forbidden_write_paths. |
| **Edit** | Find-and-replace in files. Subject to forbidden_write_paths. |
| **MultiEdit** | Batch find-and-replace (multiple edits, one file, atomic). |
| **Glob** | Fast file pattern matching (e.g. `**/*.py`). |
| **Grep** | Content search via ripgrep (regex, file type filtering). |

### Web Tools (scoped to web subagent only)

| Tool | Description |
|------|-------------|
| **WebSearch** | Web search — returns results with links. No API key needed. |
| **WebFetch** | Fetch URL, convert HTML to markdown. 15-min cache. |

### Other Available Tools

| Tool | Description | Notes |
|------|-------------|-------|
| **LSP** | Language Server Protocol (go-to-definition, references, hover) | Requires LSP server config |
| **NotebookEdit** | Edit Jupyter notebook cells | If needed for data workflows |
| **Task** | Spawn a sub-agent for complex tasks | Used by orchestrator for subagent delegation |

### Tool Scoping per Subagent

Each subagent receives only the tools it needs via `ClaudeAgentOptions.allowed_tools`:

```python
TOOL_SETS = {
    "system":  ["Bash", "Read", "Glob", "Grep"],
    "files":   ["Bash", "Read", "Write", "Edit", "MultiEdit", "Glob", "Grep"],
    "web":     ["Bash", "Read", "WebSearch", "WebFetch"],
    "media":   ["Bash", "Read", "Glob"],            # + custom MCP tools (Phase 3)
    "mail":    ["Read"],                             # + mcp__email__* tools
}
```

## MCP Servers

ChatOS uses MCP servers **only** for capabilities not covered by built-in tools.
End users cannot add MCP servers — the admin configures them in
`/etc/chatos/mcp.toml`.

### External MCP Servers (subprocess, stdio transport)

| MCP Server | PyPI Package | Agent | Purpose |
|------------|-------------|-------|---------|
| **email** | `mcp-email-server` | mail | IMAP read + SMTP send. Credentials from mcp.toml. |

### Custom SDK MCP Servers (in-process, Phase 3)

| Server | Agent | Purpose |
|--------|-------|---------|
| **chatos-files** | files | Directory trees, file previews for web UI |
| **chatos-media** | media | Media metadata, base64 encoding for inline rendering |

### Wiring MCP Servers into the SDK

```python
from claude_agent_sdk import ClaudeAgentOptions

options = ClaudeAgentOptions(
    mcp_servers={
        "email": {
            "command": "python",
            "args": ["-m", "mcp_email_server", "stdio"],
            "env": {
                "MCP_EMAIL_SERVER_EMAIL_ADDRESS": creds["username"],
                "MCP_EMAIL_SERVER_PASSWORD": creds["password"],
                "MCP_EMAIL_SERVER_IMAP_HOST": creds["imap_server"],
                "MCP_EMAIL_SERVER_SMTP_HOST": creds["smtp_server"],
            },
        },
    },
    allowed_tools=["Read", "mcp__email__*"],
)
```

MCP tools follow the naming convention `mcp__<server-name>__<tool-name>`.
Use wildcards (`mcp__email__*`) in `allowed_tools` to allow all tools from a server.

### Credential Storage

MCP server credentials live in `/etc/chatos/mcp.toml`:
- Owned by `root:_chatos`, mode `640` (root writes, `_chatos` reads)
- This is the standard OpenBSD pattern (same as smtpd, httpd, sshd)
- No env files, no vaults — just file permissions

```toml
# /etc/chatos/mcp.toml — example
[email]
imap_server = "imap.example.com"
imap_port = 993
smtp_server = "smtp.example.com"
smtp_port = 587
username = "user@example.com"
password = "app-specific-password"
```

## Subagents

Subagents are specialist agents that the orchestrator delegates to. Each has a
focused system prompt, scoped tool set, and optional MCP servers. Defined in
`.claude/agents/`.

| Agent | Role | Built-in Tools | MCP Servers |
|-------|------|---------------|-------------|
| **system** | Machine health + maintenance | Bash, Read, Glob, Grep | — |
| **files** | File management | Bash, Read, Write, Edit, MultiEdit, Glob, Grep | chatos-files (Phase 3) |
| **web** | Web browsing + search | Bash, Read, WebSearch, WebFetch | — |
| **media** | Images, video, audio | Bash, Read, Glob | chatos-media (Phase 3) |
| **mail** | Email | Read | email (mcp-email-server) |

## Web UI Architecture

### Stack

**React 19 + TypeScript + Vite** in `ui/`. Plain CSS (single target: Chromium kiosk).
State managed with `useReducer` — no external state library.

- **Dev:** `cd ui && npm run dev` — Vite dev server with HMR, proxies WebSocket to `:8400`
- **Build:** `cd ui && npm run build` → `ui/dist/` static files
- **Production:** `_chatos_ui` serves `ui/dist/` to the kiosk browser

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

All agents (orchestrator and subagents) use a single model. Per-agent model
config lives in `etc/chatos/agents.toml` but currently every agent is set to
the same value. This allows future per-agent overrides without code changes.

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
