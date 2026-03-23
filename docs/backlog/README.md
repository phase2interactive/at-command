# Feature Backlog

Ideas and designs for future at-cmd features, organized by maturity.

## Tactical

Practical gaps and day-to-day friction reducers.

| Feature | Description | Details |
|---------|-------------|---------|
| Regenerate / Try Again | Single keypress to re-call the LLM with the same request | [tactical-regenerate.md](tactical-regenerate.md) |
| Custom User Prompt | User-defined text appended to the system prompt via config | [tactical-custom-prompt.md](tactical-custom-prompt.md) |
| Danger Warnings | Regex scan for destructive patterns before the editable prompt | [tactical-danger-warnings.md](tactical-danger-warnings.md) |
| Ambiguity Handling | Surface clarifying questions instead of guessing | [tactical-ambiguity-handling.md](tactical-ambiguity-handling.md) |
| Inline Explanation Mode | `--explain` flag or keypress for plain-English command breakdown | [tactical-explain-mode.md](tactical-explain-mode.md) |
| Multi-Candidate Picker | Present 2-3 alternative commands via numbered list or fzf | [tactical-multi-candidate.md](tactical-multi-candidate.md) |
| `at-cmd doctor` | Pre-flight health check: backend reachable, credentials valid, model exists | [tactical-doctor.md](tactical-doctor.md) |

## Exploratory

Ambitious ideas that push the boundaries of what a natural-language CLI tool could become.

| Feature | Description | Details |
|---------|-------------|---------|
| Shell History as Context | Include recent history in the system prompt for context-aware suggestions | [exploratory-shell-history-context.md](exploratory-shell-history-context.md) |
| Streaming Ghost Text | Stream the translated command character-by-character as dim text | [exploratory-streaming-ghost-text.md](exploratory-streaming-ghost-text.md) |
| Teachable Vocabulary | Learn from user edits; store `(request, corrected_command)` pairs locally | [exploratory-teachable-vocabulary.md](exploratory-teachable-vocabulary.md) |
| Pipeline Builder | Chain natural-language steps: `@ find logs then compress then move` | [exploratory-pipeline-builder.md](exploratory-pipeline-builder.md) |
| Self-Improving Calibration | Track edit distance over time and auto-propose prompt amendments | [exploratory-self-improving.md](exploratory-self-improving.md) |
