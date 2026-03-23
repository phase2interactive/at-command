# Regenerate / Try Again

**Status:** Draft
**Date:** 2026-03-23
**Priority:** High
**Depends on:** Core translate flow (cli.py, init.py, llm.py)

---

## Overview

LLM responses are non-deterministic. The first translation is often close but not quite right -- wrong flags, wrong tool, overly complex piping. Today the only recourse is to Ctrl+C out of the editable prompt and retype the entire `@ <request>` from scratch. This feature adds a single-keypress regenerate action that fires a fresh LLM call with the same original request, replacing the current suggestion in place.

The main spec already mentions re-trigger in inline mode ("press the keybinding again to regenerate") but nothing is implemented and submit mode has no regenerate path at all. This spec covers both modes end to end.

---

## User Stories

1. **As a user in submit mode**, I want to press a key (e.g., Tab) while in the editable prompt to get a different command suggestion without retyping my request.

2. **As a user in inline mode**, I want to press my inline hotkey again (or a dedicated regenerate key) while viewing a translated command to get a fresh suggestion in the buffer.

3. **As a user who regenerated**, I want to undo back to the original `@ <request>` text, not to the previous (rejected) suggestion.

4. **As a user**, I want visual feedback that a regeneration is in progress so I know the tool is working.

5. **As a power user**, I want to configure which key triggers regenerate via `config.toml`.

---

## Detailed UX

### Submit Mode

**Current flow:**
```
$ @ find large jpg files
  # Find JPG files larger than 5MB in the current directory
> find . -name '*.jpg' -size +5M|          <-- cursor here, editable
```

**With regenerate:**
```
$ @ find large jpg files
  # Find JPG files larger than 5MB in the current directory
> find . -name '*.jpg' -size +5M|          <-- user presses Tab
  translating...                            <-- spinner on stderr
  # Locate JPEG images over 5MB recursively
> find . -type f \( -name '*.jpg' -o -name '*.jpeg' \) -size +5M|
```

**Trigger key:** Tab (default, configurable as `regenerate_key` in config.toml).

Tab is chosen because:
- It is universally available and easy to reach.
- In the readline editable prompt, Tab defaults to filename completion, which is not useful in this context since the buffer contains a shell command the user has not committed to yet.
- It does not conflict with Enter (execute), Ctrl+C (cancel), or arrow keys (edit).

**Behavior:**
1. User presses Tab while in the `readline` editable prompt.
2. The current prompt line is cleared and replaced with a spinner/status message on stderr.
3. A new LLM call is made with the **original natural language request** (not the current buffer contents).
4. On success: the new description replaces the old one on stderr, and the new command populates the editable prompt.
5. On failure: an error message is shown on stderr and the **previous** command is restored in the editable prompt so the user does not lose it.
6. The user can regenerate multiple times. Each regeneration replaces the last.
7. Enter, Ctrl+C, and Escape behave exactly as before.

### Inline Mode

**Current flow (after first translation):**
```
$ find . -name '*.jpg' -size +5M|         <-- buffer replaced, editable
  # Find JPG files larger than 5MB         <-- dim description
```

**With regenerate:**
```
$ find . -name '*.jpg' -size +5M|         <-- user presses hotkey again
$                                          <-- buffer cleared, spinner on stderr
$ find . -type f \( -name '*.jpg' -o -name '*.jpeg' \) -size +5M|
  # Locate JPEG images over 5MB recursively
```

**Trigger key:** The same inline hotkey (e.g., Alt+G). The shell function detects that the buffer no longer starts with `@ ` (it contains a translated command) and the `_at_original_buf` variable is set, indicating a previous translation is active. This combination signals a regeneration rather than a first translation.

**Behavior:**
1. The inline shell function checks: does `_at_original_buf` exist and is the buffer NOT prefixed with `@ `? If both are true, this is a regenerate.
2. The buffer is cleared and a fresh `at-cmd --json` call is made using the request extracted from `_at_original_buf` (stripping the `@ ` prefix).
3. `_at_original_buf` is **not** updated -- it still holds the original `@ <request>` text so that undo always returns to the starting point.
4. On success: the buffer is replaced with the new command and the description is printed.
5. On failure: the **previous** command (the one that was in the buffer before regenerate) is restored.

### Visual Feedback

| State | Submit mode | Inline mode |
|-------|------------|-------------|
| Regenerating | Spinner on stderr below prompt: `translating...` | Buffer cleared, spinner on stderr |
| Success | New description on stderr, new command in prompt | New command in buffer, new description below |
| Failure | Error on stderr, previous command restored in prompt | Previous command restored in buffer |

---

## Technical Design

### Modules Affected

#### `cli.py` -- Submit mode regenerate

The `translate_cmd` function currently uses `readline.set_startup_hook` and `input()` for the editable prompt. This is a single-shot interaction that does not support intercepting Tab.

**Approach:** Replace the bare `input()` loop with a custom readline interaction that binds Tab to a regenerate callback.

```
Key changes in translate_cmd():

1. Store the original user_prompt in a local variable (already done).
2. Before entering the input loop, bind Tab via readline.parse_and_bind()
   or readline.set_completer() to a regenerate function.
3. The regenerate function:
   a. Clears the current line.
   b. Prints spinner on stderr.
   c. Calls backend_fn(system_prompt, user_prompt) again.
   d. Calls sanitize_response() on the result.
   e. Replaces the readline buffer with the new command.
   f. Prints the new description on stderr.
4. On BackendError or SanitizeError during regenerate, print error on
   stderr and restore the previous command.
5. After the input loop exits, restore original readline bindings.
```

An alternative to readline Tab binding is to use a thin wrapper around `input()` that catches a specific key. Given readline's limited callback model, the cleanest implementation may be:

- Use `readline.set_completer()` with a custom completer that triggers regeneration on the first Tab press and returns `None` (suppressing normal completion).
- Or use `readline.parse_and_bind("Tab: <custom>")` if the platform supports it.

If readline hooks prove too fragile across platforms, a fallback approach is to treat a special sentinel input (e.g., the user clearing the line and pressing Enter on an empty prompt, or typing a literal `!` and pressing Enter) as a regenerate signal and loop back. This is less elegant but fully portable.

**Recommended approach:** Use readline's completer mechanism. When Tab is pressed:
1. The completer function is invoked.
2. On `state == 0`, it triggers the regenerate side effect (LLM call, buffer update).
3. It returns `None` to suppress completion output.

This avoids replacing the entire input mechanism and keeps the change minimal.

#### `init.py` -- Inline mode regenerate

Each shell's `_at_cmd_inline` function needs a guard at the top to handle the regenerate case.

**Pseudocode for the updated `_at_cmd_inline` (all shells):**
```
function _at_cmd_inline:
    buf = get_buffer()

    if buf starts with "@ ":
        # First translation (existing behavior)
        _at_original_buf = buf
        request = strip "@ " prefix from buf
    else if _at_original_buf is set:
        # Regenerate: reuse original request
        _at_regenerate_prev = buf          # save current command for error recovery
        request = strip "@ " prefix from _at_original_buf
    else:
        return  # not an at-cmd buffer, do nothing

    clear buffer, show spinner
    result = at-cmd --json --shell <shell> <request>

    if error:
        if regenerating:
            restore buf from _at_regenerate_prev
        else:
            restore buf from _at_original_buf
        return

    set buffer to result.command
    show result.description
```

This change affects `_fish()`, `_bash()`, `_zsh()`, and `_powershell()` in `init.py`. The `_at_original_buf` variable is intentionally left unchanged during regeneration so undo always returns to the original `@ <request>`.

A new shell variable `_at_regenerate_prev` is introduced per-shell to hold the command that was in the buffer before the regenerate attempt, used only for error recovery.

#### `config.py` -- New config field

Add `regenerate_key` to the `Config` dataclass:

```python
regenerate_key: str = "tab"
```

This value is used only in submit mode. In inline mode, the existing `hotkey` serves double duty (first press translates, subsequent presses regenerate).

Add `"tab"` to the `VALID_KEYBINDINGS` list and add its shell-specific sequences to `keybindings.py` (though for submit mode it is handled via readline, not shell keybindings).

Add env var support: `AT_CMD_REGENERATE_KEY`.

#### `keybindings.py` -- New binding (optional)

Add a `"tab"` entry if any shell integration needs to bind a dedicated regenerate key for inline mode in the future. For the initial implementation this is not strictly required since inline mode reuses the existing hotkey.

#### `llm.py` -- No changes

The `BackendFn` protocol and backend implementations are stateless. Each regenerate call is simply a second invocation of `backend_fn(system_prompt, user_prompt)`. No changes needed.

#### `sanitize.py` -- No changes

Sanitization is stateless. No changes needed.

### Data Flow

**Submit mode regenerate:**
```
User presses Tab in editable prompt
  -> readline completer callback fires
  -> cli.py: call backend_fn(system_prompt, original_user_prompt)
  -> llm.py: fresh LLM request (identical system prompt + user prompt)
  -> sanitize.py: parse response
  -> cli.py: replace readline buffer via readline.insert_text()
  -> cli.py: print new description on stderr
```

**Inline mode regenerate:**
```
User presses hotkey with non-"@ " buffer and _at_original_buf set
  -> shell function: extract request from _at_original_buf
  -> shell function: call at-cmd --json --shell <shell> <request>
  -> cli.py translate_cmd (--json mode): backend_fn -> sanitize -> JSON output
  -> shell function: parse JSON, replace buffer, show description
```

---

## Edge Cases

### Backend error during regenerate

If the LLM call fails (network error, timeout, invalid response), the previous command must be preserved. The user should see an error message on stderr but should not lose the command they were reviewing.

- **Submit mode:** The completer callback catches `BackendError` and `SanitizeError`, prints the error on stderr, and leaves the readline buffer unchanged.
- **Inline mode:** The shell function checks the exit code of `at-cmd --json` and restores `_at_regenerate_prev` on failure.

### Rapid re-presses

If the user presses Tab (submit) or the hotkey (inline) multiple times in rapid succession while a regeneration is already in flight:

- **Submit mode:** The readline completer runs synchronously and blocks the input loop. A second Tab press during an active LLM call is simply queued by the terminal and fires after the first call completes. No special debounce logic is needed.
- **Inline mode:** The shell function calls `at-cmd --json` synchronously (blocking). A second hotkey press during an active call is buffered by the shell and executes after the first completes. This is acceptable behavior. The spec does not require debouncing but implementations may add a simple timestamp guard (`_at_last_regen_ts`) if testing reveals issues.

### Undo after regenerate

Undo must always return to the original `@ <request>` text, regardless of how many regenerations occurred.

- **Inline mode:** `_at_original_buf` is set once on the first translation and never updated during regeneration. Undo restores from `_at_original_buf` as it does today.
- **Submit mode:** Undo is not natively supported (readline has its own undo, but it operates on character edits). If the user wants to start over, they Ctrl+C out and the original request is lost. This is existing behavior and acceptable for v1. A future enhancement could print the original request on cancel for easy re-invocation.

### Empty or identical regeneration

The LLM may return the same command on regeneration. This is not an error. The tool simply replaces the buffer with whatever the LLM returns. A future "multi-candidate" feature (see backlog) could deduplicate, but that is out of scope here.

### Regenerate after user edits the command

- **Submit mode:** The user may have edited the command in the readline buffer before pressing Tab. Regeneration uses the **original natural language request**, not the current buffer. The user's edits are discarded. This is intentional -- regenerate means "give me a different answer to my original question."
- **Inline mode:** Same behavior. The request comes from `_at_original_buf`, not the current buffer.

### JSON mode (`--json` flag)

Regenerate is an interactive feature. In JSON mode, `translate_cmd` returns immediately after the first result. No regenerate loop applies. No changes needed for JSON mode.

---

## Configuration

### New config field

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `regenerate_key` | `str` | `"tab"` | Key that triggers regeneration in submit mode |

### config.toml example

```toml
backend = "claude"
model = "sonnet"
regenerate_key = "tab"
```

### Environment variable

```
AT_CMD_REGENERATE_KEY=tab
```

### Inline mode note

Inline mode does not use `regenerate_key`. It reuses the configured `hotkey` for regeneration (pressing the same key again). This is consistent with the spec's description of inline mode: "Re-trigger -- press the keybinding again to regenerate."

---

## Testing Strategy

### Unit Tests (`tests/test_regenerate.py`)

**Submit mode (cli.py):**

1. **test_regenerate_calls_backend_again** -- Mock the backend to return two different responses. Simulate Tab in the readline prompt. Assert that `backend_fn` was called twice with the same `(system_prompt, user_prompt)` arguments and the second response is presented.

2. **test_regenerate_preserves_previous_on_error** -- Mock the backend to succeed on the first call and raise `BackendError` on the second. Assert that the readline buffer still contains the first command after the failed regeneration.

3. **test_regenerate_does_not_apply_in_json_mode** -- Call `translate_cmd` with `--json`. Assert the output is a single JSON object with no regeneration loop.

**Inline mode (init.py):**

4. **test_inline_regenerate_fish_script** -- Generate the fish init script and verify that `_at_cmd_inline` contains the regeneration guard (checks for `_at_original_buf` when the buffer does not start with `@ `).

5. **test_inline_regenerate_zsh_script** -- Same as above for zsh.

6. **test_inline_regenerate_bash_script** -- Same as above for bash.

7. **test_inline_regenerate_preserves_original_buf** -- Verify the generated shell script does not overwrite `_at_original_buf` during regeneration.

**Configuration:**

8. **test_config_regenerate_key_default** -- Load default config and assert `regenerate_key == "tab"`.

9. **test_config_regenerate_key_from_toml** -- Write a config.toml with `regenerate_key = "ctrl+g"` and assert it is loaded correctly.

10. **test_config_regenerate_key_from_env** -- Set `AT_CMD_REGENERATE_KEY` and assert it overrides the default.

### Integration Tests (manual / shell-specific)

These are difficult to automate and should be part of manual QA:

- In each supported shell (bash, zsh, fish), verify:
  - First translation works as before.
  - Pressing the hotkey again after a translation regenerates.
  - Undo after regeneration returns to the original `@ <request>`.
  - Backend failure during regeneration restores the previous command.
  - Rapid double-press does not crash or produce garbled output.

---

## Out of Scope / Future Considerations

- **"Try a different approach" hint:** The regenerate call currently sends the same system prompt and user prompt. A future enhancement could append a hint like "Suggest a different approach than: `<previous command>`" to improve diversity. This requires changes to `llm.py` and the system prompt builder.

- **Regeneration counter / limit:** No limit on the number of regenerations per session. If LLM cost is a concern, a future `max_regenerations` config field could cap it.

- **Multi-candidate picker:** The backlog includes a separate "Multi-Candidate Picker" feature that asks for N alternatives in a single LLM call. Regenerate is the simpler single-call version. The two features are complementary but independent.

- **Undo stack in submit mode:** Submit mode currently has no undo for regeneration (the previous suggestion is discarded). A future enhancement could maintain a stack of past suggestions navigable with a key (e.g., Shift+Tab to go back).

- **Streaming regeneration:** If streaming support is added in the future, regeneration should stream the new response character by character just like the initial translation.

- **Regeneration with edited prompt:** A "refine" mode where the user edits their natural language request and regenerates (rather than always reusing the original). This is a different feature and should be specced separately.
