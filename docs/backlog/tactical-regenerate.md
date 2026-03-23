# Refine / Edit Previous Request

**Status:** Draft
**Date:** 2026-03-23
**Priority:** High
**Depends on:** Core translate flow (cli.py, init.py)

---

## Overview

When the LLM returns a wrong or suboptimal command, the user's best move is to refine their original request — not blindly retry the same words. Inspired by Claude Code's double-Escape (edit previous message), this feature lets the user quickly restore their original `@ <request>` text, edit it, and resubmit.

Blind regeneration (same prompt, hope for different output) is dropped. If the request was clear enough to get a good result, the first attempt usually does. If it wasn't, resending the same words won't help.

---

## UX

### Submit Mode

**Double-Escape restores the original request:**

```
$ @ find large jpg files
  # Find JPG files larger than 5MB in the current directory
❯ find . -name '*.jpg' -size +5M|     ← not what the user wanted
  [Escape, Escape]                     ← double-escape
$ @ find large jpg files|              ← original request restored, editable
```

The user edits their request and presses Enter to retranslate:

```
$ @ find jpg files over 10mb recursively|   ← user refined the request
  # Recursively find JPG files larger than 10MB
❯ find . -name '*.jpg' -size +10M|
```

**Behavior:**
1. Single Escape (or Ctrl+C): cancel, exit without executing (existing behavior).
2. Double-Escape (two Escapes within 500ms): restore the original `@ <request>` into a new editable prompt. The user is back in the shell, not in the at-cmd editable prompt.
3. The restored text starts with `@ ` so the shell integration intercepts it on Enter as a fresh translation request.

### Inline Mode

**Undo (Ctrl+Z) already restores the original `@ <request>` — this is the same pattern.** The user presses Ctrl+Z, edits, and retriggers.

```
$ find . -name '*.jpg' -size +5M|     ← translated command in buffer
  [Ctrl+Z]                             ← undo
$ @ find large jpg files|              ← original restored, editable
  ... user edits ...
$ @ find jpg files over 10mb recursively|
  [Enter or hotkey]                    ← retranslate
```

No new mechanism needed for inline mode — undo already does this. The spec just needs to document the full refine workflow clearly.

### LLM Annotation (Optional Enhancement)

When the user refines and resubmits, the system could inject context into the LLM prompt:

```
The user previously asked: "find large jpg files"
which produced: find . -name '*.jpg' -size +5M
The user was not satisfied and has refined their request.
```

This gives the LLM a signal to try a meaningfully different approach. This is optional for v1 but worth designing for.

---

## Technical Design

### Submit Mode — Double-Escape Detection

The `translate_cmd` function in `cli.py` currently uses `readline` + `input()`. To detect double-escape:

**Option A: Custom input loop with keypress detection**

Replace `input()` with a character-level reader that detects two Escape keypresses within a timeout window. On detection, return a sentinel value that the outer loop interprets as "restore and re-prompt."

**Option B: Treat empty input as refine signal**

If the user clears the readline buffer entirely and presses Enter (submits empty), interpret that as "I don't want this, let me try again." Simpler but less discoverable than double-Escape.

**Recommended: Option A** — double-Escape matches established muscle memory from Claude Code.

### Flow

```
translate_cmd():
    prompt = original "@ <request>" text
    loop:
        result = call_llm(prompt)
        show description
        user_input = editable_prompt(result.command)

        if user_input == DOUBLE_ESCAPE_SENTINEL:
            # Restore original request in shell buffer
            # For submit mode: use print -z (zsh) or readline pre-fill
            print "@ {original_request}" to shell buffer
            return (no execution)

        if user_input is cancelled (Ctrl+C / single Escape):
            exit

        if user_input is confirmed (Enter):
            execute(user_input)
            return
```

### Inline Mode — No Changes Needed

Ctrl+Z undo already restores `@ <request>`. The user edits and retriggers. Document this as the "refine" workflow.

### Annotation Support (v2)

Add an optional `previous_attempt` parameter to `build_system_prompt()`:

```python
def build_system_prompt(
    ctx: ShellContext,
    previous_attempt: tuple[str, str] | None = None,  # (request, command)
) -> str:
    prompt = f"You are a shell command translator for {ctx.shell} on {ctx.os_name}. ..."
    if previous_attempt:
        prev_request, prev_command = previous_attempt
        prompt += (
            f"\n\nThe user previously asked: \"{prev_request}\"\n"
            f"which produced: {prev_command}\n"
            f"The user was not satisfied and has refined their request."
        )
    return prompt
```

For inline mode, the shell scripts would need to pass the previous command back to `at-cmd`. A `--previous-command` flag on the CLI could handle this:

```bash
at-cmd --json --shell zsh --previous-command "find . -name '*.jpg' -size +5M" "find jpg files over 10mb recursively"
```

---

## Edge Cases

### User doesn't edit after restore
If the user double-escapes and resubmits the exact same `@ <request>`, they get a fresh LLM call. This is fine — the LLM is non-deterministic and may return something different. But the primary value is in editing.

### Multiple refine cycles
The user can refine multiple times. Each cycle is independent — the annotation only references the immediately previous attempt, not the full history.

### Submit mode: restoring to shell buffer
After double-escape, the original `@ <request>` needs to land in an editable shell prompt. In submit mode (direct CLI), this means exiting `translate_cmd` and somehow pre-filling the next shell prompt. Options:
- **Zsh**: `print -z "@ find large jpg files"` puts it in the zsh line editor buffer
- **Bash**: No clean equivalent; could print the text for the user to copy
- **Shell integration**: The `_at_cmd_submit` shell function can handle the loop natively

The cleanest approach: return a special exit code (e.g., 2) from `at-cmd` that the shell integration function interprets as "refine." The shell function then pre-fills the prompt with the original request.

---

## Testing Strategy

1. **test_double_escape_returns_sentinel** — Simulate double-Escape input; assert translate_cmd returns without executing.
2. **test_single_escape_cancels** — Simulate single Escape; assert clean exit (existing behavior preserved).
3. **test_inline_undo_restores_original** — Verify shell scripts: Ctrl+Z after translation restores `@ <request>` (existing tests, just document the refine workflow).
4. **test_annotation_prompt_includes_previous** — Call `build_system_prompt` with `previous_attempt`; assert the output contains the previous request and command.
5. **test_annotation_prompt_without_previous** — Call `build_system_prompt` without `previous_attempt`; assert no annotation text.

---

## Out of Scope

- **Blind regeneration (same prompt retry):** Intentionally dropped. If the user wants a different result, they should refine their request.
- **Undo stack / suggestion history:** Navigating through past suggestions. Could complement this feature later but adds complexity.
- **Multi-candidate picker:** Asking for N alternatives in one LLM call. Separate backlog item.
