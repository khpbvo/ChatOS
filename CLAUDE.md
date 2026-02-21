# ChatOS — Project Memory

This file is the canonical reference for Claude Code working on this project.
Read this ENTIRELY before making any changes.

## What Is ChatOS?

ChatOS is an AI-driven operating system interface for OpenBSD. Instead of a traditional shell or desktop, the user boots into a kiosk web browser showing a chat interface. All system administration happens through natural language conversation with an AI agent backed by Claude.

The user says "install nginx and configure a reverse proxy to port 3000" and the system does it — with proper permission checks, confirmation prompts for dangerous operations, and audit logging.

## Core Principles

1. **Security first, always.** OpenBSD was chosen for a reason. Every component runs with minimum privileges. pledge() and unveil() are the outer security ring. Agent SDK hooks are the inner ring.
2. **The AI never touches the system directly without permission checks.** Every tool call passes through PreToolUse hooks that enforce rules.toml.
3. **The rules file is sacred.** Only root can modify /etc/chatos/rules.toml. The agent user (_chatos) can read it but never write to it.
4. **Separation of concerns.** The UI user (_chatos_ui) serves the web interface. The agent user (_chatos) runs the Claude Agent SDK. They communicate via Unix domain socket or WebSocket.
5. **Audit everything.** Every operation, whether allowed or denied, gets logged to /var/chatos/logs/.

## Target Environment

- **OS:** OpenBSD (current release, amd64)
- **Python:** 3.12.x (system package)
- **Node.js:** OpenBSD package (required for Claude Code CLI via npm)
- **Hardware:** Development on VMware Fusion VM (2 CPU, 4GB RAM, M1 host). Production target is bare metal.
- **Display:** xenodm + Chromium in kiosk mode for the chat UI
- **Network:** Bridged networking, outbound HTTPS to Claude API

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Chromium Kiosk (--kiosk mode)       [_chatos_ui]        │
│  Serves: /usr/local/share/chatos/ui/                     │
│  Connects to: ws://localhost:8765                         │
├──────────────────────────────────────────────────────────┤
│  WebSocket Server (Python)           [_chatos_ui]        │
│  Bridges browser <-> agent via UDS                        │
├──────────────────────────────────────────────────────────┤
│  Agent Orchestrator (Claude Agent SDK) [_chatos]         │
│  - PreToolUse hooks enforce rules.toml                   │
│  - PostToolUse hooks log all operations                  │
│  - Subagents for specialist domains                      │
│  - Custom MCP tools for ChatOS-specific operations       │
├──────────────────────────────────────────────────────────┤
│  OpenBSD Kernel                                          │
│  pledge() / unveil() / W^X / ASLR / arc4random          │
└──────────────────────────────────────────────────────────┘
```

## Agent SDK Integration

We use the **Claude Agent SDK (Python)** — `claude-agent-sdk` package.
Installed in venv at: `/usr/local/share/chatos/venv/`

### Key SDK Features We Use

- **PreToolUse hooks:** Intercept every tool call (Bash, Write, Edit, etc.) BEFORE execution. Our hook reads rules.toml and allows/denies/requires-confirmation.
- **PostToolUse hooks:** Log every operation outcome for audit trail.
- **Subagents:** Specialist agents defined as markdown files in `.claude/agents/`. Each has restricted tool access and focused system prompts.
- **Custom tools via MCP:** In-process MCP servers for ChatOS-specific operations (e.g., user confirmation flow, session management).
- **Permission modes:** Main orchestrator runs in `default` mode. Individual subagents get restricted tool lists.
- **ClaudeSDKClient:** For bidirectional, interactive conversations (not one-shot queries).

### SDK Usage Pattern

```python
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, HookMatcher

options = ClaudeAgentOptions(
    allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep"],
    hooks={
        "PreToolUse": [
            HookMatcher(matcher="Bash", hooks=[check_bash_rules]),
            HookMatcher(matcher="Write|Edit", hooks=[check_write_rules]),
        ],
        "PostToolUse": [
            HookMatcher(matcher=None, hooks=[audit_log]),  # log everything
        ],
    },
    system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
    cwd="/usr/local/share/chatos",
)
```

## Models

- **Orchestrator:** claude-sonnet-4-5-20250929 (Sonnet 4.5) — fast, cost-effective for routing and standard operations
- **Security/Networking subagents:** claude-opus-4-6 (Opus 4.6) — complex reasoning for security decisions and network analysis
- **Simple subagents (fs listing, diagnostics):** Sonnet 4.5 or Haiku

## Permission System (rules.toml)

The rules file at `/etc/chatos/rules.toml` defines three tiers:

1. **safe_patterns** — Execute immediately, no confirmation needed (read-only operations, system status)
2. **confirm_patterns** — Require explicit user confirmation via the chat UI before execution
3. **forbidden_patterns** — NEVER execute, regardless of user request. Hook returns deny immediately.

Additionally:
- **forbidden_write_paths** — Paths the agent can never write to (/etc/master.passwd, /etc/doas.conf, /bsd, etc.)
- **resources** — Limits on concurrent operations, session timeouts

The rules engine is implemented as a PreToolUse hook. It:
1. Extracts the command/path from the tool input
2. Checks against forbidden_patterns first (deny)
3. Checks against forbidden_write_paths for write operations (deny)
4. Checks against safe_patterns (allow)
5. Checks against confirm_patterns (request user confirmation)
6. Default: deny with explanation (whitelist approach)

## System Users

| User | Purpose | Home | Shell |
|------|---------|------|-------|
| agent01 | Human admin account | /home/agent01 | /bin/ksh |
| _chatos | Agent process, runs SDK | /home/chatos | /sbin/nologin |
| _chatos_ui | Kiosk browser + web server | /home/chatos-ui | /sbin/nologin |

## Directory Layout

```
/etc/chatos/                    # Config (root-owned)
├── rules.toml                  # Permission rules (root:_chatos 640)
├── agents.toml                 # Model and agent config
├── env                         # API key (_chatos:_chatos 400)
└── kiosk.conf                  # Browser/UI config

/usr/local/share/chatos/        # Project root
├── venv/                       # Python virtual environment
├── src/                        # Application source
│   ├── orchestrator.py          # Main agent loop + hooks
│   ├── rules_engine.py          # TOML rules parser + matcher
│   ├── ws_server.py             # WebSocket bridge
│   ├── audit.py                 # Audit logging
│   ├── models.py                # Pydantic models
│   └── tools/                   # Custom MCP tools
│       ├── confirm.py           # User confirmation flow
│       └── session.py           # Session management
├── ui/                          # Kiosk web interface
│   ├── index.html
│   ├── chat.js
│   └── style.css
├── .claude/                     # Agent SDK config
│   ├── agents/                  # Subagent definitions
│   │   ├── filesystem.md
│   │   ├── packages.md
│   │   ├── services.md
│   │   ├── networking.md
│   │   └── diagnostics.md
│   ├── skills/                  # Agent skills
│   └── commands/                # Slash commands
└── CLAUDE.md                    # This file (project memory)

/var/chatos/                     # Runtime data
├── logs/                        # Audit logs
├── run/                         # Unix sockets
└── sessions/                    # Session state
```

## Build Order

This is the implementation sequence. Each step should be a working, testable increment:

### Phase 1: Core Engine (CLI-testable, no UI)
1. **rules_engine.py** — Parse rules.toml, match commands against patterns, return allow/deny/confirm decisions
2. **audit.py** — Structured JSON logging to /var/chatos/logs/
3. **orchestrator.py** — ClaudeSDKClient with PreToolUse/PostToolUse hooks wired to rules engine and audit
4. **CLI test harness** — Simple stdin/stdout loop to test the agent from the terminal
5. **Test suite** — Unit tests for rules engine, integration tests for hook behavior

### Phase 2: Subagents
6. **Subagent markdown files** — filesystem.md, packages.md, diagnostics.md, services.md, networking.md
7. **agents.toml parser** — Load model config per agent
8. **Test subagent routing** — Verify orchestrator delegates correctly

### Phase 3: Web UI + Kiosk
9. **ws_server.py** — WebSocket server bridging browser to agent
10. **Chat UI** — Minimal HTML/JS/CSS chat interface
11. **Kiosk setup** — xenodm + chromium --kiosk auto-launch
12. **rc.d scripts** — OpenBSD service scripts for chatos_agent and chatos_ui

### Phase 4: Hardening
13. **pledge/unveil wrappers** — Python ctypes bindings for OpenBSD pledge() and unveil()
14. **Apply pledge/unveil** — Lock down each process
15. **Watchdog logic** — Monitor for unexpected behavior
16. **Installer script** — curl | sh that transforms a fresh OpenBSD into ChatOS

## Coding Standards

- **Python 3.12+** — Use modern typing, dataclasses, match statements where appropriate
- **PEP 8** — Strict compliance
- **Type hints everywhere** — All function signatures, return types
- **Google-style docstrings** — Concise but complete
- **Pydantic models** — For all structured data (rules, messages, audit entries)
- **Context managers** — For all resources (files, sockets, sessions)
- **No hardcoded secrets** — API keys from /etc/chatos/env only
- **No hardcoded paths** — Use constants or config, make paths configurable
- **async/await** — The SDK is async, so the entire stack should be async
- **Tests** — Every module gets a test file. Use pytest + pytest-asyncio.

## OpenBSD-Specific Notes

- Shell is ksh, not bash. Shell scripts must be POSIX-compatible or explicitly use /bin/ksh.
- Package manager is pkg_add / pkg_delete / pkg_info (NOT apt, yum, pacman).
- Service management is rcctl (NOT systemd, NOT systemctl).
- Firewall is pf (packet filter), config at /etc/pf.conf.
- No /proc filesystem by default. System info via sysctl.
- The `doas` command replaces `sudo`. Config at /etc/doas.conf.
- Native binaries compiled for Linux will NOT work (different ELF ABI). Always use OpenBSD packages or compile from source/ports.
- Rust is available via pkg_add for packages that need compilation (e.g., pydantic-core).

## Important Reminders for Claude Code

- You are running ON the OpenBSD box. Use OpenBSD commands, not Linux equivalents.
- The project venv is at /usr/local/share/chatos/venv/ — activate it before running Python.
- The API key is in /etc/chatos/env — source it before running the agent.
- Always test changes before committing. Run the test suite.
- When creating rc.d scripts, follow OpenBSD rc.d(8) conventions exactly.
- The _chatos user has /sbin/nologin — you cannot su to it. Use doas -u _chatos to run commands as that user.
- Keep security in mind with every change. If in doubt, deny by default.
