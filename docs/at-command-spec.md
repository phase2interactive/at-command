# Terminal `@` Command Specification

**Version:** 0.1
**Date:** 2026-03-20
**Status:** Draft

## Overview

The `@` command translates natural language into shell commands using an LLM backend. It provides an inline, Copilot-like preview experience directly in the terminal — the user describes intent in plain English, and the system presents an editable command with a brief description before execution.

## Core Concept

```
@ find all python files modified in the last week
```

The user types natural language. The system returns:

1. **The translated command** — placed in an editable buffer, ready to run or modify
2. **A brief description** — a short explanation of what the command does, rendered as dim/secondary text

The user never executes a command they haven't reviewed.

## Interaction Modes

### Mode 1: Submit (Enter)

The user types `@ <request>` and presses Enter. The system:

1. Shows a loading indicator (spinner or dim text)
2. Calls the LLM backend with the request and shell/OS context
3. Displays the description as dim text
4. Presents the translated command in an **editable input prompt** pre-filled with the result
5. The user can:
   - **Enter** — execute the command
   - **Edit** — modify the command before executing
   - **Cancel** (Ctrl+C / Escape) — abort without executing

```
$ @ find large jpg files
  ⏳ translating...
  # Find JPG files larger than 5MB in the current directory
❯ find . -name '*.jpg' -size +5M
```

### Mode 2: Inline (Keybinding)

The user types `@ <request>` and presses a keybinding (e.g., Alt+Space, Ctrl+Space). The system:

1. Replaces the command line buffer contents with a loading indicator
2. Calls the LLM backend
3. Replaces the buffer with the translated command (fully editable, cursor at end)
4. Displays the description as dim text below the command line
5. The user can:
   - **Enter** — execute the command
   - **Edit** — modify the command inline
   - **Undo** (Ctrl+Z) — restore the original `@ <request>` text
   - **Re-trigger** — press the keybinding again to regenerate

```
$ @ find large jpg files        ← user types this
  [Alt+Space]
$ find . -name '*.jpg' -size +5M   ← buffer replaced, editable
  # Find JPG files larger than 5MB   ← dim description below
```

## LLM Request Contract

### Input

The system prompt must include:

| Field | Description |
|-------|-------------|
| **Shell** | The user's current shell (fish, bash, zsh, powershell, etc.) |
| **OS** | The operating system (Linux, macOS, Windows) |
| **Working directory** | Current path (optional, for context) |
| **Available tools** | Optionally, a list of installed CLI tools for better suggestions |

### Output

The LLM must return exactly **two lines**:

```
Line 1: The shell command (no backticks, no markdown, single line)
Line 2: A brief description (10 words or fewer)
```

Example:

```
find . -name '*.py' -mtime -7
Find Python files modified in the last 7 days
```

### System Prompt Template

```
You are a shell command translator for {shell} on {os}.
The user will describe what they want in natural language.
Return EXACTLY two lines:
Line 1: The {shell} command (no backticks, no markdown, one line, use appropriate chaining for {shell})
Line 2: A brief description (10 words max) of what the command does
```

## Requirements

### Functional

| ID | Requirement |
|----|-------------|
| F1 | The `@` command MUST accept natural language as arguments |
| F2 | The translated command MUST be presented for review before execution |
| F3 | The user MUST be able to edit the command before executing |
| F4 | The user MUST be able to cancel without executing |
| F5 | A brief description MUST be shown alongside the command |
| F6 | The system MUST detect the current shell and OS automatically |
| F7 | The system MUST show a loading indicator during LLM calls |
| F8 | The inline mode MUST support undo back to the original input |

### Non-Functional

| ID | Requirement |
|----|-------------|
| NF1 | LLM response time should be under 3 seconds for typical requests |
| NF2 | The command MUST NOT execute automatically — user confirmation is always required |
| NF3 | The implementation MUST NOT modify shell history with synthetic entries |
| NF4 | The loading state MUST NOT block terminal input in inline mode (best effort) |
| NF5 | The implementation SHOULD work without root/admin privileges |

## LLM Backend

The spec is backend-agnostic. Any LLM that can follow the two-line output contract works. Example backends:

| Backend | Invocation |
|---------|------------|
| Claude Code CLI | `claude -p --model sonnet "<prompt>"` |
| OpenAI CLI | `openai api chat.completions.create -m gpt-4o ...` |
| Ollama (local) | `ollama run llama3 "<prompt>"` |
| Any HTTP API | `curl -s https://api.example.com/v1/chat/completions ...` |

Implementations SHOULD make the backend configurable via environment variable or config file.

## Shell-Specific Considerations

### Fish
- `@` cannot be autoloaded from `functions/@.fish` — define in `conf.d/`
- `commandline -r` only works inside key binding functions
- Use `read -c` for pre-filled editable prompts in submit mode
- Vi mode requires binding in `-M insert`

### Bash/Zsh
- Use `print -z` (zsh) or `read -e -i` (bash) for pre-filled editable prompts
- `bind -x` (bash) or `zle` widgets (zsh) for inline mode keybindings
- `READLINE_LINE` / `READLINE_POINT` for bash buffer manipulation

### PowerShell
- Use `PSReadLine` module for keybindings and buffer manipulation
- `[Microsoft.PowerShell.PSConsoleReadLine]::Replace()` for inline mode

## Security

- Commands are NEVER auto-executed — the user always has a review step
- The LLM prompt explicitly requests single-line commands without markdown wrapping
- Implementations SHOULD sanitize LLM output (strip backticks, markdown fences, leading `$` or `>`)
- The system does NOT send file contents, environment variables, or secrets to the LLM — only the natural language request and shell/OS metadata

## Future Considerations

See [docs/backlog/](backlog/) for detailed feature designs.
