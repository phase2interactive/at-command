# Shell History as Living Context

**Status:** Exploratory Draft
**Date:** 2026-03-23
**Author:** at-cmd team
**Depends on:** Core translate pipeline (cli.py, detect.py, llm.py, config.py)

---

## Overview

Today `at-cmd` is stateless. Every translation request is independent -- the LLM
sees only the user's natural-language request plus OS/shell/cwd metadata. This
means a user who just ran `docker compose up -d` and types `@ show me the logs`
gets a generic suggestion like `journalctl -f` instead of the contextually
obvious `docker compose logs -f`.

This feature feeds a sanitized, opt-in window of recent shell history entries
into the LLM system prompt so that translations can leverage conversational
context from the user's actual terminal session.

### Why This Matters

- **Pronoun resolution**: "do that again but for the other service" becomes
  answerable when the LLM can see what "that" and "the other service" refer to.
- **Tool affinity**: If the history shows `kubectl` commands, a request about
  "restart the pod" should stay in the Kubernetes toolchain.
- **Workflow continuity**: Multi-step tasks (build, test, deploy) generate
  better suggestions when the LLM sees the preceding steps.

---

## User Stories

| ID   | Story |
|------|-------|
| US-1 | As a developer, I want `at-cmd` to see my recent commands so that requests like "do it again with verbose" produce accurate results. |
| US-2 | As a security-conscious user, I want history context to be off by default so that no command history ever leaves my machine unless I explicitly enable it. |
| US-3 | As a user who sometimes passes tokens on the command line, I want sensitive patterns automatically stripped from history before it reaches the LLM. |
| US-4 | As a user with a non-standard history file location, I want to configure the path so `at-cmd` can still find my history. |
| US-5 | As a user on a shared machine, I want a deny-list of command patterns (e.g., `mysql -p`, `AWS_SECRET`) that are never sent to the LLM. |
| US-6 | As a privacy-focused user, I want a "commands-only" mode that sends command names but strips all arguments, so the LLM sees tool usage patterns without any data. |

---

## Privacy Design

Shell history is among the most sensitive artifacts on a developer's machine. It
routinely contains API keys passed as arguments, database passwords, internal
hostnames, and other material that must never be sent to a remote service
without informed, explicit consent.

### Principles

1. **Off by default.** History context is disabled unless the user sets
   `history_context = true` in their config file or sets the environment
   variable `AT_CMD_HISTORY_CONTEXT=true`. There is no "first run" prompt that
   nudges toward enabling it.

2. **Minimal data.** Only the command text of recent history entries is read.
   Timestamps, session IDs, and other metadata are discarded before processing.

3. **Sanitization before transmission.** Every history entry passes through a
   multi-stage sanitization pipeline (see below) before it is eligible for
   inclusion in the system prompt. Entries that match deny-list patterns are
   dropped entirely. Entries in strip-arguments mode are reduced to command
   names only.

4. **Bounded scope.** A configurable cap (`history_count`, default 20, max 100)
   limits how many entries are included. This bounds both privacy exposure and
   token cost.

5. **Transparent documentation.** The `at-cmd config` TUI and the generated
   config file both include comments explaining exactly what data is sent and
   to where. The `--json` output mode already shows the system prompt; with
   this feature it will also show the history entries that were included.

6. **No caching or persistence.** History entries are read on every invocation,
   sanitized in memory, injected into the prompt, and discarded. `at-cmd` never
   writes history data to disk, logs, or any secondary store.

### What Leaves the Machine

When history context is enabled, the following data is included in the LLM
request (which is sent to whichever backend the user has configured):

| Data | Included | Notes |
|------|----------|-------|
| Recent command strings | Yes | After sanitization pipeline |
| Command arguments | Depends | Included by default; stripped in `strip_arguments` mode |
| Timestamps | No | Discarded during parsing |
| Session/terminal IDs | No | Discarded during parsing |
| Environment variables | No | Not read from history |
| File contents | No | Never read |

When using a local backend (e.g., Ollama), history data does not leave the
machine at all. When using a remote backend (Claude, OpenAI), the data is sent
over HTTPS to that provider's API endpoint. Users should consult their
provider's data retention policy.

---

## Detailed UX

### Enabling History Context

**Via config file** (`~/.config/at-cmd/config.toml`):

```toml
# Shell history context -- sends recent commands to the LLM for better
# translations. Off by default. See: at-cmd docs for privacy details.
history_context = true
history_count = 20                  # Number of recent entries (max 100)
# history_file = ""                # Override auto-detected history path
# history_deny_patterns = []       # Regex patterns to drop entirely
# history_strip_arguments = false  # Send command names only, no arguments
```

**Via environment variables**:

```bash
export AT_CMD_HISTORY_CONTEXT=true
export AT_CMD_HISTORY_COUNT=20
export AT_CMD_HISTORY_STRIP_ARGUMENTS=true
```

**Via `at-cmd config` TUI**: A new "History Context" section with toggle,
count slider, deny-list editor, and strip-arguments checkbox. The section
header includes a one-line privacy note: "When enabled, recent shell commands
are included in LLM requests."

### How History Appears in the System Prompt

When enabled, the system prompt gains a new section appended after the existing
context block:

```
You are a shell command translator for zsh on macOS.
Working directory: /Users/dev/myproject
The user will describe what they want in natural language.
Return EXACTLY two lines:
Line 1: The zsh command (no backticks, no markdown, one line, use appropriate chaining for zsh)
Line 2: A brief description (10 words max) of what the command does

Recent shell history (most recent last):
  git status
  docker compose up -d
  docker compose ps
  curl http://localhost:8080/health
```

The history block is clearly labeled so the LLM understands its role. Entries
are listed oldest-first (most recent last) to match natural reading order and
give recency bias to the final entries.

### Feedback to the User

When `--json` mode is used, the output includes a `history_entries` array so
the user can audit exactly what was sent:

```json
{
  "command": "docker compose logs -f",
  "description": "Follow Docker Compose service logs",
  "history_entries": [
    "git status",
    "docker compose up -d",
    "docker compose ps",
    "curl http://localhost:8080/health"
  ]
}
```

---

## Shell History File Locations

The module auto-detects the history file based on the detected shell:

| Shell | Default Location | Format |
|-------|-----------------|--------|
| bash  | `~/.bash_history` | One command per line. Multiline commands use `\` continuation. Timestamps appear as `#<epoch>` lines when `HISTTIMEFORMAT` is set. |
| zsh   | `~/.zsh_history` or `$HISTFILE` | Extended format: `: <epoch>:<duration>;<command>`. Falls back to plain format if extended markers are absent. |
| fish  | `~/.local/share/fish/fish_history` | Custom format: `- cmd: <command>` entries with `when: <epoch>` fields. |
| powershell | `(Get-PSReadLineOption).HistorySavePath` | One command per line. Default path: `~/.local/share/powershell/PSReadLine/ConsoleHost_history.txt` on Unix, `$env:APPDATA\Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt` on Windows. |

**Override**: The user can set `history_file = "/path/to/custom/history"` in
config or `AT_CMD_HISTORY_FILE=/path` as an env var. When set, the file is
read as plain text (one command per line) with no format-specific parsing.

**Resolution order**: config/env override > `$HISTFILE` env var (bash/zsh) >
shell-specific default path.

---

## Sanitization Pipeline

Every history entry passes through these stages in order. If an entry is
dropped at any stage, subsequent stages do not process it.

### Stage 1: Format Parsing

Strip shell-specific metadata to extract the bare command string:

- **zsh extended format**: Remove leading `: <epoch>:<duration>;` prefix.
- **fish format**: Extract value after `- cmd: `, skip `when:` lines.
- **bash timestamps**: Drop lines matching `^#\d+$`.
- **All shells**: Strip leading/trailing whitespace. Drop empty lines.

### Stage 2: Deny-List Filtering

Drop any entry matching a pattern in the deny list. The deny list is the union
of built-in patterns and user-configured patterns.

**Built-in deny patterns** (always active when history context is enabled):

```python
BUILTIN_DENY_PATTERNS = [
    r"(?i)(api[_-]?key|token|secret|password|passwd|credential)\s*=",
    r"(?i)(-p\s+\S|--password[= ]\S)",          # password flags
    r"(?i)(bearer|basic)\s+[A-Za-z0-9+/=]{20,}", # auth headers
    r"(?i)curl\s.*-H\s*['\"]Authorization:",      # curl auth headers
    r"(?i)(AWS_SECRET|GITHUB_TOKEN|GH_TOKEN|OPENAI_API_KEY)",
    r"(?i)mysql\s.*-p\S+",                        # mysql inline password
    r"(?i)export\s+\S*(KEY|TOKEN|SECRET|PASSWORD)", # env var assignments
    r"(?i)ssh-keygen|gpg\s+--",                    # key operations
]
```

**User deny patterns** (`history_deny_patterns` in config) are compiled as
regular expressions and matched against the full command string. Example:

```toml
history_deny_patterns = [
    "internal\\.corp\\.example\\.com",
    "vault\\s+write",
]
```

### Stage 3: Argument Stripping (Optional)

When `history_strip_arguments = true`, each entry is reduced to the command
name (first whitespace-delimited token) only. Pipes and chains are preserved
structurally:

| Before | After |
|--------|-------|
| `docker compose up -d` | `docker compose up` |
| `find . -name '*.py' -mtime -7` | `find` |
| `cat logs.txt \| grep error \| wc -l` | `cat \| grep \| wc` |
| `git commit -m "fix bug"` | `git commit` |

For known commands with subcommands (git, docker, kubectl, systemctl, brew,
cargo, npm, uv, just), the first two tokens are preserved. For piped commands,
each segment is stripped independently.

### Stage 4: Deduplication and Truncation

- Remove consecutive duplicate entries (keep one).
- Take the last `history_count` entries from the filtered result.

### Stage 5: Final Validation

- Drop any entry longer than 500 characters (likely a pasted script, not a
  typed command).
- Drop any entry that contains a raw base64 blob longer than 50 characters
  (likely an encoded secret or binary data).

---

## Technical Design

### New Module: `src/at_cmd/history.py`

```
history.py
    HistoryConfig          - dataclass holding history-specific config fields
    read_history()         - read + parse history file for detected shell
    sanitize_entries()     - run the full sanitization pipeline
    get_history_context()  - top-level function: returns list[str] or empty
```

**`get_history_context(shell: str, config: Config) -> list[str]`** is the
public API. It returns an empty list when the feature is disabled. Otherwise
it reads, parses, sanitizes, and returns the entries ready for prompt injection.

### Integration Points

**`detect.py`**: Add an optional `history_entries: tuple[str, ...] = ()`
field to `ShellContext`. The field defaults to an empty tuple to preserve
backward compatibility. `detect_context()` gains an optional
`history_config` parameter; when provided it calls `get_history_context()`.

**`llm.py`**: `build_system_prompt()` appends the history block only when
`ctx.history_entries` is non-empty:

```python
def build_system_prompt(ctx: ShellContext) -> str:
    prompt = (
        f"You are a shell command translator for {ctx.shell} on {ctx.os_name}.\n"
        f"Working directory: {ctx.cwd}\n"
        # ... existing content ...
    )
    if ctx.history_entries:
        history_block = "\n".join(f"  {entry}" for entry in ctx.history_entries)
        prompt += (
            f"\n\nRecent shell history (most recent last):\n{history_block}"
        )
    return prompt
```

**`config.py`**: Add new fields to the `Config` dataclass:

```python
@dataclass
class Config:
    # ... existing fields ...
    history_context: bool = False
    history_count: int = 20
    history_file: str = ""
    history_deny_patterns: list[str] | None = None
    history_strip_arguments: bool = False
```

Load from TOML, env vars (`AT_CMD_HISTORY_CONTEXT`, etc.), same layered
resolution as existing fields. `history_deny_patterns` is read as a TOML
array of strings.

**`cli.py`**: No new flags. History context is configuration-only (not a
per-invocation toggle) to avoid accidental exposure via shell aliases or
scripts that pass `--history`.

### Module Boundaries

```
cli.py
  |
  v
detect.py  <--  history.py (called during context detection)
  |
  v
llm.py     (receives ShellContext with history_entries populated)
  |
  v
backend
```

`history.py` has no dependencies on `llm.py` or `cli.py`. It depends only on
`config.py` (for `Config`) and the standard library.

---

## Configuration Reference

| Key | Env Var | Type | Default | Description |
|-----|---------|------|---------|-------------|
| `history_context` | `AT_CMD_HISTORY_CONTEXT` | bool | `false` | Enable shell history in LLM prompts. |
| `history_count` | `AT_CMD_HISTORY_COUNT` | int | `20` | Number of recent entries to include (1-100). |
| `history_file` | `AT_CMD_HISTORY_FILE` | str | `""` | Override auto-detected history file path. |
| `history_deny_patterns` | `AT_CMD_HISTORY_DENY_PATTERNS` | list[str] | `[]` | Additional regex patterns; matching entries are dropped. |
| `history_strip_arguments` | `AT_CMD_HISTORY_STRIP_ARGUMENTS` | bool | `false` | Strip arguments, send command names only. |

`history_deny_patterns` via env var is a comma-separated string:
`AT_CMD_HISTORY_DENY_PATTERNS="internal\\.corp,vault\\s+write"`

---

## Edge Cases

| Case | Behavior |
|------|----------|
| **History file does not exist** | Return empty list. No error, no warning. Feature degrades silently. |
| **History file is not readable** (permissions) | Return empty list. Log a debug-level message to stderr if verbose mode is on. |
| **History file is very large** (>100 MB) | Read only the last `history_count * 10` lines using a seek-to-end strategy. Never read the entire file into memory. |
| **Non-standard history location** | User sets `history_file` in config. File is read as plain text, one command per line. |
| **Shell not recognized** | If the detected shell is not bash/zsh/fish/powershell and no `history_file` is configured, return empty list. |
| **Multiline commands in history** | Bash uses `\` continuations; zsh uses embedded newlines. Join continued lines into a single string. If the joined result exceeds 500 characters, drop it. |
| **History contains at-cmd invocations** | Filter out entries starting with `@ ` or `at-cmd ` to avoid self-referential context. |
| **All entries filtered by deny list** | Return empty list. The prompt simply omits the history section. |
| **Config sets history_count > 100** | Clamp to 100. |
| **Config sets history_count < 1** | Clamp to 1. |
| **Concurrent writes to history** | Read is a point-in-time snapshot. No locking. If the file is mid-write, the last entry may be truncated; the 500-char limit and validation will discard it. |
| **Binary data in history file** | Catch `UnicodeDecodeError`, skip undecodable lines, continue with the rest. |

---

## Testing Strategy

Tests live in `tests/test_history.py`.

### Unit Tests

| Area | Tests |
|------|-------|
| **Format parsing** | Parse zsh extended format, fish format, bash with timestamps. Verify metadata is stripped correctly. |
| **Deny-list filtering** | Built-in patterns catch `export GITHUB_TOKEN=xxx`, `curl -H "Authorization: Bearer ..."`, `mysql -pSecretPass`. User patterns drop custom matches. |
| **Argument stripping** | `docker compose up -d` becomes `docker compose up`. Pipes are handled. Known subcommand tools keep two tokens. |
| **Deduplication** | Three consecutive identical entries produce one. Non-consecutive duplicates are kept. |
| **Truncation** | History of 200 entries with `history_count=20` returns exactly 20. |
| **Max-length drop** | Entry of 600 characters is dropped. Entry of 400 characters is kept. |
| **Base64 detection** | Entry containing a 60-char base64 blob is dropped. |
| **Self-referential filtering** | Entries starting with `@ ` or `at-cmd ` are removed. |
| **Empty/missing file** | Returns empty list, no exception. |
| **Unreadable file** | Returns empty list, no exception. |
| **Binary data** | Undecodable bytes are skipped gracefully. |
| **Config disabled** | `history_context=false` returns empty list without reading any file. |

### Integration Tests

| Area | Tests |
|------|-------|
| **System prompt assembly** | With history entries, `build_system_prompt()` includes the history block. Without entries, the prompt is unchanged from current behavior. |
| **End-to-end** | Mock a history file, enable the feature in config, call the translate pipeline, verify history appears in the system prompt passed to the backend. |
| **Config round-trip** | Write config with history fields, reload, verify all fields are preserved. |

### Fixture Files

Create `tests/fixtures/` with sample history files:
- `bash_history_plain.txt` -- plain format
- `bash_history_timestamps.txt` -- with `#epoch` lines
- `zsh_history_extended.txt` -- `: epoch:duration;command` format
- `fish_history.txt` -- `- cmd:` / `when:` format
- `history_with_secrets.txt` -- entries containing tokens and passwords

---

## Out of Scope

The following are explicitly not part of this feature:

- **Semantic summarization of history.** This feature sends raw (sanitized)
  command strings, not LLM-generated summaries. A local summarization step
  would add latency and complexity without clear benefit at this stage.
- **Cross-session history merging.** Only the single history file for the
  current shell is read. Fish's per-session history and zsh's `INC_APPEND_HISTORY`
  behavior are handled, but no attempt is made to merge multiple session files.
- **Real-time history streaming.** History is read once per invocation as a
  snapshot. There is no file watcher or background process.
- **History from other tools.** Atuin, McFly, and other history replacement
  tools store history in SQLite or custom formats. Supporting them is a
  separate feature.
- **Interactive history selection.** The user cannot pick which history entries
  to include per-request. The pipeline is automatic and configuration-driven.
- **Persistent history index or cache.** No local database or index of history
  is maintained between invocations.
- **Sending history to the `at-cmd config` TUI.** The TUI shows configuration
  options for the feature but does not preview or display actual history entries.
