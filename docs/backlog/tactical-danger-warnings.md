# Danger Warnings

**Status:** Proposed
**Date:** 2026-03-23
**Depends on:** None (can ship independently)

---

## Overview

at-cmd translates natural language into shell commands. The target user is someone who struggles with CLI syntax, which means they are also the user least likely to recognize a destructive command when they see one. The tool's primary safety guarantee -- human review before execution -- only works if the human understands what they are reviewing.

Danger Warnings adds a classification step between sanitization and display. After `sanitize_response` returns a `(command, description)` pair, the command is scanned against a registry of dangerous patterns. If any match, a colored warning line is rendered above the editable prompt (submit mode) or above the description line (inline mode). The user still has full control; the warning is advisory, not blocking.

## Motivation

- A user who types `@ delete everything in this folder` may receive `rm -rf ./*` and press Enter without understanding the consequences.
- `@ format my usb drive` could yield `dd if=/dev/zero of=/dev/sda` or `mkfs.ext4 /dev/sda1`.
- `@ fix permissions on my home directory` could yield `chmod -R 777 ~/`.
- The LLM is not adversarial, but it optimizes for correctness of translation, not for user safety. That responsibility belongs to the tool.

---

## User Stories

1. **As a novice user**, I want to see a visible warning when the translated command could delete data, so that I pause and think before pressing Enter.
2. **As an experienced user**, I want danger warnings to be unobtrusive and quick to dismiss, so they do not slow down my workflow.
3. **As a power user**, I want to customize which patterns trigger warnings (add my own, disable built-in ones), so the feature stays useful in my environment.
4. **As a user in inline mode**, I want the warning to appear alongside the description text, so I see it without switching interaction styles.
5. **As a user in JSON output mode** (`--json`), I want danger metadata included in the JSON payload, so downstream scripts can make their own decisions.

---

## Detailed UX

### Submit Mode

After the spinner completes and before the editable prompt appears:

```
$ @ delete all log files older than 30 days
  translating...
  !! WARNING: This command recursively deletes files (rm -rf)
  # Remove log files older than 30 days from /var/log
> find /var/log -name '*.log' -mtime +30 -exec rm -rf {} +
```

- The warning line starts with `!!` to be visually distinct from the description line which starts with `#`.
- **Warning-level** commands render in **yellow** (ANSI `\033[33m`).
- **Critical-level** commands render in **bold red** (ANSI `\033[1;31m`).
- The warning text follows the pattern: `!! WARNING: <human-readable risk> (<matched pattern>)`.
- If multiple patterns match, they are consolidated into a single line: `!! WARNING: Recursively deletes files, runs as root (rm -rf, sudo)`.
- The warning is written to stderr so it does not pollute piped output.

### Inline Mode

The shell integration scripts render the description as dim text below the command buffer. The warning line is inserted above the description:

```
$ find /var/log -name '*.log' -mtime +30 -exec rm -rf {} +
  !! WARNING: This command recursively deletes files (rm -rf)
  # Remove log files older than 30 days from /var/log
```

The inline shell functions receive warning data through the JSON output mode (`--json`). The JSON response gains two new fields:

```json
{
  "command": "find /var/log -name '*.log' -mtime +30 -exec rm -rf {} +",
  "description": "Remove log files older than 30 days from /var/log",
  "danger_level": "warning",
  "danger_messages": ["Recursively deletes files (rm -rf)"]
}
```

When `danger_level` is `null`, no warning is shown. The shell integration scripts are responsible for rendering the warning in the appropriate color.

### JSON Output Mode

When `--json` is passed, the danger fields are always present:

```json
{
  "command": "...",
  "description": "...",
  "danger_level": null,
  "danger_messages": []
}
```

This makes the schema stable regardless of whether a warning is triggered.

---

## Technical Design

### New Module: `src/at_cmd/danger.py`

A single module containing the pattern registry, classification function, and rendering helper.

#### Pattern Registry

Each pattern is a dataclass:

```python
@dataclass(frozen=True)
class DangerPattern:
    """A single dangerous command pattern.

    Attributes:
        name: Short identifier for the pattern (e.g., "rm-rf").
        regex: Compiled regular expression to match against the command string.
        level: Severity level -- "warning" or "critical".
        message: Human-readable description of the risk.
    """
    name: str
    regex: re.Pattern[str]
    level: str  # "warning" | "critical"
    message: str
```

The built-in registry is a module-level tuple of `DangerPattern` instances. Using a tuple (not a list) signals that the built-in set is not meant to be mutated at runtime.

#### Classification Function

```python
def classify_danger(command: str) -> DangerResult:
    """Scan a command string against the danger pattern registry.

    Args:
        command: The shell command to classify.

    Returns:
        DangerResult with the highest severity level and all matching messages.
    """
```

Returns a `DangerResult` dataclass:

```python
@dataclass(frozen=True)
class DangerResult:
    """Result of danger classification.

    Attributes:
        level: The highest matched severity ("critical" > "warning" > None).
        messages: Human-readable risk descriptions for each matched pattern.
    """
    level: str | None
    messages: list[str]
```

- The function iterates all patterns, collects matches, and returns the highest severity.
- Severity ordering: `critical` > `warning` > `None`.
- If no patterns match, returns `DangerResult(level=None, messages=[])`.

#### Rendering Helper

```python
def format_danger_warning(result: DangerResult) -> str | None:
    """Format a DangerResult into a colored terminal warning string.

    Args:
        result: The classification result.

    Returns:
        A formatted ANSI string for stderr, or None if no danger was detected.
    """
```

- Returns `None` when `result.level is None`.
- Uses yellow for warning, bold red for critical.
- Consolidates all messages into a single line.

### Integration Points

#### `cli.py` -- `translate_cmd`

After `sanitize_response` returns and before the description/prompt is rendered:

```python
command, description = sanitize_response(raw)
danger = classify_danger(command)
```

**Submit mode (non-JSON):** If `danger.level` is not `None`, render the warning line to stderr before the description line.

**JSON mode:** Add `danger_level` and `danger_messages` keys to the JSON output.

#### Shell integration scripts (`init.py`)

The inline-mode shell functions already call `at-cmd translate --json`. They will read the new `danger_level` and `danger_messages` fields and render a warning line in the appropriate color if present. Changes are needed in the bash, zsh, fish, and powershell templates.

### Module Dependency

```
cli.py -> sanitize.py -> (command, description)
                      -> danger.py -> DangerResult
       -> display warning
       -> editable prompt
```

`danger.py` has no dependencies beyond the standard library (`re`, `dataclasses`).

---

## Pattern List

### Critical Level

These patterns represent commands that can cause immediate, irreversible data loss or system damage.

| Name | Regex | Message |
|------|-------|---------|
| `rm-rf-root` | `rm\s+.*-[a-zA-Z]*r[a-zA-Z]*f.*\s+/(?:\s\|$)` | Recursively force-deletes from the root filesystem |
| `dd-device` | `\bdd\s+.*(?:of\|if)=/dev/` | Writes directly to a block device |
| `mkfs` | `\bmkfs(?:\.\w+)?\s+` | Formats a filesystem |
| `fork-bomb` | `:\(\)\s*\{\s*:\|:\s*&\s*\}\s*;?\s*:` | Fork bomb -- will crash the system |
| `dev-null-redirect` | `>\s*/dev/sda` | Writes directly to a block device |
| `drop-database` | `\bDROP\s+(?:DATABASE\|SCHEMA)\b` | Drops an entire database |

### Warning Level

These patterns represent commands that are dangerous but may be intentional in certain contexts.

| Name | Regex | Message |
|------|-------|---------|
| `rm-rf` | `rm\s+.*-[a-zA-Z]*r[a-zA-Z]*f` | Recursively force-deletes files |
| `rm-recursive` | `rm\s+.*-[a-zA-Z]*r` | Recursively deletes files |
| `chmod-777` | `chmod\s+.*777` | Sets world-writable permissions |
| `chmod-recursive-root` | `chmod\s+.*-R.*\s+/(?:\s\|$)` | Recursively changes permissions from root |
| `chown-recursive-root` | `chown\s+.*-R.*\s+/(?:\s\|$)` | Recursively changes ownership from root |
| `drop-table` | `\bDROP\s+TABLE\b` | Drops a database table |
| `truncate-table` | `\bTRUNCATE\s+(?:TABLE\s+)?\w+` | Truncates a database table |
| `delete-no-where` | `\bDELETE\s+FROM\s+\w+\s*;` | Deletes all rows (no WHERE clause) |
| `sudo-rm` | `sudo\s+rm\b` | Deletes files with root privileges |
| `pipe-to-sh` | `\|\s*(?:ba)?sh\b` | Pipes output into a shell interpreter |
| `curl-to-sh` | `curl\s+.*\|\s*(?:ba)?sh` | Downloads and executes a remote script |
| `wget-to-sh` | `wget\s+.*\|\s*(?:ba)?sh` | Downloads and executes a remote script |
| `overwrite-system-file` | `>\s*/etc/` | Overwrites a system configuration file |
| `kill-all` | `\bkillall\b\|\bpkill\s+-9` | Force-kills processes |
| `shutdown-reboot` | `\b(?:shutdown\|reboot\|poweroff\|halt)\b` | Shuts down or reboots the system |
| `git-force-push` | `git\s+push\s+.*--force` | Force-pushes to a remote (rewrites history) |
| `git-reset-hard` | `git\s+reset\s+--hard` | Discards uncommitted changes |

### Regex Design Notes

- All patterns use word boundaries (`\b`) where appropriate to avoid false positives on substrings (e.g., `alarm` should not match `rm`).
- Patterns account for flag ordering flexibility (`rm -rf`, `rm -r -f`, `rm --recursive --force` are all valid).
- Patterns are matched case-insensitively for SQL keywords only. Shell commands are case-sensitive.
- The regex is applied to the full command string, not individual tokens, so it catches patterns inside pipes and `&&` chains.

---

## Severity Levels

| Level | Color | Meaning | Example |
|-------|-------|---------|---------|
| **critical** | Bold red (`\033[1;31m`) | Immediate, likely irreversible damage to the system or data. Almost never intentional from a natural-language request. | `rm -rf /`, `dd if=/dev/zero of=/dev/sda`, fork bomb |
| **warning** | Yellow (`\033[33m`) | Potentially destructive but may be exactly what the user asked for. Warrants a pause and review. | `rm -rf ./logs`, `chmod 777 app.py`, `DROP TABLE users` |

The highest matched severity wins. If a command matches both a warning pattern and a critical pattern, the critical level is displayed. All matched messages are still listed.

---

## Configuration

### TOML Config (`~/.config/at-cmd/config.toml`)

```toml
[danger]
enabled = true                     # Set to false to disable all warnings

# Additional user-defined patterns (merged with built-ins)
[[danger.patterns]]
name = "my-dangerous-tool"
regex = "my-tool\\s+--destroy"
level = "warning"
message = "Runs my-tool in destructive mode"

# Suppress specific built-in patterns by name
[danger]
suppress = ["rm-rf", "git-force-push"]
```

### Environment Variables

| Variable | Effect |
|----------|--------|
| `AT_CMD_DANGER_ENABLED` | `true` (default) or `false` -- master switch |

Environment variables intentionally do not support adding custom patterns. That level of configuration belongs in the TOML file.

### Config Dataclass Changes

The `Config` dataclass in `config.py` gains:

```python
danger_enabled: bool = True
danger_suppress: list[str] = field(default_factory=list)
```

Custom patterns from TOML are loaded separately in `danger.py` and merged with the built-in registry at classification time.

### CLI Flag

```
at-cmd translate --no-danger   # Suppress warnings for this invocation
```

This flag is useful for scripting and for experienced users who want a quick one-off without the warning.

---

## Edge Cases

### False Positives

- `echo "rm -rf /"` -- the pattern is inside a quoted string argument to `echo`. This is a known false positive. The regex engine matches on the raw command string and does not parse shell quoting. **Decision:** Accept false positives. A spurious warning is far less harmful than a missed real one. Users can suppress specific patterns if needed.
- `grep -r "pattern" .` -- the `-r` flag on `grep` should not trigger `rm -r`. **Mitigation:** The `rm-recursive` pattern anchors on `\brm\s+`, not bare `-r`.
- `chmod 644 file.txt` -- should not trigger. Only `chmod 777` and recursive-root patterns match.

### Piped Commands

- `find . -name '*.tmp' | xargs rm -rf` -- the `rm -rf` pattern matches because it scans the full command string including everything after pipes. This is correct behavior.
- `cat file | sudo sh` -- matches both `pipe-to-sh` and potentially `sudo`. Both warnings are shown.

### Chained Commands (`&&`, `;`, `||`)

- `mkdir backup && rm -rf old/` -- the `rm -rf` pattern matches because the full string is scanned. This is correct.
- No attempt is made to split on `&&` and classify each sub-command independently. The full-string approach is simpler and catches more cases.

### Subshells and Command Substitution

- `$(rm -rf /)` -- matches. The regex sees the content regardless of `$()` wrapping.
- Backtick substitution also matches for the same reason.

### Escaped or Obfuscated Commands

- `r\m -rf /` -- does not match. The regex expects literal `rm`. **Decision:** Obfuscation is an adversarial case. The LLM is not adversarial, and the user typed a natural-language request. If the LLM returns obfuscated output, `sanitize.py` will likely reject it as malformed before danger classification runs.

### Empty or Single-Word Commands

- `ls`, `pwd`, `echo hello` -- no patterns match, no warning shown. Zero overhead for the common case.

### Multiple Matches

- `sudo rm -rf / && dd if=/dev/zero of=/dev/sda` -- matches `rm-rf-root` (critical), `sudo-rm` (warning), `dd-device` (critical). Result: critical level, three messages consolidated into one warning line.

---

## Testing Strategy

All tests live in `tests/test_danger.py`.

### Unit Tests for `classify_danger`

**Expected use (one test per pattern category):**

| Test | Input | Expected Level |
|------|-------|----------------|
| `test_rm_rf_detected` | `rm -rf /tmp/old` | warning |
| `test_rm_rf_root_critical` | `rm -rf /` | critical |
| `test_dd_device` | `dd if=/dev/zero of=/dev/sda bs=4M` | critical |
| `test_mkfs` | `mkfs.ext4 /dev/sdb1` | critical |
| `test_chmod_777` | `chmod 777 app.py` | warning |
| `test_drop_table` | `DROP TABLE users;` | warning |
| `test_curl_pipe_sh` | `curl -sL https://example.com/install.sh \| bash` | warning |
| `test_fork_bomb` | `:(){ :\|:& };:` | critical |
| `test_git_force_push` | `git push origin main --force` | warning |
| `test_sudo_rm` | `sudo rm -rf /var/log/old` | warning |

**Safe commands (no false positives):**

| Test | Input | Expected Level |
|------|-------|----------------|
| `test_safe_ls` | `ls -la` | None |
| `test_safe_grep_recursive` | `grep -r "pattern" .` | None |
| `test_safe_echo_rm` | `echo "rm -rf"` | warning (accepted false positive) |
| `test_safe_chmod_644` | `chmod 644 file.txt` | None |
| `test_safe_git_push` | `git push origin main` | None |

**Edge cases:**

| Test | Input | Expected Level |
|------|-------|----------------|
| `test_piped_rm` | `find . \| xargs rm -rf` | warning |
| `test_chained_commands` | `mkdir backup && rm -rf old/` | warning |
| `test_multiple_matches_highest_wins` | `sudo rm -rf /` | critical |
| `test_empty_command` | `` | None |
| `test_whitespace_only` | `   ` | None |

### Unit Tests for `format_danger_warning`

- Test that warning-level results produce yellow ANSI output.
- Test that critical-level results produce bold-red ANSI output.
- Test that `None`-level results return `None`.
- Test that multiple messages are comma-joined.

### Unit Tests for Configuration

- Test that `danger_enabled = false` causes `classify_danger` to return no results.
- Test that suppressed pattern names are excluded from matching.
- Test that user-defined patterns from TOML are merged with built-ins.

### Integration Tests

- Test that `translate_cmd` with `--json` includes `danger_level` and `danger_messages` keys.
- Test that the warning line appears on stderr in submit mode (mock the LLM backend).
- Test that `--no-danger` suppresses warnings.

---

## Out of Scope

The following are explicitly not part of this feature:

- **Blocking execution.** The warning is advisory. at-cmd never prevents the user from running a command. Adding a confirmation gate (e.g., "type YES to proceed") is a separate feature and a different UX philosophy.
- **Context-aware classification.** The classifier does not know whether `/tmp/old` exists or whether the user has backups. It pattern-matches on syntax only.
- **LLM-based risk assessment.** Asking the LLM "is this command dangerous?" would add latency and cost. The regex approach is instantaneous and deterministic.
- **Real-time re-classification after edits.** If the user edits `rm -rf /` to `rm -rf ./old_logs/` in the prompt, the warning is not re-evaluated. This would require hooking into readline or the shell buffer in ways that are complex and shell-specific.
- **Severity beyond two levels.** Two levels (warning and critical) are sufficient. Adding "info" or "danger" or a numeric scale adds complexity without meaningful UX benefit.
- **Network-aware patterns.** Detecting `curl` to a known-malicious URL or `ssh` to an unexpected host is out of scope. The classifier operates on command syntax, not network intelligence.
- **Windows-specific patterns.** `del /s /q`, `format C:`, `Remove-Item -Recurse -Force` are not covered in the initial pattern list. They should be added when PowerShell support matures.
