# Inline Explanation Mode

**Version:** 0.1
**Date:** 2026-03-23
**Status:** Draft
**Backlog ref:** Tactical Backlog > Inline Explanation Mode

---

## Overview

at-cmd translates natural language into shell commands, but the target user often cannot read what the resulting command actually does. Explanation mode closes this gap: it takes a shell command and returns a structured, plain-English breakdown of every token. This turns each interaction into a micro-lesson, building confidence and teaching CLI patterns over time.

Three surfaces expose the feature:

1. **`?` keypress** in the editable prompt after translation
2. **`--explain` flag** on the translate command
3. **`at-cmd explain "<command>"`** as a standalone subcommand

---

## Motivation

- The core safety guarantee of at-cmd is "the user always reviews before executing." But review is only meaningful if the user understands what they are reading.
- Users who are learning the CLI benefit from token-level breakdowns far more than a 10-word summary.
- Existing tools like `explainshell.com` require leaving the terminal. Inline explanation keeps the user in flow.

---

## User Stories

| ID | As a... | I want to... | So that... |
|----|---------|-------------|------------|
| US-1 | CLI novice | press `?` after at-cmd translates a command | I can understand each part before I run it |
| US-2 | Developer reviewing a script | run `at-cmd explain "find . -name '*.log' -mtime +30 -delete"` | I get a quick breakdown without leaving my terminal |
| US-3 | User who received a command from a colleague | pipe a command into `at-cmd explain` | I can verify what it does before running it |
| US-4 | Power user | add `--explain` to a translate call | I get the command and the explanation in one step |

---

## Detailed UX

### Surface 1: `?` keypress in the editable prompt

After a successful translation, the user sees the standard editable prompt:

```
  # Find JPG files larger than 5MB in the current directory
> find . -name '*.jpg' -size +5M
```

Pressing `?` at this point triggers an explanation. The command text is sent to the LLM with the explanation prompt. While waiting, a spinner appears on stderr. The explanation renders below the description as dim text:

```
  # Find JPG files larger than 5MB in the current directory

  find           Search for files and directories
    .            Start from the current directory
    -name '*.jpg'  Match filenames ending in .jpg
    -size +5M    Only files larger than 5 megabytes

> find . -name '*.jpg' -size +5M
```

After the explanation renders, the cursor returns to the editable prompt. The user can still edit, execute, or cancel as normal.

**Key detail:** The `?` keypress is only intercepted when the cursor is at position 0 (empty input or start of line) or when readline detects it as a standalone keypress rather than part of editing. If the user is typing `?` as part of a command (e.g., editing to add `--help`), it must pass through normally. Implementation: bind `?` only when the buffer exactly matches the pre-filled command (i.e., the user has not edited it yet), or use a different trigger such as `Alt+?` / `F1` to avoid ambiguity. The chosen binding should be documented in the explanation output itself (e.g., a dim hint: `press ? for explanation`).

### Surface 2: `--explain` flag on translate

```
$ @ --explain find large jpg files
  # Find JPG files larger than 5MB in the current directory

  find           Search for files and directories
    .            Start from the current directory
    -name '*.jpg'  Match filenames ending in .jpg
    -size +5M    Only files larger than 5 megabytes

> find . -name '*.jpg' -size +5M
```

The `--explain` flag triggers the explanation LLM call automatically after translation, before presenting the editable prompt. This costs one additional LLM round trip but requires no extra keypress.

When combined with `--json`, the output includes an `explanation` field:

```json
{
  "command": "find . -name '*.jpg' -size +5M",
  "description": "Find JPG files larger than 5MB in the current directory",
  "explanation": [
    {"token": "find", "description": "Search for files and directories"},
    {"token": ".", "description": "Start from the current directory"},
    {"token": "-name '*.jpg'", "description": "Match filenames ending in .jpg"},
    {"token": "-size +5M", "description": "Only files larger than 5 megabytes"}
  ]
}
```

### Surface 3: `at-cmd explain "<command>"` standalone subcommand

```
$ at-cmd explain "tar -czf backup.tar.gz ./logs"

  tar              Create or extract archive files
    -c             Create a new archive
    -z             Compress with gzip
    -f backup.tar.gz  Write to this output file
    ./logs         The directory to archive
```

This accepts a command string as a positional argument. It does not translate anything -- it only explains.

Stdin support for piping:

```
$ echo "tar -czf backup.tar.gz ./logs" | at-cmd explain -
```

When the argument is `-`, the command is read from stdin. This enables integration with other tools.

Options:

| Flag | Description |
|------|-------------|
| `--json` | Output structured JSON instead of formatted text |
| `--shell <name>` | Override shell context (affects how the command is interpreted) |
| `--backend <name>` | Override LLM backend |
| `--model <name>` | Override model |

---

## Explanation Format

### Token-by-token breakdown

The explanation groups the command into logical tokens. A "token" is not necessarily a single word -- it is a semantic unit that a user would think of as one piece. Examples:

| Command fragment | Token grouping |
|-----------------|----------------|
| `find .` | `find` + `.` |
| `-name '*.jpg'` | single token: `-name '*.jpg'` |
| `-size +5M` | single token: `-size +5M` |
| `\| grep -v test` | `\|` + `grep` + `-v` + `test` |
| `2>/dev/null` | single token: `2>/dev/null` |
| `$(command)` | single token with explanation of subcommand |

The LLM determines token boundaries. The prompt instructs it to group flags with their arguments and to treat pipes/redirections as separate tokens.

### Color coding (terminal output)

| Element | ANSI style |
|---------|-----------|
| Token (command/subcommand names) | Bold white |
| Token (flags and arguments) | Default (normal weight) with 2-space indent |
| Description text | Dim (ANSI `\033[2m`) |
| Pipe / redirect operators | Yellow |
| Dangerous tokens (`rm`, `-rf`, `sudo`, `dd`) | Red bold |

Example with annotations:

```
  find             Search for files and directories       <- bold white + dim desc
    .              Start from the current directory       <- normal + dim desc
    -name '*.jpg'  Match filenames ending in .jpg         <- normal + dim desc
    -size +5M      Only files larger than 5 megabytes     <- normal + dim desc
```

When `--json` is used, no color is applied; the structured data is returned instead.

### Output layout

- The explanation block is indented 2 spaces from the left margin.
- Token names are left-aligned in a column. The column width is determined by the longest token plus 2 spaces of padding.
- Descriptions start at the same column for visual alignment.
- Pipe segments are separated by a blank line with the pipe operator on its own line:

```
  find . -name '*.log' -mtime +30
    find           Search for files and directories
    .              Start from the current directory
    -name '*.log'  Match filenames ending in .log
    -mtime +30     Modified more than 30 days ago

  | wc -l
    wc             Count lines, words, or bytes
    -l             Count lines only
```

---

## LLM Prompt Design

### Explanation system prompt

```
You are a shell command explainer for {shell} on {os}.
The user will provide a shell command.
Return a token-by-token explanation as a series of lines.
Each line must have EXACTLY this format:

TOKEN ||| DESCRIPTION

Rules:
- TOKEN is a logical piece of the command (a subcommand, flag, flag+argument pair, filename, redirection, or pipe)
- DESCRIPTION is a plain-English explanation in 10 words or fewer
- Group flags with their arguments when they form a unit (e.g., "-name '*.jpg'" is one token)
- Treat pipe operators (|) as their own token with description "Pipe output to the next command"
- Treat redirections (>, >>, 2>, etc.) with their target as one token
- Do NOT include backticks, markdown, or numbering
- Do NOT include the overall command as a token -- only its parts
- One token per line, in the order they appear in the command
```

### Parsing the response

The `|||` delimiter is chosen because it is unlikely to appear in shell commands or descriptions. Parsing logic:

1. Strip markdown fences and backticks (reuse existing `sanitize.py` helpers).
2. Split on newlines.
3. For each non-empty line, split on `|||` and strip whitespace from both parts.
4. Discard lines that do not contain the delimiter (LLM preamble, etc.).
5. Return a list of `ExplainToken(token: str, description: str)` dataclass instances.

If parsing produces zero tokens, raise `ExplainError` with a message indicating the LLM response could not be parsed.

---

## Technical Design

### New module: `src/at_cmd/explain.py`

```
explain.py
  - ExplainToken (dataclass): token, description
  - ExplainError (Exception)
  - build_explain_prompt(ctx: ShellContext) -> str
  - parse_explanation(raw: str) -> list[ExplainToken]
  - format_explanation(tokens: list[ExplainToken], use_color: bool) -> str
  - format_explanation_json(tokens: list[ExplainToken]) -> list[dict]
```

`build_explain_prompt` returns the system prompt for explanation calls. `parse_explanation` handles sanitization and structured extraction. `format_explanation` renders the aligned, color-coded terminal output. `format_explanation_json` returns the list-of-dicts form for JSON mode.

### New subcommand: `at-cmd explain`

Added to `cli.py` as a visible subcommand on the `main` Click group:

```python
@main.command("explain")
@click.argument("command", required=False)
@click.option("--json-output", "--json", "json_mode", is_flag=True)
@click.option("--shell", "shell_name", default=None)
@click.option("--backend", default=None)
@click.option("--model", default=None)
def explain_cmd(command, json_mode, shell_name, backend, model):
    ...
```

If `command` is `None` or `"-"`, read from stdin. Otherwise, use the positional argument.

The subcommand name `explain` must be added to the known commands so `_DefaultToTranslate` does not route it to `translate`.

### Integration into the editable prompt (`?` keypress)

This requires modifying the readline interaction in `translate_cmd`. The approach:

1. After the command is pre-filled in the readline buffer, register a custom readline key binding for `?` (or `Alt+?`).
2. When triggered, the binding function:
   a. Reads the current buffer contents.
   b. Calls the LLM with the explanation prompt.
   c. Prints the explanation to stderr (above the prompt).
   d. Returns the cursor to the editable prompt.

**Alternative (simpler MVP):** Instead of a live readline binding, check after the user submits whether they typed `?` as the entire input. If so, explain the pre-filled command and re-present the prompt. This avoids readline complexity at the cost of requiring Enter after `?`.

Recommended approach for v1: Use the simpler "type `?` + Enter" approach. Document it clearly. Move to a true readline binding in a follow-up.

### `--explain` flag on translate

Add `--explain` as a `click.option` on `translate_cmd`. When set:

1. After translation completes, make a second LLM call with the explanation prompt.
2. Render the explanation between the description and the editable prompt.
3. In JSON mode, include the `explanation` array in the output.

### Changes to existing modules

| Module | Change |
|--------|--------|
| `cli.py` | Add `explain` subcommand. Add `--explain` flag to `translate_cmd`. Add `?` handling in the readline loop. |
| `llm.py` | No changes needed. `BackendFn` already accepts arbitrary system/user prompts. |
| `config.py` | No changes needed for v1. |
| `sanitize.py` | No changes. The markdown stripping helpers may be extracted into shared utilities if needed, but the existing function can be called from `explain.py`. |

### Request flow for `at-cmd explain`

```
cli.py (explain_cmd)
  -> detect.py (OS/shell context)
  -> config.py (layered config)
  -> explain.py (build_explain_prompt)
  -> llm.py (backend call with explain prompt + command as user prompt)
  -> explain.py (parse_explanation, format_explanation)
  -> stdout
```

### Request flow for `?` in editable prompt

```
cli.py (translate_cmd, user types "?" + Enter)
  -> explain.py (build_explain_prompt)
  -> llm.py (backend call)
  -> explain.py (parse_explanation, format_explanation)
  -> stderr (render explanation)
  -> re-present editable prompt with same command pre-filled
```

---

## Edge Cases

### Very long commands

Commands exceeding ~200 characters may produce many tokens. The explanation should still render correctly. No truncation is applied -- the user scrolls if needed. In JSON mode, all tokens are included regardless of count.

### Multi-line commands (backslash continuations)

Commands like:

```bash
docker run \
  -v /data:/data \
  -p 8080:80 \
  nginx
```

These arrive as a single string with embedded newlines or literal backslashes. The LLM prompt handles this naturally since it sees the full command. The explanation groups tokens logically regardless of line breaks.

### Pipes and compound commands

Commands with pipes (`|`), logical operators (`&&`, `||`), and semicolons (`;`) are broken into segments. Each segment is explained with the operator as a separator token. Example:

```
  grep -r "TODO" .       Search for "TODO" recursively in current directory
  |                      Pipe output to the next command
  sort                   Sort lines alphabetically
  |                      Pipe output to the next command
  uniq -c                Count consecutive duplicate lines
```

### Subshells and command substitution

Tokens like `$(date +%Y)` or backtick substitutions are treated as single tokens. The description explains what the substitution evaluates to. Deeply nested substitutions get a single summary rather than recursive breakdown.

### Empty or trivial commands

If the user asks to explain `ls` or `cd`, the explanation may be very short (1-2 tokens). This is fine. The LLM should still produce valid output.

### Commands in a different shell

If the user passes `--shell fish` but provides a bash command, the explanation may be inaccurate. This is documented as a known limitation. The shell context affects how the LLM interprets syntax.

### LLM returns unusable explanation

If `parse_explanation` returns zero tokens, display a fallback message: `Could not generate explanation for this command.` Do not crash.

### `?` character in actual commands

The `?` glob character is valid in shell commands (e.g., `ls file?.txt`). The "type `?` + Enter" approach avoids ambiguity because it only triggers when the entire input is exactly `?`. If the user edits the command to include `?`, normal execution proceeds. If a future version uses a readline binding, `Alt+?` or `F1` should be used instead.

---

## Testing Strategy

### Unit tests (`tests/test_explain.py`)

**parse_explanation:**

| Test | Input | Expected |
|------|-------|----------|
| Happy path | `"find ||| Search for files\n. ||| Current directory"` | 2 ExplainToken objects |
| Markdown fences | Input wrapped in triple backticks | Tokens extracted correctly |
| Missing delimiter | `"This is just text"` | Empty list or ExplainError |
| Empty input | `""` | ExplainError raised |
| Extra whitespace | `"  find  |||  Search for files  "` | Trimmed token and description |
| Pipe token | `"\| ||| Pipe output to next command"` | Token is `\|` |

**format_explanation:**

| Test | Scenario | Assertion |
|------|----------|-----------|
| Alignment | Tokens of varying length | All descriptions start at the same column |
| Color codes | `use_color=True` | Output contains ANSI escape sequences |
| No color | `use_color=False` | Output contains no ANSI escapes |
| Single token | One-token input | Renders without error |

**build_explain_prompt:**

| Test | Scenario | Assertion |
|------|----------|-----------|
| Contains shell name | zsh context | Prompt includes "zsh" |
| Contains OS | macOS context | Prompt includes "macOS" |
| Contains format instructions | Any context | Prompt includes `\|\|\|` delimiter instruction |

### Integration tests

| Test | Scenario | Assertion |
|------|----------|-----------|
| explain subcommand (mocked backend) | `at-cmd explain "ls -la"` | Exits 0, output contains token breakdown |
| explain with --json (mocked backend) | `at-cmd explain --json "ls -la"` | Valid JSON with `explanation` array |
| explain with stdin | Pipe input | Same output as positional argument |
| translate --explain (mocked backend) | `@ --explain list files` | Output contains both description and explanation |
| Bad backend response | Backend returns garbage | Graceful error message, non-zero exit |

### Manual testing checklist

- [ ] `at-cmd explain "find . -name '*.py' -mtime -7"` produces readable output
- [ ] `at-cmd explain "docker run -d -p 80:80 --name web nginx"` handles flags with arguments
- [ ] `at-cmd explain "cat access.log | grep 404 | awk '{print $1}' | sort | uniq -c | sort -rn | head"` handles long pipe chains
- [ ] `echo "rm -rf /tmp/old" | at-cmd explain -` reads from stdin
- [ ] `@ --explain compress all log files` shows explanation before editable prompt
- [ ] Typing `?` + Enter in the editable prompt triggers explanation and returns to prompt
- [ ] Color output renders correctly in terminals that support ANSI
- [ ] `--json` output is valid and parseable

---

## Out of Scope

The following are explicitly excluded from this feature:

- **Recursive/interactive drill-down**: Clicking or selecting a token to get a deeper explanation. The single-pass token breakdown is sufficient for v1.
- **Caching explanations**: Identical commands could be cached to avoid repeat LLM calls. Deferred to a general caching feature.
- **Offline/local explanations**: A local database of common commands and flags (like a built-in `tldr`). This would remove the LLM dependency for simple commands but is a separate effort.
- **Explanation of command output**: Explaining what a command printed after execution. This feature only explains the command itself.
- **Shell integration for explain**: No keybinding is generated in `init.py` for explain mode. The `?` trigger only works within at-cmd's own editable prompt, not as a general shell widget.
- **Streaming explanations**: Rendering tokens as they arrive from the LLM. Deferred to a general streaming feature.
- **Internationalization**: Explanations are English-only for v1.
- **Syntax highlighting of the command itself**: The explanation uses color for structure, but the command tokens are not syntax-highlighted as shell code.
