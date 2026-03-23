# Ambiguity Handling

**Status:** Draft
**Date:** 2026-03-23
**Priority:** Medium
**Depends on:** None (standalone feature)

---

## Overview

When a user types an ambiguous request like `@ compress the logs`, the LLM currently
picks one interpretation silently. The user receives a command they may not have wanted,
and the only recourse is to cancel and rephrase. This feature adds a structured mechanism
for the LLM to signal ambiguity and surface clarifying questions with numbered options,
letting the user pick the right interpretation before a command is generated.

### Motivation

- A wrong command that looks plausible is more dangerous than no command at all.
- Users who are already uncertain about CLI syntax cannot evaluate whether the LLM
  guessed correctly. Surfacing the ambiguity makes the uncertainty visible.
- Clarifying questions reduce wasted LLM round-trips from cancel-rephrase cycles.
- The feature reinforces the tool's core safety principle: the user stays in control.

---

## User Stories

| ID | Story |
|----|-------|
| US-1 | As a user, when my request has multiple plausible interpretations, I want to see a short question with numbered options so I can pick the right one without retyping. |
| US-2 | As a user, when none of the offered options match my intent, I want to type a free-form refinement so I am not trapped in a fixed menu. |
| US-3 | As a user, when the LLM is confident in the interpretation, I want the normal two-line response with no extra prompting so common requests stay fast. |
| US-4 | As a user, I want to disable ambiguity handling entirely via config so I can opt for the old always-guess behavior if I prefer speed. |
| US-5 | As a user in inline mode, I want ambiguity handling to degrade gracefully because the shell buffer cannot display a multi-line picker. |

---

## Detailed UX

### Submit Mode (Enter)

When the LLM signals ambiguity, the flow changes from the normal path:

```
$ @ compress the logs
  translating...

  ? Multiple interpretations:
    1) gzip each log file in place
    2) Create a tar.gz archive of all log files
    3) Create a zip archive of all log files

  Pick [1-3] or describe what you meant: 2

  # Archive all log files into logs.tar.gz
> tar czf logs.tar.gz *.log
```

**Interaction rules:**

1. The spinner runs as usual during the initial LLM call.
2. If the response is an ambiguity signal (see Response Parsing below), the CLI
   renders the question and numbered options as dim text on stderr.
3. The user enters a number (1-N) or free-form text at the `Pick` prompt.
4. A second LLM call is made with the original request plus the user's selection
   as additional context. This second call uses the standard two-line contract.
5. The result flows into the normal editable prompt.
6. Ctrl+C at the `Pick` prompt cancels the entire operation.

**Free-form refinement (US-2):**

If the user types text that is not a valid option number, it is treated as a
refinement of the original request. The second LLM call receives:
`"Original request: compress the logs. Clarification: use zstd compression"`

### Inline Mode (Keybinding)

Inline mode operates inside the shell's line buffer, which cannot render multi-line
menus. When ambiguity is detected in inline mode:

1. The buffer is restored to the original `@ <request>` text.
2. A single-line hint is printed to stderr:
   `ambiguous request -- press Enter to clarify or re-trigger with more detail`
3. The user can either:
   - Press Enter to drop into submit mode, where the full clarification flow runs.
   - Edit the `@ <request>` text to be more specific and re-trigger the keybinding.

This avoids forcing a complex menu into the line buffer while still surfacing the
ambiguity signal.

### JSON Mode (`--json`)

When `--json` is active and the LLM signals ambiguity, the output is:

```json
{
  "ambiguous": true,
  "question": "How should the logs be compressed?",
  "options": [
    "gzip each log file in place",
    "Create a tar.gz archive of all log files",
    "Create a zip archive of all log files"
  ]
}
```

The caller is responsible for presenting options and re-invoking `at-cmd` with a
more specific request. No interactive prompt is shown in JSON mode.

---

## LLM Prompt Design

### Modified System Prompt

The system prompt is extended with an ambiguity instruction block. The existing
two-line contract remains the primary format; the ambiguity format is an alternative
the LLM may choose when appropriate.

```
You are a shell command translator for {shell} on {os}.
Working directory: {cwd}
The user will describe what they want in natural language.

If the request is clear, return EXACTLY two lines:
Line 1: The {shell} command (no backticks, no markdown, one line,
        use appropriate chaining for {shell})
Line 2: A brief description (10 words max) of what the command does

If the request is genuinely ambiguous and there are multiple meaningfully
different commands that could satisfy it, return a clarification in this
exact format:
AMBIGUOUS
Line 1: A short question (under 15 words)
Line 2: Option 1 description (under 10 words)
Line 3: Option 2 description (under 10 words)
Line 4: Option 3 description (under 10 words, optional)

Rules for ambiguity:
- Only signal ambiguity when the different interpretations would produce
  substantially different commands (not minor flag variations).
- Offer 2-3 options maximum. Never more than 3.
- If one interpretation is overwhelmingly more likely, just return the command.
- Never signal ambiguity for trivial requests like "list files" or "show disk usage".
```

### Follow-up Prompt (Second LLM Call)

When the user selects an option or provides a refinement, the second call uses the
standard two-line-only system prompt (no ambiguity block) with a combined user prompt:

```
Original request: {original_request}
User chose: {option_text_or_free_form_input}

Translate this into a single shell command.
```

This ensures the second call always returns a command, never a nested ambiguity.

---

## Response Parsing

### New Response Format

The `sanitize.py` module currently expects exactly two non-empty lines (command +
description). The parser must now distinguish between two response shapes:

**Shape 1 -- Command (existing):**
```
find . -name '*.log' -exec gzip {} +
Gzip all log files in current directory
```

**Shape 2 -- Ambiguity (new):**
```
AMBIGUOUS
How should the logs be compressed?
gzip each log file in place
Create a tar.gz archive of all log files
Create a zip archive of all log files
```

### Detection Logic

After stripping markdown fences and empty lines (existing sanitization), check
whether the first non-empty line is exactly `AMBIGUOUS` (case-insensitive).

- If yes: parse the remaining lines as `(question, *options)`. Require at least
  a question line and 2 option lines. Raise `SanitizeError` if fewer are found.
- If no: fall through to the existing two-line command parser unchanged.

### New Return Type

`sanitize_response` currently returns `tuple[str, str]`. To avoid breaking the
existing API, introduce a new public function and a result type:

```python
from dataclasses import dataclass


@dataclass
class TranslateResult:
    """Parsed LLM response -- either a command or a clarification request."""

    command: str = ""
    description: str = ""
    ambiguous: bool = False
    question: str = ""
    options: list[str] = field(default_factory=list)

    @property
    def is_ambiguous(self) -> bool:
        return self.ambiguous


def parse_response(raw: str) -> TranslateResult:
    """Parse raw LLM output into a structured result.

    Returns a TranslateResult with either command+description populated
    (normal case) or question+options populated (ambiguity case).
    """
```

The existing `sanitize_response` function is preserved for backward compatibility
and continues to return `tuple[str, str]`. Internal callers migrate to
`parse_response`.

---

## Technical Design

### Modules That Change

| Module | Change |
|--------|--------|
| `sanitize.py` | Add `TranslateResult` dataclass, `parse_response()` function, and `_parse_ambiguity()` helper. Existing `sanitize_response()` unchanged. |
| `llm.py` | Add `build_ambiguity_system_prompt()` that extends the base prompt with the ambiguity instruction block. Add `build_followup_prompt()` for the second call. |
| `cli.py` | Update `translate_cmd` to call `parse_response`, handle the ambiguity branch (render options, collect input, make second LLM call). |
| `config.py` | Add `ambiguity_enabled: bool = True` and `ambiguity_threshold: str = "auto"` fields to `Config`. Wire up env vars `AT_CMD_AMBIGUITY_ENABLED` and `AT_CMD_AMBIGUITY_THRESHOLD`. |

### Request Flow

```
                   +------------------+
                   |   User request   |
                   +--------+---------+
                            |
                   +--------v---------+
                   |  Build system    |
                   |  prompt (with    |
                   |  ambiguity block)|
                   +--------+---------+
                            |
                   +--------v---------+
                   |   LLM Call #1    |
                   +--------+---------+
                            |
                   +--------v---------+
                   | parse_response() |
                   +--------+---------+
                            |
                +-----------+-----------+
                |                       |
        +-------v-------+      +-------v-------+
        | TranslateResult|      | TranslateResult|
        | .ambiguous=False|      | .ambiguous=True |
        +-------+-------+      +-------+-------+
                |                       |
        +-------v-------+      +-------v-------+
        | Normal flow:  |      | Show question |
        | editable      |      | + options     |
        | prompt        |      +-------+-------+
        +---------------+              |
                               +-------v-------+
                               | User picks    |
                               | option or     |
                               | types text    |
                               +-------+-------+
                                       |
                               +-------v-------+
                               | LLM Call #2   |
                               | (standard     |
                               |  prompt only) |
                               +-------+-------+
                                       |
                               +-------v-------+
                               | Normal flow:  |
                               | editable      |
                               | prompt        |
                               +---------------+
```

### Key Implementation Details

**Prompt selection in `llm.py`:**

When `config.ambiguity_enabled` is `True`, `build_system_prompt()` appends the
ambiguity instruction block. When `False`, the prompt is identical to today's.
This keeps the feature fully opt-out without code branching in `cli.py`.

**Second LLM call:**

The follow-up call deliberately uses the base system prompt without the ambiguity
block. This prevents infinite clarification loops where the LLM keeps asking
questions.

**Option numbering:**

Options are numbered starting at 1 in the display. Internally they are stored as
a zero-indexed list. The `Pick` prompt validates input: digits 1-N map to options;
anything else is treated as free-form text.

---

## Edge Cases

| Case | Behavior |
|------|----------|
| **LLM always signals ambiguity** | The `ambiguity_threshold` config option (see Configuration) can be set to `"strict"` to add a stronger instruction ("only signal ambiguity when interpretations produce fundamentally different outcomes"). If the LLM still over-triggers, the user can disable the feature entirely. |
| **LLM never signals ambiguity** | Expected for simple requests. If the LLM ignores the ambiguity instructions entirely, behavior is identical to the current codebase -- no regression. |
| **LLM returns malformed ambiguity block** | Missing question or fewer than 2 options after `AMBIGUOUS` marker triggers a `SanitizeError`. The CLI prints an error and exits, same as any other parse failure. |
| **LLM returns AMBIGUOUS as part of a command** | Unlikely, but handled: the marker check requires `AMBIGUOUS` to be the entire first line (stripped), not a substring. A command like `echo AMBIGUOUS` would have additional text on the line and would not trigger the branch. |
| **Inline mode with ambiguity** | Buffer is restored, stderr hint is shown, no menu is rendered in the line buffer. See Detailed UX > Inline Mode above. |
| **JSON mode with ambiguity** | Returns the structured JSON object with `ambiguous: true`. No interactive prompt. The caller handles re-invocation. |
| **Second LLM call also returns AMBIGUOUS** | Should not happen because the follow-up prompt omits the ambiguity block. If it does happen anyway (model hallucination), treat the response as a `SanitizeError` with message "Unable to resolve ambiguity -- please try a more specific request." |
| **User enters invalid option number** (e.g., "5" when only 3 options) | Re-prompt with "Invalid choice. Pick [1-3] or describe what you meant:" up to 2 retries, then abort. |
| **Timeout during second LLM call** | Standard `BackendError` handling applies. The user sees the same timeout error as a normal translate failure. |
| **Empty free-form refinement** | If the user presses Enter with no input at the `Pick` prompt, re-prompt once, then cancel. |

---

## Configuration

### New Config Fields

```toml
# ~/.config/at-cmd/config.toml

# Enable or disable ambiguity detection.
# When false, the LLM always returns a command (current behavior).
ambiguity_enabled = true

# How aggressively the LLM should signal ambiguity.
# "auto"   - LLM decides based on the prompt instructions (default)
# "strict" - Only for fundamentally different interpretations
# "eager"  - Signal ambiguity even for moderately unclear requests
ambiguity_threshold = "auto"
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AT_CMD_AMBIGUITY_ENABLED` | `true` | `"true"` or `"false"` |
| `AT_CMD_AMBIGUITY_THRESHOLD` | `"auto"` | `"auto"`, `"strict"`, or `"eager"` |

### Config Dataclass Changes

```python
@dataclass
class Config:
    # ... existing fields ...
    ambiguity_enabled: bool = True
    ambiguity_threshold: str = "auto"  # "auto" | "strict" | "eager"
```

### Threshold Prompt Mapping

The threshold value maps to additional wording appended to the ambiguity instruction
in the system prompt:

| Threshold | Additional instruction |
|-----------|----------------------|
| `auto` | (no additional text -- base instructions only) |
| `strict` | "Only signal ambiguity when the different interpretations would produce fundamentally different outcomes. When in doubt, pick the most common interpretation and return the command." |
| `eager` | "Err on the side of asking. If there is any reasonable alternative interpretation, signal ambiguity." |

---

## Testing Strategy

Tests live in `tests/test_ambiguity.py` mirroring the feature's cross-cutting nature.

### Unit Tests -- `parse_response()`

| Test | Description |
|------|-------------|
| `test_parse_normal_response` | Standard two-line input returns `TranslateResult` with `ambiguous=False`, command and description populated. |
| `test_parse_ambiguous_response` | Input starting with `AMBIGUOUS` returns `ambiguous=True`, question and 2-3 options populated. |
| `test_parse_ambiguous_case_insensitive` | `ambiguous` (lowercase) marker is recognized. |
| `test_parse_ambiguous_with_markdown_fences` | Markdown fences around the ambiguity block are stripped before parsing. |
| `test_parse_ambiguous_missing_question` | `AMBIGUOUS` followed by zero lines raises `SanitizeError`. |
| `test_parse_ambiguous_one_option` | `AMBIGUOUS` + question + only 1 option raises `SanitizeError` (minimum 2 required). |
| `test_parse_ambiguous_three_options` | Three options are parsed correctly. |
| `test_parse_command_containing_ambiguous_word` | A command like `echo AMBIGUOUS state` is not misdetected as an ambiguity signal. |

### Unit Tests -- Prompt Building

| Test | Description |
|------|-------------|
| `test_system_prompt_includes_ambiguity_block` | When `ambiguity_enabled=True`, the system prompt contains the `AMBIGUOUS` format instructions. |
| `test_system_prompt_excludes_ambiguity_block` | When `ambiguity_enabled=False`, the prompt matches the current baseline exactly. |
| `test_threshold_strict_adds_instruction` | `ambiguity_threshold="strict"` appends the strict wording. |
| `test_threshold_eager_adds_instruction` | `ambiguity_threshold="eager"` appends the eager wording. |
| `test_followup_prompt_no_ambiguity_block` | The follow-up system prompt never includes the ambiguity instructions. |

### Integration Tests -- CLI Flow

| Test | Description |
|------|-------------|
| `test_ambiguity_flow_select_option` | Mock LLM returns ambiguity on call 1, command on call 2. Simulate user selecting option "1". Verify second call receives the selected option text. |
| `test_ambiguity_flow_free_form` | Mock LLM returns ambiguity. Simulate user typing free-form text. Verify second call receives the refinement. |
| `test_ambiguity_disabled_passthrough` | With `ambiguity_enabled=False`, even if LLM returns `AMBIGUOUS` marker, it is treated as a command (not intercepted). |
| `test_ambiguity_json_mode` | With `--json`, ambiguity returns structured JSON without interactive prompts. |
| `test_ambiguity_cancel` | Ctrl+C at the pick prompt exits with code 130. |

### Edge Case Tests

| Test | Description |
|------|-------------|
| `test_invalid_option_number` | User enters "5" for 3 options, verify re-prompt. |
| `test_second_call_returns_ambiguous` | Second call unexpectedly returns `AMBIGUOUS`, verify `SanitizeError` with helpful message. |
| `test_empty_pick_input` | Empty input at the pick prompt triggers re-prompt. |

---

## Out of Scope

The following are explicitly excluded from this feature:

- **Multi-turn conversation**: This feature supports exactly one clarification round.
  Extended back-and-forth dialogue is a separate feature.
- **Ambiguity learning/memory**: The system does not remember past clarification
  choices to auto-resolve similar ambiguities in the future.
- **Confidence scores**: The LLM is not asked to return a numeric confidence value.
  The signal is binary: either the response is a command or an ambiguity block.
- **Automatic option pre-selection**: The system does not try to guess which option
  the user most likely wants based on history or context.
- **Multi-candidate generation**: The related "Multi-Candidate Picker" backlog item
  asks for N alternative commands. Ambiguity handling asks the user to clarify intent
  before generating any command. These are complementary but distinct features.
- **Streaming ambiguity responses**: The clarification block is short enough that
  streaming provides no meaningful benefit.
- **TUI integration**: The `at-cmd config` TUI is not updated to expose
  `ambiguity_enabled` or `ambiguity_threshold` in this iteration. Config file
  and env vars are sufficient.
