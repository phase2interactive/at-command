# Self-Improving Prompt Calibration

**Status:** Exploratory Draft
**Date:** 2026-03-23
**Depends on:** Custom User Prompt (tactical backlog)

---

## Overview and Motivation

Every time a user edits an LLM-generated command before running it, that edit encodes a preference the LLM failed to anticipate. Today those corrections are discarded. This feature captures each generated-vs-actually-run pair, measures the gap, detects recurring patterns, and proposes concrete amendments to the user's custom system prompt so the LLM stops making the same mistakes.

The result is a closed feedback loop: use the tool, correct its output, and the tool learns without any explicit teaching step. All data stays local; nothing leaves the machine.

---

## User Stories

| ID | Story |
|----|-------|
| US-1 | As a user who always replaces `find` with `fd`, I want the tool to notice and suggest adding "prefer fd over find" to my config so I stop making the same edit. |
| US-2 | As a user who prefers `docker compose` (v2) over `docker-compose` (v1), I want the system to detect this substitution pattern and offer to encode it. |
| US-3 | As a privacy-conscious user, I want all tracking data stored locally and the ability to disable tracking entirely. |
| US-4 | As a new user, I do not want to see suggestions until the system has enough data to be confident about a pattern. |
| US-5 | As a user who rejects a suggestion, I do not want to be nagged about the same pattern repeatedly. |
| US-6 | As a user reviewing my history, I want to be able to inspect and delete tracked data at any time. |

---

## Data Collection

### What Gets Tracked

Each completed interaction where the user actually runs a command (not cancels) produces one record:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | UUID v4 for the record |
| `timestamp` | string | ISO 8601 UTC timestamp |
| `request` | string | The original natural-language request |
| `generated_cmd` | string | The command returned by the LLM after sanitization |
| `final_cmd` | string | The command the user actually executed (after editing) |
| `edit_distance` | int | Levenshtein distance between `generated_cmd` and `final_cmd` |
| `edit_ratio` | float | Normalized edit distance: `edit_distance / max(len(generated), len(final))` |
| `backend` | string | Backend name (claude, ollama, openai) |
| `model` | string | Model identifier used |
| `shell` | string | Detected shell at time of request |

### When Collection Happens

Collection occurs in `cli.py` at the point where `final_cmd` is known (after the user presses Enter on the editable prompt) and the command is non-empty. If `generated_cmd == final_cmd` (no edit), the record is still stored with `edit_distance = 0` -- zero-edit records are valuable as positive signal that the prompt is working well.

Records are NOT created when:
- The user cancels (Ctrl+C / Escape)
- The final command is empty
- Tracking is disabled in config
- The interaction is in `--json` output mode (non-interactive; no user editing step)

---

## Storage Design

### Format: JSONL

Storage uses newline-delimited JSON (JSONL) for simplicity, appendability, and human readability. Each line is one self-contained JSON object.

**Location:** `~/.local/share/at-cmd/calibration.jsonl`

Follows the XDG Base Directory Specification (`$XDG_DATA_HOME/at-cmd/` with fallback to `~/.local/share/at-cmd/`).

### Example Record

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "timestamp": "2026-03-23T14:30:00Z",
  "request": "find large jpg files",
  "generated_cmd": "find . -name '*.jpg' -size +5M",
  "final_cmd": "fd -e jpg -S +5M",
  "edit_distance": 22,
  "edit_ratio": 0.65,
  "backend": "claude",
  "model": "sonnet",
  "shell": "zsh"
}
```

### Why JSONL Over SQLite

- Append-only writes with no locking, safe for concurrent shell sessions.
- Trivially inspectable with `cat`, `jq`, `head`, `tail`.
- No binary dependency.
- The dataset is small (one record per user interaction) so query performance is irrelevant. Even a power user generating 50 records/day accumulates under 5 MB/year.

### Data Retention

A configurable `calibration_retention_days` setting (default: 90 days). On each write, if the file exceeds a size threshold (default: 1 MB), a background trim removes records older than the retention window. This is lazy garbage collection -- it runs infrequently and only on the write path.

---

## Analysis Algorithm

### Phase 1: Diff Extraction

For each record where `edit_ratio > 0`, compute a structured diff between `generated_cmd` and `final_cmd` using `difflib.SequenceMatcher`. Classify each diff hunk into one of these categories:

| Category | Example | Detection Method |
|----------|---------|-----------------|
| **Tool substitution** | `find` -> `fd`, `grep` -> `rg` | First token of a pipeline segment changes to a different executable |
| **Flag correction** | `-size +5M` -> `-S +5M` | Tokens starting with `-` are added, removed, or replaced |
| **Path fix** | `.` -> `~/projects` | Arguments that look like paths (contain `/` or are `.`, `~`, `..`) change |
| **Syntax adjustment** | Single quotes to double quotes, semicolons to `&&` | Punctuation/operator tokens change |
| **Complete rewrite** | Entire command is different | `edit_ratio > 0.8` |
| **Minor tweak** | Argument value change, e.g., `+5M` -> `+10M` | All other edits |

### Phase 2: Pattern Aggregation

Group extracted diffs by category and specific substitution. A pattern is a `(category, from_value, to_value)` tuple. For tool substitutions this looks like `("tool_sub", "find", "fd")`. For flag corrections it might be `("flag_fix", "--no-color", "--color=never")`.

Count occurrences of each pattern. A pattern becomes a **candidate suggestion** when:

1. It has occurred at least `calibration_suggestion_threshold` times (default: 3).
2. It has a **consistency ratio** of at least 0.75 -- meaning the user makes this specific correction at least 75% of the times the pattern could have applied (i.e., 75% of the times the LLM used the `from_value`, the user changed it to the `to_value`).
3. The pattern has not been previously rejected by the user.

### Phase 3: Confidence Scoring

Each candidate suggestion receives a confidence score:

```
confidence = occurrences * consistency_ratio * recency_weight
```

Where `recency_weight` is an exponential decay giving more weight to recent corrections (half-life of 30 days). This ensures stale patterns fade if the user's preferences change.

Only suggestions with `confidence >= 1.0` are surfaced. This effectively requires the minimum threshold of 3 occurrences with high consistency.

### Complete Rewrites

Records with `edit_ratio > 0.8` are excluded from pattern extraction -- they indicate the LLM was fundamentally wrong rather than exhibiting a correctable pattern. These records are still stored and counted; a separate metric tracks the overall rewrite rate as a proxy for LLM quality.

---

## Suggestion Generation

### When Suggestions Appear

Suggestions are shown at the end of an `at-cmd` interaction, after the user's command has finished executing. This ensures the suggestion does not interrupt the user's workflow. The check runs only if new records have been appended since the last analysis (tracked via a simple counter in the calibration file metadata).

Suggestions are rate-limited to at most one per session (one per invocation of `at-cmd`) and at most one per day for the same pattern.

### Suggestion Format

```
  Tip: You often change "find" to "fd" (5 times in the last 30 days).
  Add to your config?  "Prefer fd over find when available."
  [y] Accept  [n] Dismiss  [x] Never suggest this again
```

Output is rendered to stderr in dim text, consistent with the description line style.

### User Responses

| Input | Effect |
|-------|--------|
| `y` / Enter | Appends the suggestion text to the `custom_prompt` field in `~/.config/at-cmd/config.toml` |
| `n` | Dismisses for now; the pattern can be suggested again if it continues to accumulate |
| `x` | Adds the pattern to a suppression list; it will never be suggested again |

The suppression list is stored in the calibration data file as a separate JSON array at a well-known path: `~/.local/share/at-cmd/suppressed_patterns.json`.

---

## Integration with Custom User Prompt

This feature is designed to feed into the Custom User Prompt feature from the tactical backlog. The relationship:

1. **Custom User Prompt** adds a `custom_prompt` string field to `Config` and appends it to the system prompt built in `llm.py:build_system_prompt()`.
2. **Self-Improving Prompt Calibration** proposes additions to that `custom_prompt` field based on observed patterns.

When a suggestion is accepted:

- If `custom_prompt` is empty, set it to the suggestion text.
- If `custom_prompt` already has content, append the new suggestion on a new line.
- Call `config.save_config()` to persist.

If Custom User Prompt is not yet implemented when this feature ships, accepted suggestions are stored in a pending list (`~/.local/share/at-cmd/pending_prompt_additions.json`) and applied once the config field exists. However, the preferred implementation order is Custom User Prompt first.

---

## Technical Design

### New Module: `src/at_cmd/calibration.py`

Responsible for all calibration logic. Keeps the module under the 1000-line limit by separating concerns:

```
calibration.py
  |-- record_interaction()      # Append a record to the JSONL file
  |-- load_records()            # Read and parse all records
  |-- extract_diffs()           # Phase 1: structured diff for a single record
  |-- aggregate_patterns()      # Phase 2: group and count across records
  |-- generate_suggestions()    # Phase 3: score and filter candidates
  |-- present_suggestion()      # Render a suggestion and handle user input
  |-- apply_suggestion()        # Write accepted suggestion to config
  |-- trim_old_records()        # Data retention cleanup
```

### Key Functions

```python
@dataclass
class InteractionRecord:
    """A single tracked interaction between the user and the LLM."""
    id: str
    timestamp: str
    request: str
    generated_cmd: str
    final_cmd: str
    edit_distance: int
    edit_ratio: float
    backend: str
    model: str
    shell: str


@dataclass
class PatternCandidate:
    """A detected correction pattern with scoring metadata."""
    category: str          # tool_sub, flag_fix, path_fix, syntax_adj
    from_value: str
    to_value: str
    occurrences: int
    consistency_ratio: float
    confidence: float
    suggestion_text: str   # Human-readable prompt addition


def record_interaction(
    generated_cmd: str,
    final_cmd: str,
    request: str,
    backend: str,
    model: str,
    shell: str,
) -> None:
    """Append an interaction record to the calibration log.

    Args:
        generated_cmd: The command the LLM generated.
        final_cmd: The command the user actually ran.
        request: The original natural-language request.
        backend: Backend name used.
        model: Model identifier used.
        shell: Detected shell.
    """


def generate_suggestions(
    min_occurrences: int = 3,
    min_consistency: float = 0.75,
    min_confidence: float = 1.0,
) -> list[PatternCandidate]:
    """Analyze stored records and return actionable suggestions.

    Args:
        min_occurrences: Minimum times a pattern must occur.
        min_consistency: Minimum ratio of consistent corrections.
        min_confidence: Minimum confidence score to surface.

    Returns:
        list[PatternCandidate]: Suggestions sorted by confidence descending.
    """
```

### Integration Points

**`cli.py` -- translate_cmd():**

After the user runs a command (after `subprocess.run(final_cmd, shell=True)`), call `record_interaction()` and optionally `present_suggestion()`:

```python
# After subprocess.run(final_cmd, shell=True)
if config.calibration_enabled:
    from at_cmd.calibration import record_interaction, present_suggestion

    record_interaction(
        generated_cmd=command,
        final_cmd=final_cmd,
        request=user_prompt,
        backend=config.backend,
        model=config.model,
        shell=shell_ctx.shell,
    )
    present_suggestion(config)
```

**`config.py` -- Config dataclass:**

New fields:

```python
calibration_enabled: bool = True
calibration_suggestion_threshold: int = 3
calibration_retention_days: int = 90
```

**`llm.py` -- build_system_prompt():**

No changes needed in this module. The custom prompt integration happens via the Custom User Prompt feature, which concatenates the `custom_prompt` config field into the system prompt.

### New CLI Subcommand: `at-cmd calibration`

```
at-cmd calibration status    # Show record count, top patterns, last suggestion date
at-cmd calibration history   # Print recent records as a table
at-cmd calibration clear     # Delete all calibration data (with confirmation)
at-cmd calibration suggest   # Manually trigger suggestion analysis
```

---

## Configuration

All calibration settings live in `~/.config/at-cmd/config.toml` under a `[calibration]` section:

```toml
[calibration]
enabled = true                  # Master switch for all tracking
suggestion_threshold = 3        # Minimum pattern occurrences before suggesting
retention_days = 90             # Days to keep records before trimming
suggestion_cooldown_hours = 24  # Minimum hours between suggestions for the same pattern
```

Environment variable overrides follow the existing convention:

| Env Var | Config Key |
|---------|-----------|
| `AT_CMD_CALIBRATION_ENABLED` | `calibration.enabled` |
| `AT_CMD_CALIBRATION_THRESHOLD` | `calibration.suggestion_threshold` |
| `AT_CMD_CALIBRATION_RETENTION` | `calibration.retention_days` |

---

## Privacy Considerations

1. **All data is local.** The calibration JSONL file and suppression list never leave the machine. No telemetry, no phone-home, no cloud sync.
2. **No command output is stored.** Only the command text and natural-language request are recorded, never stdout/stderr from execution.
3. **Tracking is opt-out.** Enabled by default (to maximize usefulness), but a single config toggle disables all collection and suggestion.
4. **Data is inspectable.** The JSONL format is human-readable. `at-cmd calibration history` provides a formatted view. `at-cmd calibration clear` deletes everything.
5. **Retention is bounded.** Records older than `retention_days` are automatically pruned.
6. **Requests may contain sensitive info.** The natural-language request field could contain sensitive context (e.g., "connect to prod-db-01"). Users concerned about this should disable tracking or use `at-cmd calibration clear` periodically. The spec does NOT attempt to auto-redact because reliable redaction is unsolvable in the general case.

---

## Edge Cases

### Too Few Data Points

If fewer than `suggestion_threshold` records exist overall, skip analysis entirely. Do not show "no suggestions yet" messages -- the feature should be invisible until it has something useful to say.

### Conflicting Patterns

The same `from_value` maps to different `to_value` entries across different records (e.g., user sometimes changes `find` to `fd` and sometimes to `locate`). Resolution: only surface a suggestion if one `to_value` dominates with at least 75% consistency. If no single target dominates, suppress all suggestions for that `from_value` until a clear winner emerges.

### User Rejects a Suggestion

A `n` (dismiss) response does nothing permanent. The pattern continues to accumulate and may be re-suggested after the cooldown period if the user keeps making the same correction. An `x` (never) response permanently suppresses that specific `(from_value, to_value)` pair.

### Suggestion Already in Custom Prompt

Before proposing a suggestion, check if the `custom_prompt` field already contains the suggested text (or a semantically similar instruction, checked via simple substring matching on the key terms). Skip if already present.

### Backend or Model Change

Records include backend and model metadata. When the user switches models, old patterns may not apply. The analysis weights recent records more heavily via the recency decay, which naturally handles model transitions. A hard model-switch reset is not performed because many patterns (tool preferences, path conventions) are user preferences independent of the model.

### Inline Mode (Shell Integration)

In inline mode, the shell integration script calls `at-cmd translate --json` and handles the editable buffer itself. The JSON output path does not have a user editing step visible to `at-cmd`. To support tracking in inline mode, the shell integration script must call a new endpoint after the user runs the command:

```bash
at-cmd calibration record --generated "$generated" --final "$final" --request "$request"
```

This is a future enhancement. The initial implementation covers submit mode only.

### Concurrent Shell Sessions

JSONL append is atomic on POSIX systems for writes under the pipe buffer size (typically 4096 bytes). A single calibration record is well under this limit, so concurrent appends from multiple shell sessions are safe without file locking.

---

## Testing Strategy

### Unit Tests (`tests/test_calibration.py`)

| Test | Description |
|------|-------------|
| `test_record_interaction_creates_file` | First record creates the JSONL file and parent directories |
| `test_record_interaction_appends` | Subsequent records append without corrupting existing data |
| `test_edit_distance_calculation` | Verify Levenshtein distance and ratio for known pairs |
| `test_extract_diffs_tool_substitution` | `find` -> `fd` is classified as `tool_sub` |
| `test_extract_diffs_flag_correction` | `-size +5M` -> `-S +5M` is classified as `flag_fix` |
| `test_extract_diffs_complete_rewrite` | High edit ratio records are excluded from pattern extraction |
| `test_aggregate_patterns_threshold` | Patterns below threshold are not returned |
| `test_aggregate_patterns_consistency` | Inconsistent patterns (below 75%) are filtered out |
| `test_confidence_scoring_recency` | Recent records contribute more to confidence than old ones |
| `test_generate_suggestions_empty_data` | Returns empty list when no records exist |
| `test_generate_suggestions_suppressed` | Suppressed patterns are excluded from results |
| `test_suggestion_already_in_prompt` | Duplicate suggestions are not proposed |
| `test_apply_suggestion_empty_prompt` | Accepted suggestion sets `custom_prompt` when empty |
| `test_apply_suggestion_appends` | Accepted suggestion appends to existing `custom_prompt` |
| `test_trim_old_records` | Records older than retention window are removed |
| `test_concurrent_append_safety` | Multiple rapid appends produce valid JSONL |
| `test_tracking_disabled` | No file is created or modified when `calibration_enabled = False` |

### Integration Tests

- End-to-end: simulate a sequence of interactions with edits, verify that after the threshold is met, `generate_suggestions()` returns the expected pattern.
- CLI subcommand tests: `at-cmd calibration status`, `at-cmd calibration clear` work correctly.

### Fixtures

- A pre-built JSONL file with known patterns for deterministic analysis testing.
- A `tmp_path` fixture for all file operations to avoid polluting the real data directory.

---

## Out of Scope

The following are explicitly excluded from this spec:

- **Automatic prompt modification without user consent.** Suggestions are always presented for approval.
- **Cloud sync or sharing of calibration data.** All data is local-only.
- **Semantic diff analysis.** The analysis uses token-level string comparison, not LLM-powered semantic understanding of command equivalence.
- **Inline mode tracking.** The initial implementation covers submit mode only. Inline mode requires shell integration changes and is deferred.
- **Team/shared calibration profiles.** Organizational prompt sharing is a separate feature.
- **Auto-detection of installed tools.** This feature observes user corrections, not the filesystem. Tool detection is a separate backlog item.
- **Undo for accepted suggestions.** If a user accepts a bad suggestion, they can manually edit `config.toml` to remove it. A dedicated undo mechanism is not included in v1.
