# JSON Response Format Migration

**Status:** Implemented
**Date:** 2026-03-23
**Depends on:** None
**Unlocks:** Danger Warnings (LLM-based classification), Ambiguity Handling, Multi-Candidate Picker

---

## Overview

Migrate the LLM response contract from a fragile 2-line plain-text format to structured JSON. Instead of asking the LLM to return two raw lines (command + description) and then hoping `sanitize.py` can scrape them clean, the system prompt instructs the LLM to return a JSON object. This gives us a typed, extensible response contract that future features (danger classification, confidence scores, multiple candidates) can build on without changing the parsing layer each time.

## Motivation

The current 2-line text contract is brittle:

- `sanitize.py` exists entirely to undo markdown formatting the LLM wasn't supposed to add. Regex stripping is a losing game against varied LLM output styles.
- Adding any new response field (danger level, explanation, alternatives) means changing the line count, updating the system prompt, and rewriting the parser — every time.
- The Ollama and OpenAI backends already return JSON from the API; we parse out a text string and then re-parse that text. Requesting JSON content directly is more natural.
- The Claude CLI backend supports `--output-format json`, which can return structured content.

A JSON contract makes the response self-describing and extensible. New fields can be added to the schema without touching the parsing core.

---

## User Stories

1. **As a developer**, I want LLM responses to be structured JSON, so adding new response fields doesn't require rewriting the parser.
2. **As a user**, I want more reliable command extraction, so malformed LLM output is less likely to break my workflow.
3. **As a feature author**, I want a response schema I can extend (danger level, confidence, alternatives) without changing the sanitization layer.

---

## New Response Contract

### System Prompt (JSON section)

```
Return your response as a JSON object with exactly these fields:
{
  "command": "<the shell command, single line, no backticks or markdown>",
  "description": "<brief description, 10 words or fewer>"
}

Return ONLY the JSON object. No markdown fences, no explanation, no extra text.
```

### Example Response

```json
{
  "command": "find . -name '*.py' -mtime -7",
  "description": "Find Python files modified in the last 7 days"
}
```

### Future Extension (not part of this BI)

Once JSON is the contract, features like danger warnings can add fields to the prompt:

```json
{
  "command": "rm -rf /tmp/old",
  "description": "Remove old temp files",
  "danger": "warning"
}
```

This requires only a system prompt change and a schema update — no new parsing logic.

---

## Technical Design

### Response Dataclass

New file or addition to an existing module:

```python
@dataclass(frozen=True)
class LLMResponse:
    """Parsed response from the LLM backend.

    Attributes:
        command: The translated shell command.
        description: Brief description of what the command does.
    """
    command: str
    description: str
```

### New Parse Function: `parse_response`

Replaces the role of `sanitize_response`. Lives in `sanitize.py` (or a new `response.py`).

```python
def parse_response(raw: str) -> LLMResponse:
    """Parse a JSON LLM response into an LLMResponse.

    Tries JSON parsing first. Falls back to the legacy 2-line
    text parser for robustness (LLMs sometimes ignore JSON instructions).

    Args:
        raw: Raw text from the LLM backend.

    Returns:
        LLMResponse with command and description.

    Raises:
        SanitizeError: If neither JSON nor text parsing succeeds.
    """
```

**Parsing strategy (ordered):**

1. Strip whitespace and any markdown code fences (```json ... ```)
2. Attempt `json.loads()`
3. Validate required keys (`command`, `description`) are present and non-empty strings
4. Apply `_clean_command()` to the command value (LLMs may still sneak in backticks)
5. If JSON parsing fails, fall back to the existing 2-line text parser
6. Log a warning on fallback so we can track how often the LLM ignores the JSON instruction

The fallback keeps the tool working even when the LLM doesn't comply. Over time, if fallback rates are low, the text path can be removed.

### System Prompt Changes (`llm.py`)

`build_system_prompt` changes from:

```
Return EXACTLY two lines:
Line 1: The {shell} command (no backticks, no markdown, one line)
Line 2: A brief description (10 words max)
```

To:

```
Return your response as a JSON object with exactly these fields:
{"command": "<the shell command>", "description": "<10 words max>"}
Return ONLY the JSON object. No markdown, no explanation.
```

### Backend Changes (`llm.py`)

The `BackendFn` protocol and all three backends (`_claude_backend`, `_ollama_backend`, `_openai_backend`) continue to return `str`. The JSON parsing happens in `parse_response`, not in the backends. This keeps the backends as dumb transport — they return whatever the LLM said, and the parse layer interprets it.

No backend signature changes needed.

### CLI Changes (`cli.py`)

Replace:

```python
command, description = sanitize_response(raw)
```

With:

```python
response = parse_response(raw)
command, description = response.command, response.description
```

Minimal change. The `LLMResponse` dataclass is what future features will extend.

### `--json` Output

The `--json` CLI flag currently builds its own dict. After this change it can serialize directly from `LLMResponse`, keeping the external JSON schema aligned with the internal response model.

---

## Migration Path

1. **Update system prompt** to request JSON
2. **Add `parse_response`** with JSON-first, text-fallback logic
3. **Update `cli.py`** to use `parse_response` and `LLMResponse`
4. **Keep `sanitize_response`** as the text-fallback path (called internally by `parse_response`)
5. **Update tests** — new tests for JSON parsing, keep existing sanitize tests as fallback coverage
6. **Update `--json` output** to serialize from `LLMResponse`

`sanitize_response` is not deleted — it becomes the fallback parser inside `parse_response`. Existing tests continue to pass.

---

## Testing Strategy

Tests live in `tests/test_sanitize.py` (extended) or a new `tests/test_response.py`.

### JSON Parsing Tests

| Test | Input | Expected |
|------|-------|----------|
| `test_valid_json` | `{"command": "ls -la", "description": "List all files"}` | `LLMResponse("ls -la", "List all files")` |
| `test_json_with_fences` | `` ```json\n{"command": "ls", "description": "List"}\n``` `` | Parses correctly |
| `test_json_missing_command` | `{"description": "oops"}` | `SanitizeError` |
| `test_json_empty_command` | `{"command": "", "description": "..."}` | `SanitizeError` |
| `test_json_extra_fields_ignored` | `{"command": "ls", "description": "List", "extra": true}` | Parses, ignores extra |
| `test_json_command_has_backticks` | `{"command": "\`ls -la\`", "description": "List"}` | Backticks stripped |

### Fallback Tests

| Test | Input | Expected |
|------|-------|----------|
| `test_fallback_plain_text` | `ls -la\nList all files` | Falls back to text parser, returns `LLMResponse` |
| `test_fallback_with_fences` | `` ```\nls -la\nList\n``` `` | Falls back, returns `LLMResponse` |
| `test_fallback_empty` | `` | `SanitizeError` |

### Existing Sanitize Tests

All existing `test_sanitize.py` tests remain and pass — they cover the fallback path.

---

## Impact on Danger Warnings

With this BI complete, the Danger Warnings spec simplifies dramatically:

- **No new `danger.py` module** with regex patterns
- **No pattern registry** to maintain
- Add `"danger"` to the JSON schema and system prompt
- The LLM classifies danger contextually as part of the same call
- `parse_response` extracts the field like any other
- Zero extra latency, zero extra cost

The existing Danger Warnings BI (`tactical-danger-warnings.md`) should be updated to depend on this BI and to replace the regex approach with LLM-based classification once this lands.

---

## Out of Scope

- **Forcing backends to use native JSON mode** (e.g., OpenAI's `response_format: { type: "json_object" }`). This is an optimization that can come later. For now, we request JSON via the prompt and parse the text response.
- **Removing the text fallback.** The fallback stays until we have confidence that all backends reliably return JSON.
- **Adding new response fields.** This BI establishes the JSON contract. New fields (danger, confidence, alternatives) are separate BIs that build on this one.
