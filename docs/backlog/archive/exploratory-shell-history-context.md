# Session Context via --resume

**Status:** Exploratory Draft
**Date:** 2026-03-23
**Depends on:** Core translate pipeline (cli.py, llm.py, config.py)

---

## Overview

Today `at-cmd` is stateless — every translation is independent. A user who just translated `@ start the docker services` and then types `@ show me the logs` gets a generic `journalctl` suggestion instead of `docker compose logs -f`.

Rather than parsing shell history files (complex, privacy-heavy), this feature leverages the Claude CLI's built-in session persistence. By reusing a session ID across invocations, the LLM naturally remembers prior translations without any history parsing, sanitization pipelines, or extra prompt injection.

### Why This Is Simpler

- No history file parsing (bash/zsh/fish/powershell all have different formats)
- No sanitization pipeline for secrets
- No privacy concerns beyond what the user already sends per-request — the LLM only sees prior `at-cmd` interactions, not raw shell history
- The Claude CLI handles session storage, resumption, and cleanup

---

## User Stories

| ID | Story |
|----|-------|
| US-1 | As a user, I want `@ show me the logs` to know I just started Docker, so I get `docker compose logs -f` instead of `journalctl`. |
| US-2 | As a user, I want to start a fresh session when I switch projects so old context doesn't pollute new translations. |
| US-3 | As a user, I want to see which session I'm in so I know whether context is active. |
| US-4 | As a user working without the claude backend, I want the tool to work normally (stateless) without errors. |

---

## UX

### Default behavior: session context is always on

Every invocation automatically resumes the per-directory session. No flag needed:

```bash
# First call in this directory — creates a new session automatically
@ find all python files modified this week

# Second call — LLM remembers the prior translation
@ now delete the ones in /tmp
# → rm /tmp/*.py that were found by the previous command's criteria
```

### Opting out of session context

```bash
# Run a single stateless translation (no session)
@ --no-session find large jpg files

# Or disable globally in config
# resume_session = false
```

### Managing sessions

```bash
# Start a fresh session (discards prior context)
@ --new-session

# Show current session info
@ --session-info
# → Session: at-cmd-a1b2c3d4 (12 interactions, started 2h ago)

# Clear session (go back to stateless until next invocation creates one)
@ --clear-session
```

---

## Technical Design

### Session ID Management

`at-cmd` needs a stable session ID per "working context." Options:

1. **Per-directory session** — hash the cwd to generate a deterministic session name: `at-cmd-<hash(cwd)>`. Switching directories naturally gives a new session.
2. **Named session** — user names it: `@ --resume myproject`. Maps to a claude `--session-id` or `--name`.
3. **Single global session** — one `at-cmd` session stored in `~/.config/at-cmd/session_id`. Simplest.

**Recommended: Per-directory (option 1)** — it matches how developers work (one project = one directory) and requires no manual management.

### Claude CLI Integration

The claude backend in `llm.py` currently calls:
```python
["claude", "-p", "--model", config.model]
```

With `--resume`, it becomes:
```python
["claude", "-p", "--model", config.model, "--resume", session_id]
```

If the session doesn't exist yet, `--resume` with a new session ID creates it. If it does exist, it continues it.

### Session ID Storage

Store the current session ID in `~/.local/share/at-cmd/sessions.json`:

```json
{
  "/Users/dev/myproject": {
    "session_id": "a1b2c3d4-...",
    "created": "2026-03-23T10:00:00Z",
    "interactions": 12
  }
}
```

### Module Changes

| Module | Change |
|--------|--------|
| `config.py` | Add `resume_session: bool = True` field. Env var: `AT_CMD_RESUME_SESSION`. |
| `llm.py` | `_claude_backend` appends `--resume <id>` by default. Omits it when `--no-session` is passed. |
| `cli.py` | Add `--no-session`, `--new-session`, `--clear-session`, `--session-info` flags. |
| `session.py` (new) | Session ID generation, storage, lookup by cwd. Small module (~80 lines). |

### Non-Claude Backends

For ollama and openai backends, `--resume` is a no-op with a one-time warning:
```
Warning: Session context requires the claude backend. Running stateless.
```

Future work could add a conversation history buffer for HTTP backends, but that's out of scope.

---

## Configuration

```toml
# Session context is on by default. Set to false to disable.
resume_session = true   # default
```

```bash
# Disable session context globally
export AT_CMD_RESUME_SESSION=false
```

---

## Edge Cases

| Case | Behavior |
|------|----------|
| Session with non-claude backend | Warn once on first invocation, proceed stateless. |
| Session file doesn't exist yet | Create it on first invocation automatically. |
| Session file corrupted | Delete and start fresh. No error. |
| Very old session (days/weeks) | Works fine — Claude CLI handles session expiry. If the session is gone server-side, a new one is created transparently. |
| `--new-session` without prior session | No-op, no error. |
| `--no-session` + `--new-session` in same call | `--new-session` wins (clear first, then start fresh session). |
| Concurrent invocations in same directory | Both use the same session ID. Claude CLI handles serialization. |

---

## Testing Strategy

Tests live in `tests/test_session.py`.

| Area | Tests |
|------|-------|
| **Session ID generation** | Deterministic per cwd. Different cwd = different ID. |
| **Session storage** | Write, read, clear, corrupt-and-recover. |
| **CLI flag parsing** | `--no-session`, `--new-session`, `--clear-session`, `--session-info` are recognized. |
| **Claude backend integration** | Session args appended to subprocess call by default. `--no-session` omits them. |
| **Non-claude backend** | Warning emitted, proceeds stateless, no crash. |
| **Config default** | `resume_session = true` in config behaves like always passing `--resume`. |

---

## Out of Scope

- Conversation history buffer for ollama/openai backends
- Session sharing across machines
- Session export/import
- Browsing past session content from within at-cmd
- Privacy sanitization (not needed — the LLM only sees its own prior at-cmd interactions)
- Shell history file parsing (the original approach — replaced by this design)
