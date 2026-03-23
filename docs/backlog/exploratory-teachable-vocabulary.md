# Teachable Personal Vocabulary

**Status:** Exploratory Draft
**Date:** 2026-03-23
**Depends on:** Core translate flow (cli.py, llm.py, sanitize.py)

---

## Overview and Motivation

Today, `at-cmd` is stateless. Every request starts from scratch -- the LLM has no memory of what worked for this particular user. If the user always prefers `fd` over `find`, or always wants `docker compose` instead of `docker-compose`, the LLM keeps getting it wrong and the user keeps editing. That editing effort is wasted knowledge.

Teachable Personal Vocabulary turns `at-cmd` into a tool that improves with use. It captures the relationship between what the user asked for and what they actually ran (after editing), stores those pairs locally, and injects the most relevant ones into future LLM prompts as "user-preferred patterns." The entire vocabulary lives on the user's machine. Nothing is sent upstream except what already flows through the LLM prompt.

Two learning channels:

1. **Automatic correction detection** -- when the user edits a suggested command before running it, the system silently records the before/after pair.
2. **Explicit teaching** -- the user runs `at-cmd learn` to manually define a mapping from a natural-language phrase to a preferred command.

---

## User Stories

| ID | Story |
|----|-------|
| V1 | As a user who always changes `find` to `fd`, I want `at-cmd` to learn my preference so future suggestions use `fd` by default. |
| V2 | As a user, I want to explicitly teach `at-cmd` that "show my ip" means `curl ifconfig.me` so it returns my preferred command immediately. |
| V3 | As a user, I want to browse and manage my stored vocabulary so I can remove stale or incorrect entries. |
| V4 | As a user, I want to export my vocabulary to a file and import it on another machine or share it with my team. |
| V5 | As a user, I want to disable automatic learning if I only want explicit entries. |
| V6 | As a user, I want vocabulary matches to improve LLM output without overriding it entirely -- the LLM should still use its judgment for novel requests. |

---

## Detailed UX

### Automatic Correction Detection

When the user edits a command in the interactive prompt (submit mode) before pressing Enter, the system detects the delta:

```
$ @ find large jpg files
  # Find JPG files larger than 5MB in the current directory
> find . -name '*.jpg' -size +5M_           <-- LLM suggested this
> fd -e jpg -S +5M_                          <-- user edited to this, pressed Enter
```

After execution, `at-cmd` compares the original suggestion to the final command. If they differ materially (not just whitespace or trailing characters), the system stores:

```
request:            "find large jpg files"
original_command:   "find . -name '*.jpg' -size +5M"
corrected_command:  "fd -e jpg -S +5M"
timestamp:          2026-03-23T14:22:00Z
source:             "auto"
```

The recording happens silently -- no extra prompts, no confirmation. The user's flow is uninterrupted.

**Material difference threshold:** A correction is recorded only when the Levenshtein ratio between the original and final command is below 0.85 (i.e., more than 15% of characters changed). This avoids recording trivial typo fixes or path adjustments as "corrections."

### `at-cmd learn` Subcommand

Explicit teaching for when the user knows exactly what mapping they want:

```bash
# Full syntax
at-cmd learn "show my ip" "curl ifconfig.me"

# With description (optional third argument)
at-cmd learn "show my ip" "curl ifconfig.me" "Public IPv4 via ifconfig.me"
```

Behavior:
- If an entry with the same request text already exists, prompt the user to confirm overwrite.
- Validate that the command argument is non-empty.
- Print confirmation: `Learned: "show my ip" -> curl ifconfig.me`
- The entry is stored with `source: "manual"`.

If called with `--force` / `-f`, skip the overwrite confirmation.

### `at-cmd vocab` Subcommand

Browse and manage the stored vocabulary:

```bash
# List all entries (default: most recent first, tabular)
at-cmd vocab

# Example output:
#   Request                  Command                    Source   Age
#   show my ip               curl ifconfig.me           manual   2d
#   find large jpg files     fd -e jpg -S +5M           auto     5d
#   kill port 3000           lsof -ti:3000 | xargs kill auto     1w
#   (42 entries total)

# Search entries by keyword
at-cmd vocab --search "docker"

# Delete a specific entry by its request text
at-cmd vocab --delete "show my ip"

# Delete all entries (with confirmation)
at-cmd vocab --clear

# Export to JSONL file
at-cmd vocab --export vocab-backup.jsonl

# Import from JSONL file (additive, does not overwrite existing)
at-cmd vocab --import team-vocab.jsonl

# Import with overwrite (existing entries with same request text are replaced)
at-cmd vocab --import team-vocab.jsonl --overwrite
```

The `--export` / `--import` flags enable team sharing and machine migration.

---

## Storage Design

### Format: JSONL

The vocabulary is stored as a JSONL (JSON Lines) file rather than SQLite. Rationale:

- No additional dependency (no `sqlite3` import gymnastics, no migration tooling).
- Human-readable and diffable -- users can inspect and hand-edit the file.
- Trivially exportable (the file *is* the export).
- Append-only writes for auto-learned entries are safe without locking.
- Performance is adequate up to tens of thousands of entries (the entire file is small enough to load into memory).

### Location

```
~/.local/share/at-cmd/vocabulary.jsonl
```

Follows the XDG Base Directory Specification (`$XDG_DATA_HOME/at-cmd/` if set, otherwise `~/.local/share/at-cmd/`). On macOS, this is conventional for non-config application data.

### Schema

Each line is a JSON object:

```json
{
  "request": "find large jpg files",
  "original_command": "find . -name '*.jpg' -size +5M",
  "corrected_command": "fd -e jpg -S +5M",
  "description": "Find JPG files over 5MB using fd",
  "source": "auto",
  "created_at": "2026-03-23T14:22:00Z",
  "updated_at": "2026-03-23T14:22:00Z",
  "use_count": 0
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `request` | string | yes | The natural-language request that triggered the entry. |
| `original_command` | string | no | The LLM's original suggestion (null for manual entries). |
| `corrected_command` | string | yes | The command the user actually wants. |
| `description` | string | no | Optional human description of what the command does. |
| `source` | string | yes | `"auto"` (correction detection) or `"manual"` (`at-cmd learn`). |
| `created_at` | string | yes | ISO 8601 timestamp of creation. |
| `updated_at` | string | yes | ISO 8601 timestamp of last update. |
| `use_count` | int | yes | Number of times this entry was injected into a prompt. |

### File Operations

- **Auto-learn writes:** Append a new line to the file. No read required.
- **Manual learn writes:** Read the file to check for duplicates, then append or rewrite the relevant line.
- **Reads (for matching):** Load the entire file into memory at startup. For a 10,000-entry vocabulary this is roughly 2-3 MB -- negligible.
- **Deletes / updates:** Read all lines, filter/modify, rewrite the file atomically (write to a temp file, then rename).

---

## Matching Algorithm

When a new translation request arrives, the system searches the vocabulary for relevant prior corrections to inject as context.

### Step 1: Candidate Retrieval

Load all vocabulary entries. For each entry, compute a similarity score between the new request and the stored `request` field.

### Step 2: Similarity Scoring

Use a two-tier approach (no external dependencies):

1. **Token overlap (Jaccard similarity):** Split both strings into lowercase word tokens. Compute `|intersection| / |union|`. This catches rephrased but semantically identical requests ("find big jpgs" vs "find large jpg files").

2. **Subsequence ratio:** Use `difflib.SequenceMatcher` (stdlib) to compute the ratio between the two strings. This catches requests with similar structure but different parameters ("find large png files" matches "find large jpg files").

The final score is a weighted blend:

```
score = 0.4 * jaccard + 0.6 * sequence_ratio
```

The sequence ratio gets higher weight because word order and phrasing matter for command translation.

### Step 3: Threshold and Ranking

- **Match threshold:** score >= 0.45. Below this, the entry is ignored.
- **Maximum injected entries:** 3. If more than 3 entries match, take the top 3 by score. Ties are broken by `use_count` (more-used entries win), then by `updated_at` (more recent wins).

### Step 4: Boost for Exact Matches

If any entry has a Jaccard score of 1.0 (identical token set), it is always included regardless of the threshold, and it is ranked first. This ensures that explicit `at-cmd learn` entries for the exact phrase are always respected.

---

## System Prompt Injection

Matched vocabulary entries are appended to the system prompt as a structured block, placed after the base system prompt but before the user request.

### Injection Format

```
<existing system prompt>

The user has indicated these personal command preferences. When the request
closely matches one of these patterns, prefer the user's preferred command
style. You may adapt flags or arguments as needed for the specific request.

- "find large jpg files" -> fd -e jpg -S +5M
- "show my ip" -> curl ifconfig.me
- "kill port 3000" -> lsof -ti:3000 | xargs kill
```

### Integration Point

The injection happens in `build_system_prompt()` (in `llm.py`). The function signature changes to accept an optional list of vocabulary matches:

```python
def build_system_prompt(
    ctx: ShellContext,
    vocab_matches: list[VocabEntry] | None = None,
) -> str:
```

If `vocab_matches` is empty or None, the prompt is identical to today's output. This preserves full backward compatibility.

### Prompt Budget

Each injected entry adds roughly 60-80 tokens. With a max of 3 entries, the vocabulary block adds at most ~250 tokens to the prompt. This is well within budget for all supported backends.

---

## Technical Design

### New Module: `src/at_cmd/vocabulary.py`

This module owns all vocabulary operations. Approximate public API:

```python
@dataclass
class VocabEntry:
    """A single vocabulary entry."""
    request: str
    original_command: str | None
    corrected_command: str
    description: str
    source: str  # "auto" | "manual"
    created_at: str
    updated_at: str
    use_count: int


def get_vocab_path() -> Path:
    """Return the path to the vocabulary JSONL file."""

def load_vocab() -> list[VocabEntry]:
    """Load all vocabulary entries from disk."""

def save_vocab(entries: list[VocabEntry]) -> None:
    """Atomically rewrite the vocabulary file."""

def append_entry(entry: VocabEntry) -> None:
    """Append a single entry to the vocabulary file."""

def find_matches(request: str, entries: list[VocabEntry], max_results: int = 3) -> list[VocabEntry]:
    """Return the top matching entries for a given request."""

def compute_similarity(a: str, b: str) -> float:
    """Compute blended similarity score between two request strings."""

def is_material_correction(original: str, corrected: str) -> bool:
    """Return True if the edit exceeds the material difference threshold."""

def delete_entry(request: str) -> bool:
    """Delete an entry by request text. Returns True if found and deleted."""

def clear_all() -> int:
    """Delete all entries. Returns the count of deleted entries."""

def export_vocab(path: Path) -> int:
    """Export vocabulary to a JSONL file. Returns entry count."""

def import_vocab(path: Path, overwrite: bool = False) -> tuple[int, int]:
    """Import vocabulary from a JSONL file. Returns (added, skipped) counts."""
```

### Integration Points

#### 1. `cli.py` -- Correction Detection in `translate_cmd`

After the user presses Enter on the editable prompt, compare the original command to the final command:

```python
# After the user submits the edited command:
if final_cmd.strip() and final_cmd != command:
    from at_cmd.vocabulary import is_material_correction, append_entry, VocabEntry
    if cfg.vocab_auto_learn and is_material_correction(command, final_cmd):
        entry = VocabEntry(
            request=user_prompt,
            original_command=command,
            corrected_command=final_cmd.strip(),
            description=description,
            source="auto",
            created_at=now_iso(),
            updated_at=now_iso(),
            use_count=0,
        )
        append_entry(entry)
```

This block is wrapped in a try/except that silently catches all exceptions -- vocabulary recording must never interrupt the user's command execution.

#### 2. `cli.py` -- Vocabulary Lookup Before LLM Call

Before calling the backend, load the vocabulary and find matches:

```python
from at_cmd.vocabulary import load_vocab, find_matches

vocab = load_vocab()
matches = find_matches(user_prompt, vocab)

system_prompt = build_system_prompt(shell_ctx, vocab_matches=matches)
```

If the vocabulary file does not exist or is empty, `load_vocab()` returns an empty list and `find_matches()` returns an empty list. Zero overhead in the no-vocabulary case.

#### 3. `llm.py` -- Prompt Construction

`build_system_prompt` gains an optional `vocab_matches` parameter. If matches are present, append the preference block to the prompt string.

#### 4. `cli.py` -- New Subcommands

Register `learn` and `vocab` as Click subcommands on the `main` group, following the existing pattern (`setup`, `config`, `init`).

#### 5. `config.py` -- New Configuration Fields

```python
@dataclass
class Config:
    # ... existing fields ...
    vocab_auto_learn: bool = True
    vocab_max_entries: int = 5000
```

Corresponding environment variables: `AT_CMD_VOCAB_AUTO_LEARN`, `AT_CMD_VOCAB_MAX_ENTRIES`.

TOML config:
```toml
vocab_auto_learn = true
vocab_max_entries = 5000
```

---

## Configuration

| Key | Env Var | Default | Description |
|-----|---------|---------|-------------|
| `vocab_auto_learn` | `AT_CMD_VOCAB_AUTO_LEARN` | `true` | Record corrections automatically when the user edits a command. |
| `vocab_max_entries` | `AT_CMD_VOCAB_MAX_ENTRIES` | `5000` | Maximum stored entries. When exceeded, the oldest auto-learned entries are pruned first (manual entries are preserved until the cap is still exceeded). |

Disabling `vocab_auto_learn` does not disable vocabulary matching -- previously stored entries and manual entries are still used. It only stops new automatic recordings. To fully disable vocabulary, set `vocab_max_entries = 0`.

---

## Edge Cases

### Conflicting Corrections

The user corrects the same request in different ways on different occasions:

- `"list files"` -> `ls -la` (Tuesday)
- `"list files"` -> `exa -la` (Thursday)

**Resolution:** The most recent correction wins. When an auto-learned entry arrives for a request that already exists, the existing entry is updated in place (rewriting `corrected_command`, `updated_at`, and incrementing `use_count`). The old command is discarded. Rationale: the user's most recent preference is the best signal.

For manual entries created via `at-cmd learn`, the user is prompted to confirm the overwrite (unless `--force` is passed).

### Stale Entries

A user's preferred tool changes over time (e.g., they switch from `exa` to `eza`).

**Resolution:** Entries that have not been matched in over 180 days could be considered stale. However, automatic pruning of stale entries is deferred to a future iteration. For now, users manage staleness manually via `at-cmd vocab --delete`. The `Age` column in `at-cmd vocab` output makes old entries visible.

### Very Large Vocabulary

At 5,000 entries (the default cap), the JSONL file is approximately 1-1.5 MB. Loading and scanning this takes under 10ms on modern hardware. The matching algorithm is O(n) over all entries with stdlib string operations -- no external index is needed.

If a user somehow reaches the cap:
1. Sort all entries by `(source == "auto", updated_at)` ascending -- auto-learned entries with the oldest update time come first.
2. Remove entries from the front of this sorted list until the count is at or below the cap.
3. Manual entries are pruned only after all auto-learned entries are exhausted.

### Partial / Aborted Commands

If the user presses Ctrl+C or Escape to cancel without running the command, no vocabulary entry is recorded. A correction is only meaningful when the user actually ran the edited command.

### Empty Edits

If the user clears the command entirely and presses Enter (empty `final_cmd`), no vocabulary entry is recorded. The existing code already handles this case by skipping execution.

### Inline Mode

In inline mode, the command is edited in the shell buffer, not in `at-cmd`'s interactive prompt. The `at-cmd` process has already exited by the time the user edits and runs the command. Therefore, **automatic correction detection does not work in inline mode** -- only submit mode supports it. This limitation should be documented clearly.

Users who primarily use inline mode can still build their vocabulary via `at-cmd learn`.

---

## Testing Strategy

Tests live in `tests/test_vocabulary.py`.

### Unit Tests for `vocabulary.py`

| Test | Category |
|------|----------|
| `test_append_and_load_roundtrip` -- write an entry, read it back, verify fields. | Expected use |
| `test_load_empty_file` -- returns empty list when file does not exist. | Edge case |
| `test_load_malformed_jsonl` -- skips malformed lines, loads valid ones. | Failure case |
| `test_find_matches_exact` -- exact request text returns score above threshold. | Expected use |
| `test_find_matches_similar` -- rephrased request returns the right entry. | Expected use |
| `test_find_matches_no_match` -- unrelated request returns empty list. | Edge case |
| `test_find_matches_respects_max_results` -- returns at most N entries. | Edge case |
| `test_compute_similarity_identical` -- identical strings score 1.0. | Expected use |
| `test_compute_similarity_unrelated` -- unrelated strings score below threshold. | Edge case |
| `test_is_material_correction_trivial` -- whitespace-only change returns False. | Edge case |
| `test_is_material_correction_significant` -- tool swap returns True. | Expected use |
| `test_delete_entry_exists` -- deletes and returns True. | Expected use |
| `test_delete_entry_missing` -- returns False when not found. | Failure case |
| `test_clear_all` -- removes all entries, returns count. | Expected use |
| `test_export_import_roundtrip` -- export then import produces identical vocabulary. | Expected use |
| `test_import_no_overwrite` -- existing entries are preserved. | Edge case |
| `test_import_with_overwrite` -- existing entries are replaced. | Edge case |
| `test_max_entries_pruning` -- auto entries pruned before manual entries. | Edge case |
| `test_conflicting_corrections_latest_wins` -- second correction updates the entry. | Edge case |

### Integration Tests

| Test | Category |
|------|----------|
| `test_translate_records_correction` -- mock the LLM, simulate an edit, verify an entry was appended. | Expected use |
| `test_translate_no_record_on_cancel` -- Ctrl+C produces no vocabulary entry. | Edge case |
| `test_translate_no_record_when_disabled` -- `vocab_auto_learn=False` skips recording. | Edge case |
| `test_prompt_injection_with_matches` -- verify the system prompt contains the vocabulary block when matches exist. | Expected use |
| `test_prompt_no_injection_without_matches` -- verify the system prompt is unchanged when no matches exist. | Edge case |
| `test_learn_subcommand` -- CLI `learn` stores the entry correctly. | Expected use |
| `test_learn_overwrite_prompt` -- duplicate request triggers confirmation. | Edge case |
| `test_vocab_list_output` -- CLI `vocab` produces tabular output. | Expected use |
| `test_vocab_search_filters` -- `--search` filters entries. | Expected use |
| `test_vocab_delete` -- `--delete` removes the specified entry. | Expected use |

All tests should use `tmp_path` fixtures to avoid touching the real vocabulary file.

---

## Out of Scope

The following are explicitly not part of this feature and are deferred to future work:

- **Semantic / embedding-based matching.** The stdlib similarity approach is sufficient for the expected vocabulary sizes. Embedding search would require a vector database or external dependency.
- **Automatic staleness pruning.** Entries do not auto-expire. Users manage their vocabulary manually.
- **Inline mode correction detection.** The `at-cmd` process is not involved in the user's shell buffer edits after inline replacement. Supporting this would require shell-side hooks that report back to `at-cmd`.
- **Collaborative / remote vocabulary sync.** Sharing is supported only via file export/import. Real-time sync, conflict resolution, and remote storage are out of scope.
- **Per-directory or per-project vocabulary.** All entries are global. Project-scoped vocabulary could layer on top later.
- **Prompt calibration feedback loop.** The related "Self-Improving Prompt Calibration" exploratory idea (tracking edit distance over time and auto-proposing config amendments) is a separate feature that could build on top of vocabulary data.
- **TUI integration for vocabulary management.** The existing `at-cmd config` TUI is not extended. Vocabulary management is CLI-only for now.
