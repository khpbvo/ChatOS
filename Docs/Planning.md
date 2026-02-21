# ChatOS — Build Plan & Milestones

This document tracks the implementation plan, completed milestones,
architecture decisions, and known issues.

## Build Phases

### Phase 1: Core Engine (CLI-testable, no UI) — COMPLETE

All steps complete. 189 tests passing.

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
  - 24 unit tests

- [x] **Step 4: CLI test harness** — stdin/stdout REPL for terminal testing
  - Commit: `c89cc2e` — "Add CLI test harness for interactive agent testing"
  - Files: `src/cli.py`, `src/__main__.py`, `tests/test_cli.py`
  - 9 unit tests

- [x] **Step 5: Test suite** — Integration tests and exhaustive production rules coverage
  - Commit: `f40a521` — "Add integration tests and exhaustive production rules coverage"
  - Files: `tests/test_integration.py`
  - 94 integration tests (all prod patterns, security edge cases, pipeline tests)

### Phase 2: Subagents — NOT STARTED

- [ ] **Step 6: Subagent markdown files** — filesystem.md, packages.md, diagnostics.md, services.md, networking.md in `.claude/agents/`
- [ ] **Step 7: agents.toml parser** — Load model config per agent from `etc/chatos/agents.toml`
- [ ] **Step 8: Test subagent routing** — Verify orchestrator delegates to correct subagent

### Phase 3: Web UI + Kiosk — NOT STARTED

- [ ] **Step 9: ws_server.py** — WebSocket server bridging browser ↔ agent
- [ ] **Step 10: Chat UI** — Minimal HTML/JS/CSS chat interface in `ui/`
- [ ] **Step 11: Kiosk setup** — xenodm + chromium --kiosk auto-launch
- [ ] **Step 12: rc.d scripts** — OpenBSD service scripts for chatos_agent and chatos_ui

### Phase 4: Hardening — NOT STARTED

- [ ] **Step 13: pledge/unveil wrappers** — Python ctypes bindings for OpenBSD pledge() and unveil()
- [ ] **Step 14: Apply pledge/unveil** — Lock down each process
- [ ] **Step 15: Watchdog logic** — Monitor for unexpected behavior
- [ ] **Step 16: Installer script** — curl | sh that transforms a fresh OpenBSD into ChatOS

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
the `tomli` backport package, even though `tomli` is listed in pyproject.toml
dependencies (for potential <3.11 compat).

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
