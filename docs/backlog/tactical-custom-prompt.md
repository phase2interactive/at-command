# Feature Spec: Custom User Prompt

**Status:** Draft
**Date:** 2026-03-23
**Origin:** Tactical Backlog -- "Custom User Prompt"

---

## Overview

Let users inject free-text instructions into the system prompt via the
`config.toml` file (or an environment variable). The text is appended to the
existing system prompt before it is sent to the LLM backend, giving users
direct control over command translation without the tool needing to build
complex auto-detection or per-tool configuration.

### Motivation

Different users operate under different constraints:

- Some prefer modern replacements (`fd` over `find`, `ripgrep` over `grep`).
- Some work in POSIX-only environments and need strictly portable commands.
- Some always target containers (`docker exec` wrappers) or remote hosts.
- Some have project-specific conventions ("use `pnpm`, not `npm`").

A single free-text field is the simplest mechanism that addresses all of these
cases. It avoids the complexity of structured tool lists, per-tool flags, or
auto-detection while still giving the LLM meaningful steering information.

---

## User Stories

1. **Tool preference** -- As a developer who uses `fd` and `bat`, I want the
   LLM to prefer those tools so I do not have to manually edit every command.

2. **Portability constraint** -- As a sysadmin managing legacy servers, I want
   to tell the LLM "use only POSIX commands" so the output works on minimal
   systems.

3. **Project conventions** -- As a team lead, I want to set
   `custom_prompt = "use pnpm instead of npm"` in a shared dotfile so
   onboarding engineers get consistent commands.

4. **No custom prompt** -- As a casual user with no special preferences, I
   want the tool to work exactly as it does today when no custom prompt is
   configured.

---

## Configuration

### Config field

A new string field `custom_prompt` is added to the `Config` dataclass with a
default of `""` (empty string).

```toml
# ~/.config/at-cmd/config.toml

backend = "ollama"
model   = "llama3"

custom_prompt = "Prefer fd over find and ripgrep over grep. Always use long flags for clarity."
```

The value is a plain string. Multi-line TOML strings (triple-quoted) are
supported naturally by `tomllib`:

```toml
custom_prompt = """
Prefer fd over find.
Always quote shell variables.
Target bash 4+ features.
"""
```

### Environment variable override

```
AT_CMD_CUSTOM_PROMPT="use only POSIX commands"
```

The standard layered resolution applies:
defaults -> config.toml -> env var -> (no CLI flag for this field).

There is no `--custom-prompt` CLI flag. The field is intended for persistent
preferences, not per-invocation overrides. Per-invocation steering is better
handled by simply rephrasing the natural-language request.

---

## System Prompt Injection

### Placement

The custom text is appended to the system prompt **after** the core
instructions and **before** any future structured blocks (e.g., available
tools). This keeps the JSON output contract and shell context at the top
where the LLM sees them first, while user preferences act as additional
constraints.

Current system prompt (from `build_system_prompt`):

```text
You are a shell command translator for {shell} on {os}.
Working directory: {cwd}
The user will describe what they want in natural language.
Return your response as a JSON object with exactly these fields:
{"command": "<the shell command>", "description": "<10 words max>"}
Return ONLY the JSON object. No markdown, no explanation.
```

With a custom prompt, the output becomes:

```text
You are a shell command translator for {shell} on {os}.
Working directory: {cwd}
The user will describe what they want in natural language.
Return your response as a JSON object with exactly these fields:
{"command": "<the shell command>", "description": "<10 words max>"}
Return ONLY the JSON object. No markdown, no explanation.

Additional user instructions:
Prefer fd over find and ripgrep over grep. Always use long flags for clarity.
```

### Escaping and sanitization

No escaping is performed. The custom prompt is treated as opaque text passed
directly into the system prompt string. Rationale:

- The user controls their own config file; there is no injection risk from
  untrusted input.
- The system prompt is never rendered as HTML or evaluated as code.
- Stripping characters would break legitimate instructions (e.g., backticks in
  "use \`jq\` for JSON parsing").

The only processing is **whitespace normalization**: leading and trailing
whitespace is stripped with `.strip()` so that empty or whitespace-only values
are treated as "no custom prompt."

---

## Technical Design

### Modules changed

| Module | Change |
|--------|--------|
| `config.py` | Add `custom_prompt: str = ""` to the `Config` dataclass. Add env var lookup `AT_CMD_CUSTOM_PROMPT` in `load_config`. |
| `llm.py` | Update `build_system_prompt` to accept the custom prompt string and append it when non-empty. |
| `cli.py` | Pass `config.custom_prompt` to `build_system_prompt`. |
| `tui.py` | Add a text-area widget for `custom_prompt` in the config editor (if feasible within the existing layout; otherwise defer to a follow-up). |

### `config.py` changes

```python
@dataclass
class Config:
    # ... existing fields ...
    custom_prompt: str = ""
```

In `load_config`:

```python
cfg.custom_prompt = os.environ.get("AT_CMD_CUSTOM_PROMPT", cfg.custom_prompt)
```

### `llm.py` changes

`build_system_prompt` gains an optional parameter:

```python
def build_system_prompt(ctx: ShellContext, custom_prompt: str = "") -> str:
    base = (
        f"You are a shell command translator for {ctx.shell} on {ctx.os_name}.\n"
        f"Working directory: {ctx.cwd}\n"
        # ... rest of existing prompt ...
    )
    if custom_prompt.strip():
        base += f"\n\nAdditional user instructions:\n{custom_prompt.strip()}"
    return base
```

The header "Additional user instructions:" is added so the LLM can
distinguish the static contract from user-supplied guidance. This also makes
debugging easier when logging prompts.

### `cli.py` changes

```python
system_prompt = build_system_prompt(shell_ctx, custom_prompt=config.custom_prompt)
```

Single call-site change. No new imports needed.

---

## Examples of Useful Custom Prompts

| Use case | `custom_prompt` value |
|----------|----------------------|
| Modern CLI tools | `"Prefer fd over find, ripgrep (rg) over grep, bat over cat, eza over ls."` |
| POSIX portability | `"Use only POSIX-compliant commands. Do not use bash-specific syntax."` |
| Docker workflow | `"Wrap commands in docker exec -it mycontainer when they involve the app."` |
| Package manager | `"Use pnpm instead of npm or yarn."` |
| Safety | `"Never use rm -rf without prompting. Prefer trash-cli for deletions."` |
| Verbosity | `"Always use long flags (--recursive instead of -r) for readability."` |
| Language / locale | `"Output file sizes in SI units (MB, GB) rather than binary (MiB, GiB)."` |
| SSH context | `"All commands will be run on a remote CentOS 7 host via SSH."` |

---

## Edge Cases

### Empty or whitespace-only prompt

Treated as "no custom prompt." The system prompt is identical to today's
output. No "Additional user instructions:" header is appended.

### Very long prompt

No hard character limit is enforced by at-cmd. However:

- LLM backends have context-window limits. An extremely long custom prompt
  could crowd out the user's actual request or hit token limits.
- A soft warning is logged to stderr if `len(custom_prompt) > 500` characters:
  `"Warning: custom_prompt is very long ({n} chars); this may reduce response quality."`
- This threshold is advisory, not blocking. The prompt is still sent in full.

### Conflicting instructions

If the custom prompt contradicts the core system prompt (e.g.,
`"Return three lines instead of two"`), the core contract may break. This is
the user's responsibility. Mitigations:

- The core JSON format instruction comes **first** in the prompt, giving it
  positional priority in most LLMs.
- The "Additional user instructions:" header signals these are supplementary,
  not overrides.
- Documentation in `README.md` and the config TUI should note: "Your custom
  prompt should not override the output format (JSON with command +
  description fields)."

### Special characters

No escaping is needed. The custom prompt is concatenated into a plain string
that is sent as-is to the LLM. Newlines, quotes, and Unicode are all valid.

### TOML quoting

Users must follow TOML string rules. A single-line value with internal quotes
needs escaping (`\"`) or use of literal strings (`'...'`). Multi-line values
use triple quotes. This is standard TOML behavior, not specific to at-cmd.

---

## Testing Strategy

All tests go in `tests/test_config.py` and `tests/test_llm.py` (or a new
`tests/test_custom_prompt.py` if preferred for isolation).

### Config loading tests (`test_config.py`)

| Test | Description |
|------|-------------|
| `test_custom_prompt_default_empty` | Default config has `custom_prompt == ""`. |
| `test_custom_prompt_from_toml` | A config file with `custom_prompt = "use fd"` loads correctly. |
| `test_custom_prompt_from_env` | `AT_CMD_CUSTOM_PROMPT` env var overrides the TOML value. |
| `test_custom_prompt_env_overrides_toml` | Env var takes precedence when both are set. |
| `test_custom_prompt_multiline_toml` | Triple-quoted TOML string loads with newlines preserved. |
| `test_save_config_round_trip` | `save_config` followed by `load_config` preserves the custom prompt. |

### System prompt tests (`test_llm.py`)

| Test | Description |
|------|-------------|
| `test_build_system_prompt_no_custom` | Empty custom prompt produces the original system prompt (no "Additional" section). |
| `test_build_system_prompt_with_custom` | Non-empty custom prompt appends the "Additional user instructions:" block. |
| `test_build_system_prompt_whitespace_only` | Whitespace-only custom prompt is treated as empty. |
| `test_build_system_prompt_preserves_newlines` | Multi-line custom prompt is included verbatim (after strip). |
| `test_build_system_prompt_long_prompt_warning` | Custom prompt over 500 chars triggers a stderr warning (captured via `capsys`). |

### Integration/CLI test (`test_cli.py`)

| Test | Description |
|------|-------------|
| `test_translate_passes_custom_prompt` | Mock the backend and verify the system prompt received by the backend includes the custom text from config. |

### Edge case tests

| Test | Description |
|------|-------------|
| `test_custom_prompt_special_characters` | Prompt containing quotes, backticks, and newlines is passed through unchanged. |
| `test_custom_prompt_unicode` | Non-ASCII text (e.g., CJK characters) is handled correctly. |

---

## Out of Scope

The following are explicitly **not** part of this feature:

- **Per-request prompt overrides via CLI flag.** The custom prompt is a
  persistent preference. Temporary adjustments belong in the natural-language
  request itself (e.g., `@ use POSIX find to locate large files`).

- **Prompt templates or variables.** The custom prompt is static free text.
  There are no `{shell}` or `{os}` placeholders resolved at runtime. If this
  need arises, it should be a separate feature.

- **Multiple prompt profiles.** There is one `custom_prompt` field. Switching
  between "work" and "personal" profiles is out of scope; that can be handled
  with env var overrides or separate config files in a future feature.

- **Installed-tool auto-detection.** The spec explicitly notes this is a
  lighter-weight alternative. Auto-detection (`which fd`, parsing `$PATH`,
  etc.) is a separate backlog item.

- **Validation of prompt content.** at-cmd does not parse or lint the custom
  prompt for correctness or conflicts with the core contract. The user is
  responsible for the content.

- **TUI editor for custom prompt.** Adding a multi-line text area to the
  Textual config TUI is desirable but may require layout changes. If it cannot
  be done cleanly in the initial implementation, it will be deferred.
