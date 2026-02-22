# ChatOS — Build Plan & Milestones

This document tracks the implementation plan, completed milestones,
architecture decisions, and known issues.

## Build Phases

### Phase 1: Core Engine (CLI-testable, no UI) — COMPLETE

All steps complete. 184 tests passing.

- [x] **Step 1: rules_engine.py** — Parse rules.toml, match commands against patterns
  - Commit: `7624cea` — "Add rules engine with TOML parser and permission matching"
  - Files: `src/rules_engine.py`, `src/models.py`, `tests/test_rules_engine.py`
  - 48 unit tests

- [x] **Step 2: audit.py** — Structured JSON logging to /var/chatos/logs/
  - Commit: `43ef4c5` — "Add async audit logger with structured JSONL output"
  - Files: `src/audit.py`, `tests/test_audit.py`
  - Added `AuditEntry` model to `src/models.py`
  - 14 unit tests

- [x] **Step 3: orchestrator.py** — ClaudeSDKClient with PreToolUse/PostToolUse hooks
  - Commit: `3bb1c29` — "Add orchestrator with SDK hooks wired to rules engine and audit"
  - Files: `src/orchestrator.py`, `tests/test_orchestrator.py`
  - 23 unit tests

- [x] **Step 4: CLI test harness** — stdin/stdout REPL for terminal testing
  - Commit: `c89cc2e` — "Add CLI test harness for interactive agent testing"
  - Files: `src/cli.py`, `src/__main__.py`, `tests/test_cli.py`
  - 5 unit tests

- [x] **Step 5: Test suite** — Integration tests and exhaustive production rules coverage
  - Commit: `f40a521` — "Add integration tests and exhaustive production rules coverage"
  - Files: `tests/test_integration.py`
  - 94 integration tests (all prod patterns, security edge cases, pipeline tests)

### Phase 2: Subagents + Event Stream + System Prompt — COMPLETE

- [x] **Step 6: System prompt rewrite** — Reframe from sysadmin to end-user OS companion.
  Agent must be self-aware of its capabilities (files, web, media, mail, system).
  Informative but concise output style. Aware it runs on OpenBSD but the user doesn't
  need to know internals.
- [x] **Step 7: Subagent markdown files** — system.md, files.md, web.md, media.md, mail.md
  in `.claude/agents/`. Each defines a specialist agent with scoped system prompt.
- [x] **Step 8: agents.toml parser** — Load model config per agent from `etc/chatos/agents.toml`
- [x] **Step 9: Event stream protocol** — Replace raw text yielding in orchestrator with
  structured events: ThinkingEvent, ToolCallEvent, ToolOutputEvent (25-line cap),
  ToolCollapseEvent, TextEvent, MediaEvent. Both CLI and Web UI consume these.
- [x] **Step 10: MCP server config** — Parse `/etc/chatos/mcp.toml`, wire the email
  MCP server (`mcp-email-server`) into the SDK client for the mail subagent.
  Web search and web fetch use built-in tools (WebSearch, WebFetch), not MCP servers.
  Custom in-process MCP servers (chatos-files, chatos-media) are deferred to Phase 3.
- [x] **Step 11: Test subagent routing + event stream** — Verify orchestrator delegates
  to correct subagent and emits correct event types.

### Phase 3: Web UI + Kiosk — IN PROGRESS

- [x] **Step 12: ws_server.py** — WebSocket server bridging browser ↔ agent. Sends
  structured events (JSON) per the event stream protocol.
  - Files: `src/ws_server.py`, `src/models.py` (3 new models), `src/__main__.py`, `tests/test_ws_server.py`
  - 31 tests (lifecycle, protocol, errors, single-connection guard, new models)
- [x] **Step 13: Chat UI** — React + TypeScript + Vite chat interface in `ui/`.
  Connects to the WebSocket server (Step 12) and renders the event stream.
  - Files: `ui/` directory (22 files: package.json, tsconfig.json, vite.config.ts,
    index.html, src/types/events.ts, src/state/reducer.ts, src/hooks/useWebSocket.ts,
    src/hooks/useAutoScroll.ts, src/styles/variables.css, src/styles/global.css,
    src/components/*.tsx + *.css, src/App.tsx, src/main.tsx)
  - **Stack:** React 19, TypeScript 5.6, Vite 6, plain CSS (single target: Chromium kiosk)
  - **Dev:** `npm run dev` (Vite HMR) with WebSocket proxy to `ws://127.0.0.1:8400`
  - **Build:** `npm run build` → `ui/dist/` static files (served by `_chatos_ui` in Step 14)
  - **Note:** OpenBSD arm64 requires `@rollup/wasm-node` (npm override in package.json)
  - CSP-sandboxed iframe for on-demand web browsing (BrowserPanel, stretch goal)
- [x] **Step 14: File server** — HTTP file serving integrated into the WebSocket server
  via `process_request` hook. Serves local files from user home dir (session-token gated)
  and static UI from `ui/dist/`. Orchestrator detects local file paths and converts
  them to `/files/` URLs for inline rendering.
  - Files: `src/file_server.py` (new), `src/models.py`, `src/ws_server.py`,
    `src/orchestrator.py`, `ui/vite.config.ts`, `ui/src/types/events.ts`,
    `ui/src/state/reducer.ts`, `ui/src/hooks/useWebSocket.ts`,
    `ui/src/components/MediaMessage.tsx`, `ui/src/components/MessageList.tsx`,
    `ui/src/components/ChatPanel.tsx`, `ui/src/App.tsx`,
    `tests/test_file_server.py` (new), `tests/test_ws_server.py`, `tests/test_orchestrator.py`
  - 383 total tests (30 new in test_file_server, 13 new in test_orchestrator, 3 new in test_ws_server)
- [ ] **Step 15: Kiosk setup** — xenodm + chromium --kiosk auto-launch
- [ ] **Step 16: rc.d scripts** — OpenBSD service scripts for chatos_agent and chatos_ui

### Phase 4: Hardening — NOT STARTED

- [ ] **Step 17: pledge/unveil wrappers** — Python ctypes bindings for OpenBSD pledge() and unveil()
- [ ] **Step 18: Apply pledge/unveil** — Lock down each process
- [ ] **Step 19: Watchdog logic** — Monitor for unexpected behavior
- [ ] **Step 20: Installer script** — curl | sh that transforms a fresh OpenBSD into ChatOS

## Architecture Decisions

### AD-1: Whitelist-based permission model
All commands are denied by default. Only commands matching `safe_patterns` or
`confirm_patterns` are allowed. This is more restrictive but safer than a blacklist.

### AD-2: Substring matching for forbidden patterns
Forbidden patterns use `pattern in command` (substring match) to catch patterns
embedded in pipelines, subshells, and command chains. Safe/confirm patterns use
prefix matching with word-boundary awareness.

### AD-3: SDK bypassPermissions mode
We set `permission_mode="bypassPermissions"` on the SDK client so the SDK's
built-in permission system doesn't interfere. Our PreToolUse hooks are the sole
authority for permission decisions.

### AD-4: SyncHookJSONOutput for hooks
Hook callbacks return `SyncHookJSONOutput` (from `claude_agent_sdk.types`, NOT
the top-level package). The `hookSpecificOutput` dict maps our `Action` enum to
the SDK's `permissionDecision` values: `allow`/`deny`/`ask`.

### AD-5: Date-based JSONL audit logs
Audit entries are written as JSON Lines to `audit-YYYY-MM-DD.jsonl` files.
File I/O uses `asyncio.to_thread` to avoid blocking the event loop. Each write
opens/closes the file to ensure entries are flushed immediately.

### AD-6: tomllib over tomli
Python 3.12+ includes `tomllib` in the standard library. We use that instead of
the `tomli` backport package. No backport dependency is needed since we target
Python 3.12+ exclusively.

### AD-7: Claude account auth over API keys
The SDK spawns the Claude Code CLI as a subprocess. Authentication is handled
entirely by the CLI, not the SDK. We use `claude auth login` (interactive) or
`claude setup-token` (headless/kiosk) instead of ANTHROPIC_API_KEY. The _chatos
user authenticates once during initial setup via `doas -u _chatos claude setup-token`.
No env file or API key management is needed.

### AD-8: End-user OS framing, not sysadmin tool
ChatOS is an end-user operating system experience, not a sysadmin tool. The web
UI provides file management, web browsing, media viewing, email, and system
maintenance — all through natural language. The CLI remains the admin/dev
interface. The system prompt, subagents, and UX all reflect this distinction.

### AD-9: MCP credential storage in /etc/chatos/mcp.toml
MCP server credentials (IMAP passwords, etc.) are stored in `/etc/chatos/mcp.toml`,
owned by `root:_chatos` with mode `640`. This follows the standard OpenBSD pattern
for service credentials (same as smtpd, httpd, sshd). Root writes the file during
setup, `_chatos` reads it at runtime. No env files, no vaults.

### AD-10: CSP headers for iframe sandboxing
When the web UI opens a URL in an embedded iframe, CSP (Content-Security-Policy)
headers restrict what the iframe can load and execute. This prevents XSS, phishing,
and kiosk escape attempts. Default mode is chat-based URL summaries; iframe is
on-demand only.

### AD-11: Structured event stream protocol
The orchestrator emits structured events (ThinkingEvent, ToolCallEvent,
ToolOutputEvent, ToolCollapseEvent, TextEvent, MediaEvent) instead of raw text.
This enables the web UI's collapsing tool output UX: previous tool outputs
collapse to just name+args when a new tool is called, AI text stays on screen,
tool output is capped at 25 lines.

### AD-12: Built-in tools first, MCP only when necessary
The Claude Code CLI provides built-in tools (Bash, Read, Write, Edit, MultiEdit,
Glob, Grep, WebSearch, WebFetch) that require no configuration. ChatOS uses
these as the primary capability set. MCP servers are only added for capabilities
not covered by built-in tools — currently only email (`mcp-email-server` from
PyPI for IMAP/SMTP). Custom in-process SDK MCP servers (chatos-files,
chatos-media) will be added in Phase 3 for web UI rendering needs. End users
cannot add MCP servers — only the admin (via `/etc/chatos/mcp.toml`) controls
available capabilities. Prefer Python (PyPI) MCP servers over npm-based ones
to avoid a Node.js dependency on OpenBSD.

### AD-13: No offline mode
ChatOS requires an internet connection to function (Claude API access). No
degraded offline mode is planned. The target deployment has redundant
connectivity (fiber + 5G fallback).

### AD-14: Single-user now, multi-user later
The initial release is single-user (one person per machine, kiosk-style).
The architecture should not preclude adding multi-user support (accounts,
separate home dirs, session isolation) in a future phase.

### AD-15: Tool scoping per subagent
Each subagent receives only the built-in tools it needs via
`ClaudeAgentOptions.allowed_tools`. WebSearch and WebFetch are scoped to the
web subagent only (not available globally). The rules engine covers Bash
commands and Write/Edit paths. Web tools (WebSearch, WebFetch) are unfiltered
for now — domain blocking may be added in a future phase if needed.

### AD-16: Localhost-only WebSocket binding
The WebSocket server binds to `127.0.0.1` by default, not `0.0.0.0`. This
ensures the agent is only reachable from the local machine (kiosk browser).
Remote access requires an explicit `--host` override.

### AD-17: Single-connection guard
Only one WebSocket client can be connected at a time. A second connection
receives an `ErrorEvent(code="busy")` and is closed with code 4000. This
enforces the single-user kiosk model (AD-14) at the transport layer.

### AD-18: React + Vite for the kiosk UI
The chat UI uses React 19 + TypeScript + Vite. Node.js 22 and npm 11 are
available on the target machine. Vite provides HMR in development and
optimized static builds for production (`ui/dist/`). Plain CSS is used
instead of Tailwind or CSS-in-JS — the kiosk targets a single browser
(Chromium) so no compatibility layer is needed. State is managed with
`useReducer` (no external state library) since the scope is a single
chat session with streaming events.

### AD-19: Integrated HTTP file server via process_request
The HTTP file server is integrated into the existing WebSocket server on port 8400
using the `websockets` library's `process_request` hook. A single process serves
three things: `/ws` (WebSocket upgrade), `/files/*` (local files from the user's
home directory, session-token gated), and `/*` (static UI from `ui/dist/` in
production). Security: timing-safe token comparison via `secrets.compare_digest()`,
path traversal prevention via `Path.resolve()` + `relative_to()`, symlink escape
blocking, 100 MB max file size, restrictive CSP headers on file responses.

## Known Limitations

### KL-1: Forbidden pattern false positives
The substring-matching approach for forbidden patterns can produce false positives.
For example, the pattern `"passwd"` (targeting the `passwd` command) also matches
`wc -l /etc/passwd`. Documented in `test_known_false_positive_passwd_in_path`.
A future regex-based matcher could address this.

### KL-2: Shell redirect patterns need exact spacing
The forbidden patterns `">/etc/"` and `">> /etc/"` require exact string matches.
A command like `echo x > /etc/foo` (with spaces around `>`) won't match `">/etc/"`.
The current rules.toml handles common forms but edge cases exist.

### KL-3: No content-based write filtering
The `Write`/`Edit` tool checks only block the file path against
`forbidden_write_paths`. There is no inspection of the content being written.
Content-based filtering would require a separate mechanism.
