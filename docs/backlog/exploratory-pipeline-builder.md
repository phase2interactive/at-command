# Feature Spec: Command Pipeline Builder

**Status:** Exploratory Draft
**Date:** 2026-03-23
**Origin:** exploratory.md -- "Command Pipeline Builder ('then' Chaining)"

---

## Overview

The Pipeline Builder extends at-cmd to handle multi-step natural language
requests. Instead of producing a single command, the user describes a
workflow using connectives like "then," "and then," or "after that," and
at-cmd decomposes the request into discrete steps, translates each one, and
assembles them into a single composable shell pipeline.

```
@ find large log files then compress them then move to /archive
```

Produces:

```
find . -name '*.log' -size +100M -exec gzip {} \; && mv *.log.gz /archive/
Move large logs to /archive after compressing
```

The user still reviews and edits the final command before execution. The core
safety guarantee -- nothing runs without user confirmation -- is preserved.

---

## Motivation

Non-expert users think in sequential steps, not in pipes and subshells.
Asking them to compose `find ... | xargs gzip && mv ...` requires knowledge
they may not have. Today, at-cmd handles one intent per invocation. If the
user wants a multi-step workflow, they must invoke at-cmd multiple times and
manually stitch results together.

Pipeline Builder bridges that gap:

1. It lets users describe workflows the way they think about them.
2. It teaches shell composition by showing how steps become pipes and chains.
3. It keeps at-cmd relevant for non-trivial tasks that would otherwise require
   a script.

---

## User Stories

**US-1: Basic chaining.** As a developer, I want to type
`@ find TODO comments in python files then count them` and get
`grep -rn 'TODO' --include='*.py' | wc -l` so I do not have to remember
pipe syntax.

**US-2: File-operation workflow.** As a sysadmin, I want to type
`@ find log files older than 30 days then compress them then delete the originals`
and get a safe, reviewable compound command.

**US-3: Step-by-step preview.** As a cautious user, I want to see each step
of the pipeline individually before the final composed command is shown, so I
can understand what each piece does.

**US-4: Graceful single-step fallback.** As any user, I want
`@ list running docker containers` (no chaining words) to behave exactly as
it does today, with no extra latency or UX changes.

**US-5: Inline mode compatibility.** As a power user, I want pipeline
building to work in inline mode (hotkey trigger), replacing the buffer with
the assembled pipeline, with undo restoring my original text.

**US-6: JSON output.** As a script author, I want `--json` mode to return
the full pipeline plus per-step metadata so I can integrate programmatically.

---

## Detailed UX

### Natural Language Parsing

The user's request is scanned for step-boundary connectives. The following
patterns (case-insensitive) are recognized as step separators:

| Pattern             | Example                                       |
|---------------------|-----------------------------------------------|
| `then`              | find files **then** compress them              |
| `and then`          | list processes **and then** sort by memory     |
| `after that`        | download the file **after that** extract it    |
| `and`               | create a directory **and** move files into it  |
| `pipe to` / `pipe into` | list files **pipe to** grep for python    |
| `, then`            | count lines, **then** sort                     |

"and" is the most ambiguous connective. The parser should only treat "and" as
a step boundary when it separates two verb-led clauses. A phrase like
"find and replace" should NOT be split. The heuristic: "and" is a step
boundary only when the word following it can be identified as an imperative
verb (e.g., "move," "delete," "sort," "compress," "copy," "run," "show,"
"list," "count," "send," "pipe," "redirect," "open," "close," "restart,"
"kill"). When in doubt, the parser should NOT split -- it is better to send a
combined phrase to the LLM than to split incorrectly.

### Submit Mode Flow

```
$ @ find large log files then compress them then move to /archive
  translating step 1/3...
  Step 1: find . -name '*.log' -size +100M
          Find log files over 100MB
  translating step 2/3...
  Step 2: gzip {}
          Compress each file with gzip
  translating step 3/3...
  Step 3: mv *.log.gz /archive/
          Move compressed files to /archive

  Pipeline:
  # Find large logs, compress, and move to /archive
> find . -name '*.log' -size +100M -exec gzip {} \; && mv *.log.gz /archive/
```

The spinner updates with the current step number. Each step's individual
command and description are shown as dim text on stderr. The final composed
command is presented in the standard editable prompt. The user edits and
confirms as usual.

### Inline Mode Flow

In inline mode, step-by-step preview is suppressed (there is no room in the
shell buffer for it). The spinner shows `translating (3 steps)...` and the
buffer is replaced with the final assembled command. The description line
below the buffer summarizes the entire pipeline. Undo restores the original
`@ ...` text as usual.

### JSON Output

```json
{
  "command": "find . -name '*.log' -size +100M -exec gzip {} \\; && mv *.log.gz /archive/",
  "description": "Find large logs, compress, and move to /archive",
  "pipeline": true,
  "steps": [
    {
      "input": "find large log files",
      "command": "find . -name '*.log' -size +100M",
      "description": "Find log files over 100MB"
    },
    {
      "input": "compress them",
      "command": "gzip {}",
      "description": "Compress each file with gzip"
    },
    {
      "input": "move to /archive",
      "command": "mv *.log.gz /archive/",
      "description": "Move compressed files to /archive"
    }
  ]
}
```

When `--json` is passed, the output includes the `pipeline` flag and a
`steps` array. Single-step requests set `pipeline: false` and omit `steps`.

---

## Request Decomposition

### Splitting Algorithm

The decomposition happens client-side before any LLM call. This keeps the
logic deterministic and avoids spending tokens on parsing.

```
Input:  "find large log files then compress them then move to /archive"
Tokens: ["find large log files", "compress them", "move to /archive"]
```

Steps:

1. **Normalize** -- collapse whitespace, strip leading/trailing space.
2. **Scan for connectives** -- use a regex that matches the connective
   patterns listed above. The regex respects word boundaries to avoid
   splitting inside words (e.g., "authentic" contains "then" but must not
   be split).
3. **Split** -- produce a list of step strings. Each step is trimmed.
4. **Validate** -- if only one step results, fall through to the standard
   single-command translate path. If more than `max_pipeline_steps` result,
   reject with an error message.

### Proposed regex

```python
import re

_CONNECTIVES = re.compile(
    r"""
    \s*,?\s*               # optional leading comma + whitespace
    (?:
        and\s+then          # "and then"
      | after\s+that        # "after that"
      | then                # "then"
      | pipe\s+(?:to|into)  # "pipe to" / "pipe into"
      | and\s+(?=\b(?:move|delete|sort|compress|copy|run|show|list|
                      count|send|pipe|redirect|open|close|restart|
                      kill|find|grep|create|remove|rename|extract|
                      download|upload|zip|unzip|tar|cat|echo|print|
                      write|read|check|install|update|start|stop)\b)
    )
    \s+                     # trailing whitespace
    """,
    re.IGNORECASE | re.VERBOSE,
)

steps = _CONNECTIVES.split(user_prompt)
steps = [s.strip() for s in steps if s.strip()]
```

The "and" branch uses a lookahead for known imperative verbs. This list is
intentionally conservative and can be extended via configuration in the
future.

### Carrying Context Forward

Each step after the first needs context about what came before. The user
might say "compress them" -- "them" refers to the output of the previous
step. The per-step LLM prompt includes:

- The original full request (for overall intent).
- The previous step's translated command (so the LLM knows what output to
  expect).
- The current step's natural language fragment.

---

## LLM Interaction Design

### Option A: One Call Per Step (Recommended)

Each step is translated with a separate LLM call. The system prompt is
extended with pipeline context.

**Advantages:**
- Each call stays within the existing two-line response contract.
- Errors are isolated to one step -- the user sees exactly which step failed.
- Steps can be retried independently.
- The existing `sanitize_response` function works unchanged.

**Disadvantages:**
- N steps means N LLM calls. Latency scales linearly.
- Requires a pipeline-aware system prompt variant.

### Option B: Single Call with Structured Output

A single LLM call receives all steps at once and returns a structured
multi-line response (e.g., numbered steps).

**Advantages:**
- Single round trip -- lower total latency.
- The LLM sees all steps at once and can optimize the overall pipeline.

**Disadvantages:**
- Breaks the two-line response contract. Requires a new sanitizer.
- Harder to attribute errors to specific steps.
- Larger prompt surface for hallucination.

### Decision: Option A

Option A is recommended for the initial implementation. It reuses existing
infrastructure, preserves the two-line contract, and keeps error handling
simple. The latency cost is acceptable because:

- Typical pipelines are 2-4 steps.
- Steps can potentially be parallelized when they are independent (though
  most are sequential by nature).
- The streaming ghost-text feature (separate exploratory item) would mask
  perceived latency.

Option B can be revisited as an optimization once the feature is validated.

### Per-Step System Prompt

For step 1, use the standard `build_system_prompt`. For steps 2..N, append:

```
The user is building a multi-step pipeline.
The previous step produced this command: {prev_command}
Now translate the next step. The user said: "{step_text}"
The result should compose with the previous command.
Return EXACTLY two lines:
Line 1: The {shell} command for this step only (no backticks, no markdown)
Line 2: A brief description (10 words max)
```

The per-step prompt explicitly asks for "this step only" to prevent the LLM
from returning the entire pipeline.

---

## Pipeline Assembly

After all steps are individually translated, the assembler combines them into
a single command string. The connector between steps depends on how the
commands relate.

### Connector Selection

| Relationship                  | Connector | Example                                 |
|-------------------------------|-----------|-----------------------------------------|
| Output of A feeds input of B  | `\|`      | `ls \| grep foo`                        |
| A must succeed before B runs  | `&&`      | `mkdir /tmp/x && cd /tmp/x`             |
| A and B are independent       | `;`       | `echo start; sleep 5`                   |
| A operates on files found by B| `-exec`   | `find . -name '*.log' -exec gzip {} \;` |

Connector selection is non-trivial. Rather than building a rule engine, the
assembler delegates this decision to a final LLM call: the "compose" call.

### Compose Call

After all per-step translations complete, a final LLM call receives:

- The original full request.
- The ordered list of per-step commands and descriptions.
- An instruction to compose them into a single shell command using
  appropriate connectors.

System prompt for the compose call:

```
You are a shell command composer for {shell} on {os}.
The user asked: "{original_request}"

The following steps were translated individually:
Step 1: {command_1}  -- {description_1}
Step 2: {command_2}  -- {description_2}
...

Combine these into a single {shell} command using appropriate connectors
(pipes, &&, ;, -exec, subshells, etc.) so the pipeline works correctly.
Return EXACTLY two lines:
Line 1: The composed {shell} command (no backticks, no markdown, one line)
Line 2: A brief description (10 words max) of the full pipeline
```

This approach lets the LLM choose the right connectors and restructure
commands as needed (for example, folding a separate `gzip` step into a
`find -exec` clause). The compose call reuses `sanitize_response` unchanged.

### Fallback

If the compose call fails (SanitizeError, BackendError), fall back to
joining the per-step commands with `&&`. This is the safest default -- each
step runs only if the previous one succeeded.

---

## Technical Design

### New Module: `src/at_cmd/pipeline.py`

```
pipeline.py
  |
  |-- split_request(text: str) -> list[str]
  |     Parse natural language into step fragments.
  |     Returns a single-element list for non-pipeline requests.
  |
  |-- translate_pipeline(
  |       steps: list[str],
  |       original_request: str,
  |       shell_ctx: ShellContext,
  |       config: Config,
  |       backend_fn: BackendFn,
  |       on_step: Callable[[int, int, str, str], None] | None = None,
  |   ) -> PipelineResult
  |     Translate each step and compose the final command.
  |     on_step callback receives (step_index, total, command, description)
  |     for progress reporting.
  |
  |-- @dataclass PipelineResult:
  |       command: str
  |       description: str
  |       steps: list[StepResult]
  |       is_pipeline: bool
  |
  |-- @dataclass StepResult:
  |       input_text: str
  |       command: str
  |       description: str
```

### Integration with cli.py

The `translate_cmd` function is updated to call `split_request` first:

```python
steps = split_request(user_prompt)
if len(steps) == 1:
    # Existing single-command path -- no behavior change.
    ...
else:
    # Pipeline path.
    result = translate_pipeline(steps, user_prompt, shell_ctx, config, backend_fn, ...)
    command = result.command
    description = result.description
```

Single-step requests follow the existing code path exactly. No new latency,
no new LLM calls, no UX change. This satisfies US-4.

### Integration with llm.py

A new function `build_pipeline_step_prompt` is added to `llm.py` to generate
the per-step system prompt. A `build_compose_prompt` function generates the
final composition prompt. Both return strings that are passed to the existing
`BackendFn` callable. No changes to the backend implementations.

### Integration with sanitize.py

No changes. Both per-step responses and the compose response follow the
existing two-line contract.

### Integration with init.py / shell integration

No changes. The shell integration scripts call `at-cmd translate` with the
full user input. Pipeline detection happens inside the translate path. Inline
mode receives the final composed command as a single string, which is all it
needs.

---

## Edge Cases

### Steps That Do Not Compose

Some steps produce no output that a subsequent step can consume. Example:
`@ create a directory called backup then list its contents`. The compose call
handles this by choosing `&&` as the connector (`mkdir backup && ls backup`).
If the LLM returns something nonsensical, the `&&` fallback in the assembler
ensures the result is at least syntactically valid.

### Ambiguous "then"

The word "then" can appear inside a step rather than as a separator. Example:
`@ if the file exists then delete it`. This is a conditional, not a pipeline.
The splitting regex uses word boundaries and requires whitespace around
connectives, but this case is genuinely ambiguous. Mitigation:

- If splitting produces a step that looks like a sentence fragment with no
  verb (e.g., "delete it" is fine, but "exists" alone is not a coherent
  request), the parser should merge it back with the previous step.
- A post-split validation pass checks that each step contains at least one
  verb-like word. Steps that fail this check are merged leftward.

### Single-Step Requests

When `split_request` returns exactly one step, the pipeline path is skipped
entirely. The existing translate flow runs unchanged. No extra LLM calls, no
extra latency.

### Too Many Steps

If the user provides more steps than `max_pipeline_steps` (default: 5),
return an error:

```
Error: pipeline has 8 steps (max 5). Simplify your request or adjust
max_pipeline_steps in config.
```

### Empty Steps After Splitting

If a connective at the beginning or end of the request produces an empty
step (e.g., `then find files`), the empty step is silently dropped.

### LLM Failure on One Step

If a single step fails (BackendError or SanitizeError), the entire pipeline
fails. The error message identifies which step failed:

```
Error: step 2/3 ("compress them") failed: Empty response from LLM
```

The user can retry the entire request or simplify it.

### Connector Ambiguity in Compose

If the LLM compose call returns a command that does not include all steps,
or reorders them, the user sees the composed result in the editable prompt
and can fix it. The per-step preview (in submit mode) gives the user enough
context to judge whether the composition is correct.

---

## Configuration

New config fields added to the `Config` dataclass:

| Field                | Type  | Default | Env Var                    | Description                          |
|----------------------|-------|---------|----------------------------|--------------------------------------|
| `pipeline_enabled`   | bool  | true    | `AT_CMD_PIPELINE_ENABLED`  | Enable/disable pipeline detection.   |
| `max_pipeline_steps` | int   | 5       | `AT_CMD_MAX_PIPELINE_STEPS`| Maximum number of steps allowed.     |
| `pipeline_preview`   | bool  | true    | `AT_CMD_PIPELINE_PREVIEW`  | Show per-step preview in submit mode.|

When `pipeline_enabled` is false, `split_request` always returns the full
input as a single step, disabling the feature entirely.

TOML example:

```toml
pipeline_enabled = true
max_pipeline_steps = 5
pipeline_preview = true
```

---

## Testing Strategy

Tests live in `tests/test_pipeline.py`.

### Unit Tests for `split_request`

| Test                         | Input                                            | Expected Steps                                        |
|------------------------------|--------------------------------------------------|-------------------------------------------------------|
| Basic "then"                 | `find files then compress them`                  | `["find files", "compress them"]`                     |
| "and then"                   | `list files and then sort by size`               | `["list files", "sort by size"]`                      |
| "after that"                 | `download it after that extract`                 | `["download it", "extract"]`                          |
| "pipe to"                    | `list files pipe to grep python`                 | `["list files", "grep python"]`                       |
| No connective                | `find large jpg files`                           | `["find large jpg files"]`                            |
| Three steps                  | `find them then zip then move`                   | `["find them", "zip", "move"]`                        |
| "and" with verb              | `create dir and move files into it`              | `["create dir", "move files into it"]`                |
| "and" without verb           | `find and replace in all files`                  | `["find and replace in all files"]`                   |
| "then" inside conditional    | `if file exists then delete it`                  | `["if file exists then delete it"]` (merged back)     |
| Leading connective           | `then find files`                                | `["find files"]`                                      |
| Trailing connective          | `find files then`                                | `["find files"]`                                      |
| Too many steps               | (6-step input with max=5)                        | Raises error                                          |
| Case insensitivity           | `find files THEN compress`                       | `["find files", "compress"]`                          |
| "then" inside a word         | `authenticate with the server`                   | `["authenticate with the server"]` (no split)         |

### Unit Tests for `translate_pipeline`

- Mock the backend function to return canned two-line responses.
- Verify that the on_step callback is invoked for each step.
- Verify that the compose call receives all per-step commands.
- Verify fallback to `&&` joining when the compose call fails.

### Integration Tests

- End-to-end test with a mock backend: full request in, PipelineResult out.
- Verify JSON output structure with `--json` flag and a multi-step request.

### Edge Case Tests

- Single-step request returns `is_pipeline = False` and has no `steps`.
- Request exceeding `max_pipeline_steps` produces a clear error.
- Backend failure on step 2 of 3 produces an error identifying step 2.
- `pipeline_enabled = False` skips splitting entirely.

---

## Out of Scope

The following are explicitly not part of this feature and may be addressed
separately:

- **Parallel step execution.** All steps are composed into a single command.
  The user decides whether to run it. There is no orchestration of parallel
  sub-processes.
- **Conditional branching.** "if X then Y else Z" is not supported as a
  pipeline. The entire phrase is sent as a single request.
- **Interactive step editing.** The user cannot edit individual steps before
  composition. They edit the final composed command. Per-step editing could
  be a future enhancement.
- **Step caching.** Repeated identical steps are not cached across
  invocations. This could be added as part of the broader caching feature.
- **Streaming per-step output.** Steps are not streamed as they translate.
  This depends on the streaming ghost-text feature.
- **Loop constructs.** "for each file do X" is treated as a single step,
  not as a loop-aware pipeline.
- **Cross-command variable passing.** The pipeline builder does not introduce
  shell variables or temporary files to pass data between steps. It relies on
  the LLM to compose commands using native shell mechanisms (pipes, xargs,
  -exec, etc.).
