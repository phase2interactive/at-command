# Ambiguity Handling

**Status:** Draft
**Date:** 2026-03-23
**Priority:** Medium
**Depends on:** JSON Response Format (implemented)

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
| US-3 | As a user, when the LLM is confident in the interpretation, I want the normal JSON response with no extra prompting so common requests stay fast. |
| US-4 | As a user, I want to disable ambiguity handling entirely via config so I can opt for the old always-guess behavior if I prefer speed. |
| US-5 | As a user in inline mode, I want ambiguity handling to degrade gracefully because the shell buffer cannot display a multi-line picker. |

---

## Detailed UX

### Submit Mode (Enter)

When the LLM signals ambiguity, the flow changes from the normal path:

```text
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
2. If the JSON response contains `"ambiguous": true`, the CLI renders the question
   and numbered options as dim text on stderr.
3. The user enters a number (1-N) or free-form text at the `Pick` prompt.
4. A second LLM call is made with the original request plus the user's selection
   as additional context. This second call uses the standard JSON contract (without
   the ambiguity instruction block).
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
JSON contract remains the primary format; the ambiguity format is an alternative
the LLM may choose when appropriate.

```text
You are a shell command translator for {shell} on {os}.
Working directory: {cwd}
The user will describe what they want in natural language.

If the request is clear, return a JSON object with these fields:
{"command": "<the shell command>", "description": "<10 words max>"}

If the request is genuinely ambiguous and there are multiple meaningfully
different commands that could satisfy it, return a JSON object in this format:
{
  "ambiguous": true,
  "question": "<short question, under 15 words>",
  "options": ["<option 1, under 10 words>", "<option 2>", "<option 3 (optional)>"]
}

Return ONLY the JSON object. No markdown, no explanation.

Rules for ambiguity:
- Only signal ambiguity when the different interpretations would produce
  substantially different commands (not minor flag variations).
- Offer 2-3 options maximum. Never more than 3.
- If one interpretation is overwhelmingly more likely, just return the command.
- Never signal ambiguity for trivial requests like "list files" or "show disk usage".
```

### Follow-up Prompt (Second LLM Call)

When the user selects an option or provides a refinement, the second call uses the
standard JSON-only system prompt (no ambiguity block) with a combined user prompt:

```text
Original request: {original_request}
User chose: {option_text_or_free_form_input}

Translate this into a single shell command.
```

This ensures the second call always returns a command, never a nested ambiguity.

---

## Response Parsing

### JSON Response Shapes

With the JSON response format already in place, ambiguity detection is a matter of
checking for additional fields in the parsed JSON object. `parse_response()` already
handles JSON parsing and fence stripping.

**Shape 1 -- Command (existing):**

```json
{
  "command": "find . -name '*.log' -exec gzip {} +",
  "description": "Gzip all log files in current directory"
}
```

**Shape 2 -- Ambiguity (new):**

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

### Detection Logic

Inside `parse_response()`, after successful `json.loads()`, check whether
`data.get("ambiguous")` is `True`.

- If yes: validate that `question` is a non-empty string and `options` is a list
  with 2-3 non-empty strings. Return an `LLMResponse` with ambiguity fields set.
- If no: fall through to the existing command parsing path.

The text fallback path never produces ambiguity responses — only JSON can.

### Extended LLMResponse

The existing `LLMResponse` dataclass is extended with optional ambiguity fields:

```python
@dataclass(frozen=True)
class LLMResponse:
    """Parsed response from the LLM backend."""

    command: str = ""
    description: str = ""
    ambiguous: bool = False
    question: str = ""
    options: tuple[str, ...] = ()

    @property
    def is_ambiguous(self) -> bool:
        """Whether this response is an ambiguity signal."""
        return self.ambiguous
```

Using a single dataclass (rather than a separate `TranslateResult`) keeps the
response model unified. Command responses have `command`/`description` populated;
ambiguity responses have `ambiguous`/`question`/`options` populated.

---

## Technical Design

### Modules That Change

| Module | Change |
|--------|--------|
| `sanitize.py` | Extend `LLMResponse` with `ambiguous`, `question`, `options` fields. Update `parse_response()` to detect and validate ambiguity JSON. |
| `llm.py` | Add `build_ambiguity_system_prompt()` that extends the base JSON prompt with the ambiguity instruction block. Add `build_followup_prompt()` for the second call. |
| `cli.py` | Update `translate_cmd` to check `response.is_ambiguous`, render options, collect input, make second LLM call. |
| `config.py` | Add `ambiguity_enabled: bool = True` and `ambiguity_threshold: str = "auto"` fields to `Config`. Wire up env vars `AT_CMD_AMBIGUITY_ENABLED` and `AT_CMD_AMBIGUITY_THRESHOLD`. |

### Request Flow

```text
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
        |  LLMResponse   |      |  LLMResponse   |
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
                               |  JSON prompt) |
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
ambiguity instruction block. When `False`, the prompt is identical to the standard
JSON-only prompt. This keeps the feature fully opt-out without code branching in
`cli.py`.

**Second LLM call:**

The follow-up call deliberately uses the base system prompt without the ambiguity
block. This prevents infinite clarification loops where the LLM keeps asking
questions.

**Option numbering:**

Options are numbered starting at 1 in the display. Internally they are stored as
a zero-indexed tuple. The `Pick` prompt validates input: digits 1-N map to options;
anything else is treated as free-form text.

---

## Edge Cases

| Case | Behavior |
|------|----------|
| **LLM always signals ambiguity** | The `ambiguity_threshold` config option (see Configuration) can be set to `"strict"` to add a stronger instruction ("only signal ambiguity when interpretations produce fundamentally different outcomes"). If the LLM still over-triggers, the user can disable the feature entirely. |
| **LLM never signals ambiguity** | Expected for simple requests. If the LLM ignores the ambiguity instructions entirely, behavior is identical to the current codebase -- no regression. |
| **LLM returns malformed ambiguity JSON** | Missing `question` or fewer than 2 options when `ambiguous` is `true` raises a `SanitizeError`. The CLI prints an error and exits, same as any other parse failure. |
| **Inline mode with ambiguity** | Buffer is restored, stderr hint is shown, no menu is rendered in the line buffer. See Detailed UX > Inline Mode above. |
| **JSON mode with ambiguity** | Returns the structured JSON object with `ambiguous: true`. No interactive prompt. The caller handles re-invocation. |
| **Second LLM call also returns ambiguous** | Should not happen because the follow-up prompt omits the ambiguity block. If it does happen anyway (model hallucination), treat the response as a `SanitizeError` with message "Unable to resolve ambiguity -- please try a more specific request." |
| **User enters invalid option number** (e.g., "5" when only 3 options) | Re-prompt with "Invalid choice. Pick [1-3] or describe what you meant:" up to 2 retries, then abort. |
| **Timeout during second LLM call** | Standard `BackendError` handling applies. The user sees the same timeout error as a normal translate failure. |
| **Empty free-form refinement** | If the user presses Enter with no input at the `Pick` prompt, re-prompt once, then cancel. |
| **Text fallback with ambiguity-like content** | The text fallback path never produces ambiguity responses. Only valid JSON with `"ambiguous": true` triggers the ambiguity flow. |

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
| `test_parse_normal_json_not_ambiguous` | Standard JSON input returns `LLMResponse` with `ambiguous=False`, command and description populated. |
| `test_parse_ambiguous_json` | JSON with `"ambiguous": true` returns `LLMResponse` with question and 2-3 options populated. |
| `test_parse_ambiguous_missing_question` | `ambiguous=true` with no `question` field raises `SanitizeError`. |
| `test_parse_ambiguous_one_option` | `ambiguous=true` with only 1 option raises `SanitizeError` (minimum 2 required). |
| `test_parse_ambiguous_three_options` | Three options are parsed correctly into the `options` tuple. |
| `test_parse_ambiguous_extra_fields_ignored` | Extra fields in ambiguity JSON are silently ignored. |
| `test_parse_ambiguous_with_fences` | Markdown fences around ambiguity JSON are stripped before parsing. |
| `test_text_fallback_never_ambiguous` | Plain text input always returns `ambiguous=False`, even if the text contains the word "ambiguous". |

### Unit Tests -- Prompt Building

| Test | Description |
|------|-------------|
| `test_system_prompt_includes_ambiguity_block` | When `ambiguity_enabled=True`, the system prompt contains the ambiguity JSON format instructions. |
| `test_system_prompt_excludes_ambiguity_block` | When `ambiguity_enabled=False`, the prompt matches the standard JSON-only prompt. |
| `test_threshold_strict_adds_instruction` | `ambiguity_threshold="strict"` appends the strict wording. |
| `test_threshold_eager_adds_instruction` | `ambiguity_threshold="eager"` appends the eager wording. |
| `test_followup_prompt_no_ambiguity_block` | The follow-up system prompt never includes the ambiguity instructions. |

### Integration Tests -- CLI Flow

| Test | Description |
|------|-------------|
| `test_ambiguity_flow_select_option` | Mock LLM returns ambiguity JSON on call 1, command JSON on call 2. Simulate user selecting option "1". Verify second call receives the selected option text. |
| `test_ambiguity_flow_free_form` | Mock LLM returns ambiguity JSON. Simulate user typing free-form text. Verify second call receives the refinement. |
| `test_ambiguity_disabled_passthrough` | With `ambiguity_enabled=False`, LLM response with `ambiguous` field is not intercepted (ambiguity block not in prompt, so this scenario is unlikely but tests the guard). |
| `test_ambiguity_json_mode` | With `--json`, ambiguity returns structured JSON without interactive prompts. |
| `test_ambiguity_cancel` | Ctrl+C at the pick prompt exits with code 130. |

### Edge Case Tests

| Test | Description |
|------|-------------|
| `test_invalid_option_number` | User enters "5" for 3 options, verify re-prompt. |
| `test_second_call_returns_ambiguous` | Second call unexpectedly returns ambiguity JSON, verify `SanitizeError` with helpful message. |
| `test_empty_pick_input` | Empty input at the pick prompt triggers re-prompt. |

---

## Out of Scope

The following are explicitly excluded from this feature:

- **Multi-turn conversation**: This feature supports exactly one clarification round.
  Extended back-and-forth dialogue is a separate feature.
- **Ambiguity learning/memory**: The system does not remember past clarification
  choices to auto-resolve similar ambiguities in the future.
- **Confidence scores**: The LLM is not asked to return a numeric confidence value.
  The signal is binary: either the response is a command or an ambiguity object.
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
