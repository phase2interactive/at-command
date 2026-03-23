# Multi-Candidate Picker

**Status:** Proposed
**Date:** 2026-03-23
**Depends on:** Core translate flow (cli.py, llm.py, sanitize.py)

---

## Overview

Today `at-cmd` returns a single command for every request. If the command is wrong or uses an unfamiliar tool, the user must cancel and rephrase. The multi-candidate picker lets the user request N alternative commands in a single LLM call and choose the best one from a list before it lands in the editable buffer.

### Motivation

- Different users have different tool preferences (`find` vs `fd`, `grep` vs `rg`, `curl` vs `wget`).
- The LLM's first answer is often adequate but not optimal. Showing alternatives avoids the cancel-retype loop.
- Beginners benefit from seeing multiple approaches side by side -- it teaches them that problems have more than one CLI solution.

---

## User Stories

1. **As a user**, I want to run `@ find large files --candidates 3` and see three alternative commands so I can pick the one I understand best.
2. **As a user**, I want the picker to use `fzf` when it is installed so I get fuzzy-searchable selection with a preview of each description.
3. **As a user**, I want a usable fallback picker when `fzf` is not available so the feature works everywhere.
4. **As a user**, I want to set a default candidate count in my config so I do not have to type `--candidates` every time.
5. **As a user**, I want inline mode to also support multi-candidate selection so the workflow is consistent regardless of mode.
6. **As a user**, I want `--json` output to include all candidates so scripts and integrations can consume the full set.

---

## Detailed UX

### Submit Mode

#### Numbered List (fallback picker)

When `fzf` is not available or the user has configured `picker = "builtin"`:

```
$ @ compress the logs --candidates 3
  translating...

  1) tar czf logs.tar.gz *.log
     # Archive all .log files into a gzipped tarball

  2) gzip *.log
     # Compress each .log file in place with gzip

  3) zip logs.zip *.log
     # Create a zip archive of all .log files

  Pick [1-3, q to cancel]: 2

  # Compress each .log file in place with gzip
> gzip *.log
```

Behavior:
- Candidates are numbered starting at 1.
- Each candidate shows the command in normal text and the description as dim text on the next line.
- The prompt accepts a single digit or `q`/Ctrl-C to cancel.
- After selection, the chosen command lands in the standard editable readline prompt exactly as it does today for single-candidate mode.
- Invalid input (out of range, non-numeric) re-prompts without clearing the list.

#### fzf Picker

When `fzf` is found on `$PATH` (or at the path specified by `fzf_path` config) and the user has not set `picker = "builtin"`:

```
$ @ compress the logs --candidates 3
  translating...

> tar czf logs.tar.gz *.log  --  Archive all .log files into a gzipped tarball
  gzip *.log  --  Compress each .log file in place with gzip
  zip logs.zip *.log  --  Create a zip archive of all .log files
  3/3
>
```

Behavior:
- Each line sent to fzf is formatted as `{command}  --  {description}`.
- fzf is invoked with `--height=~10 --layout=reverse --ansi --no-multi`.
- The `--preview` flag is not used (commands are short enough to read inline).
- On selection, the command portion (everything before `  --  `) is extracted and placed in the editable prompt.
- On cancel (Esc / Ctrl-C in fzf), the entire translate operation is cancelled.

### Inline Mode

Inline mode always uses the numbered-list approach rendered to stderr, because the shell buffer can only hold one command at a time. The flow:

1. User types `@ compress the logs` and hits the inline hotkey.
2. Shell buffer shows spinner.
3. Numbered list appears on stderr (same format as submit-mode fallback).
4. User picks a number.
5. The chosen command replaces the shell buffer.
6. Undo (Ctrl-Z) restores the original `@ compress the logs` text.

If `--candidates 1` (the default), inline mode behaves exactly as it does today -- no picker is shown.

### JSON Mode

When `--json` is combined with `--candidates N`:

```json
{
  "candidates": [
    {"command": "tar czf logs.tar.gz *.log", "description": "Archive all .log files into a gzipped tarball"},
    {"command": "gzip *.log", "description": "Compress each .log file in place with gzip"},
    {"command": "zip logs.zip *.log", "description": "Create a zip archive of all .log files"}
  ]
}
```

When `--candidates 1` (or omitted), the output format remains unchanged for backward compatibility:

```json
{"command": "tar czf logs.tar.gz *.log", "description": "Archive all .log files into a gzipped tarball"}
```

---

## LLM Prompt Design

### Modified System Prompt

When `candidates > 1`, the system prompt returned by `build_system_prompt` changes. A new function `build_multi_candidate_system_prompt` (or an optional parameter on the existing function) produces:

```
You are a shell command translator for {shell} on {os}.
Working directory: {cwd}
The user will describe what they want in natural language.
Return EXACTLY {N} alternatives, each as two lines:
Line 1: A {shell} command (no backticks, no markdown, one line, use appropriate chaining for {shell})
Line 2: A brief description (10 words max) of what the command does

Separate each alternative with a blank line.
Each alternative should use a DIFFERENT approach, tool, or flag combination.
Do NOT repeat the same command with trivial variations.
```

### Why a Blank-Line Separator

A blank line between candidates is unambiguous and easy to parse. The existing single-candidate contract (two consecutive non-blank lines) is a subset of this format, so the parser can handle both with minimal branching.

### Example LLM Response (raw)

```
tar czf logs.tar.gz *.log
Archive all .log files into a gzipped tarball

gzip *.log
Compress each .log file in place with gzip

zip logs.zip *.log
Create a zip archive of all .log files
```

---

## Response Parsing

### New Function: `sanitize_multi_response`

Located in `sanitize.py` alongside the existing `sanitize_response`.

```python
def sanitize_multi_response(raw: str, expected: int) -> list[tuple[str, str]]:
    """Clean LLM output and extract multiple (command, description) pairs.

    Args:
        raw: Raw text from the LLM backend.
        expected: Number of candidates requested.

    Returns:
        list[tuple[str, str]]: List of (command, description) pairs.

    Raises:
        SanitizeError: If no valid candidates can be extracted.
    """
```

Algorithm:

1. Strip the full response of leading/trailing whitespace.
2. Remove markdown code fences (same regex as `sanitize_response`).
3. Split on blank lines (`\n\n` or `\n\s*\n`) to get candidate blocks.
4. For each block, apply the existing `_clean_command` to line 1 and strip line 2 for the description.
5. Discard any block that yields an empty command after cleaning.
6. Deduplicate: if two candidates have identical commands (after cleaning), keep only the first.
7. Return up to `expected` candidates. If fewer remain, return what we have (see edge cases below).

### Backward Compatibility

`sanitize_response` is unchanged. When `candidates == 1`, the existing code path is used. The new function is only called when `candidates > 1`.

---

## Technical Design

### Modules That Change

| Module | Change |
|--------|--------|
| `cli.py` | Add `--candidates` option to `translate_cmd`. Add picker logic (fzf and builtin). Modify JSON output when candidates > 1. |
| `llm.py` | Add `candidates` parameter to `build_system_prompt` (or new builder function). No change to `BackendFn` protocol -- the backend still returns a single string; multi-candidate parsing is the caller's job. |
| `sanitize.py` | Add `sanitize_multi_response` function. |
| `config.py` | Add `candidates: int = 1` and `picker: str = "auto"` and `fzf_path: str = ""` fields to `Config`. Wire up `AT_CMD_CANDIDATES`, `AT_CMD_PICKER`, `AT_CMD_FZF_PATH` env vars. |
| `init.py` | No changes required. The shell integration passes `--candidates` through if the user includes it in their request. |

### New Module: `picker.py`

A small module that encapsulates candidate selection UI.

```python
# src/at_cmd/picker.py

def pick_candidate(
    candidates: list[tuple[str, str]],
    use_fzf: bool,
    fzf_path: str,
) -> tuple[str, str] | None:
    """Present candidates to the user and return the chosen one.

    Args:
        candidates: List of (command, description) pairs.
        use_fzf: Whether to use fzf for selection.
        fzf_path: Path to fzf binary (empty string means find on PATH).

    Returns:
        The selected (command, description) tuple, or None if cancelled.
    """
```

### Data Flow (candidates > 1)

```
cli.py: translate_cmd
  |
  +--> detect_context(), load_config()
  |
  +--> get_backend(config) -> backend_fn
  |
  +--> build_system_prompt(ctx, candidates=N)
  |      (includes multi-candidate instructions)
  |
  +--> backend_fn(system_prompt, user_prompt) -> raw: str
  |
  +--> sanitize_multi_response(raw, expected=N) -> list[(cmd, desc)]
  |
  +--> picker.pick_candidate(candidates, use_fzf, fzf_path) -> (cmd, desc) | None
  |
  +--> if selection: editable readline prompt with cmd
  |    if None:      exit (user cancelled)
```

### fzf Detection

In `picker.py`, determine whether to use fzf:

1. If config `picker == "builtin"`, always use the numbered-list fallback.
2. If config `picker == "fzf"`, require fzf and error if not found.
3. If config `picker == "auto"` (default), use fzf when found on PATH (or at `fzf_path`), otherwise fall back to the builtin picker.

Detection uses `shutil.which(fzf_path or "fzf")`.

### fzf Invocation

```python
proc = subprocess.run(
    [fzf_bin, "--height=~10", "--layout=reverse", "--ansi", "--no-multi"],
    input="\n".join(f"{cmd}  --  {desc}" for cmd, desc in candidates),
    capture_output=True,
    text=True,
)
```

Parse the selected line by splitting on `"  --  "` and taking the first element.

---

## Configuration

### New Config Fields

| Field | Type | Default | Env Var | Description |
|-------|------|---------|---------|-------------|
| `candidates` | int | `1` | `AT_CMD_CANDIDATES` | Default number of candidates to request. |
| `picker` | str | `"auto"` | `AT_CMD_PICKER` | Picker mode: `"auto"`, `"fzf"`, or `"builtin"`. |
| `fzf_path` | str | `""` | `AT_CMD_FZF_PATH` | Custom path to fzf binary. Empty means use PATH. |

### TOML Example

```toml
candidates = 3
picker = "auto"
fzf_path = "/opt/homebrew/bin/fzf"
```

### CLI Flag Precedence

The `--candidates` flag on the command line overrides the config value. There is no CLI flag for `picker` or `fzf_path` -- those are config-only.

### Validation

- `candidates` must be between 1 and 10 inclusive. Values outside this range produce a user-facing error.
- `picker` must be one of `"auto"`, `"fzf"`, `"builtin"`. Other values produce a user-facing error.

---

## Edge Cases

### LLM Returns Fewer Candidates Than Requested

This is expected behavior, not an error. If the user requests 5 candidates but the LLM returns 3 valid ones, show all 3. Do not re-call the LLM to fill the gap. If the LLM returns zero valid candidates, raise `SanitizeError` as today.

### LLM Returns More Candidates Than Requested

Truncate to the requested count. Take the first N after parsing and deduplication.

### Duplicate Candidates

After sanitization, if two candidates have the same command string (case-sensitive exact match), discard the later duplicate. Descriptions are not considered for deduplication -- two commands are duplicates only if their command lines match.

### LLM Ignores Multi-Candidate Instructions

Some models may ignore the multi-candidate system prompt and return a single two-line response. The parser handles this gracefully: it returns a list with one element. If `candidates > 1` but only one candidate is returned, skip the picker and go directly to the editable prompt (same as single-candidate flow).

### fzf Not Installed and picker = "fzf"

Print a clear error to stderr: `Error: fzf not found. Install fzf or set picker = "auto" in config.` Exit with code 1.

### Single Candidate Requested

When `candidates == 1` (the default), the entire multi-candidate code path is skipped. The existing `sanitize_response` and direct-to-readline flow is used unchanged. No picker is shown. This preserves full backward compatibility.

### Candidate With Multi-Line Command

If the LLM returns a candidate whose "command" spans multiple lines (e.g., a heredoc), the parser treats only the first line as the command. This matches the existing single-candidate contract. Multi-line commands are out of scope.

### Empty Description

If a candidate block has only one line (command but no description), the description defaults to an empty string, matching the existing `sanitize_response` behavior.

---

## Testing Strategy

All tests in `tests/test_picker.py` and `tests/test_sanitize.py`.

### sanitize_multi_response

| Test | Input | Expected |
|------|-------|----------|
| Happy path: 3 candidates | Three two-line blocks separated by blank lines | List of 3 (command, description) tuples |
| Markdown fences around entire response | Fenced block with 3 candidates | Fences stripped, 3 tuples returned |
| Fewer candidates than requested | 2 blocks when 3 expected | List of 2 tuples (no error) |
| More candidates than requested | 4 blocks when 3 expected | List of 3 tuples (truncated) |
| Duplicate commands | 3 blocks, two with identical commands | List of 2 tuples (deduped) |
| Single candidate returned when 3 expected | One two-line block | List of 1 tuple |
| Empty response | Empty string | Raises SanitizeError |
| All candidates invalid after cleaning | Blocks with only whitespace/backticks | Raises SanitizeError |
| Missing description on one candidate | One block with command only, others complete | Tuple has empty description string |

### picker.pick_candidate (builtin)

| Test | Scenario | Expected |
|------|----------|----------|
| Valid selection | Simulated input "2\n" | Returns second candidate |
| Cancel with q | Simulated input "q\n" | Returns None |
| Out-of-range input then valid | Simulated input "9\n2\n" | Re-prompts, then returns second candidate |
| Single candidate | List with 1 item | Returns that item without prompting |
| KeyboardInterrupt | Ctrl-C during input | Returns None |

### picker.pick_candidate (fzf)

| Test | Scenario | Expected |
|------|----------|----------|
| fzf returns selection | Mock subprocess with stdout line | Returns parsed (command, description) |
| fzf cancelled (rc 130) | Mock subprocess with returncode 130 | Returns None |
| fzf not found | shutil.which returns None, picker="fzf" | Raises error |

### CLI Integration

| Test | Scenario | Expected |
|------|----------|----------|
| --candidates 3 with builtin picker | Mock backend + picker | Three candidates shown, selection works |
| --candidates 3 --json | Mock backend | JSON output contains candidates array |
| --candidates 1 --json | Mock backend | JSON output is flat object (backward compat) |
| --candidates 0 | Invalid value | Error message, exit 1 |
| --candidates 11 | Over max | Error message, exit 1 |

---

## Out of Scope

The following are explicitly excluded from this feature:

- **Streaming candidates**: Showing candidates as they arrive from the LLM. The entire response is awaited before parsing.
- **Parallel LLM calls**: Making N separate single-candidate calls instead of one multi-candidate call. This would multiply cost and latency.
- **Candidate ranking or scoring**: The order returned by the LLM is preserved as-is. No reranking.
- **Persistent candidate history**: Previously shown candidates are not cached or logged.
- **TUI-based picker**: No Textual or curses-based selection UI. The builtin picker is plain stdin/stdout; the rich option is fzf.
- **Multi-line command candidates**: Each candidate is a single-line command. Heredocs, multi-line pipelines, etc. are not supported.
- **Custom fzf flags**: The fzf invocation is hardcoded. Users cannot pass arbitrary fzf options.
- **Regenerate integration**: The "Regenerate / Try Again" feature (separate backlog item) is independent. It re-calls the LLM for a single new response. Multi-candidate requests all alternatives up front in one call.
