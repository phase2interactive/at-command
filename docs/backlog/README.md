# Feature Backlog

Ideas and designs for future at-cmd features, organized by maturity.

## Tactical

Practical gaps and day-to-day friction reducers.

| Feature | Description | Details |
|---------|-------------|---------|
| Refine / Edit Previous Request | Double-Escape restores original `@ <request>` for editing (à la Claude Code); blind retry dropped | [tactical-regenerate.md](tactical-regenerate.md) |
| Custom User Prompt | User-defined text appended to the system prompt via config | [tactical-custom-prompt.md](tactical-custom-prompt.md) |
| JSON Response Format | Migrate LLM response contract from 2-line text to structured JSON | [tactical-json-response-format.md](tactical-json-response-format.md) |
| Danger Warnings | LLM-based danger classification in the JSON response (depends on JSON Response Format) | [tactical-danger-warnings.md](tactical-danger-warnings.md) |
| Ambiguity Handling | Surface clarifying questions instead of guessing | [tactical-ambiguity-handling.md](tactical-ambiguity-handling.md) |
| Inline Explanation Mode | `--explain` flag or keypress for plain-English command breakdown | [tactical-explain-mode.md](tactical-explain-mode.md) |
| Multi-Candidate Picker | Present 2-3 alternative commands via numbered list or fzf | [tactical-multi-candidate.md](tactical-multi-candidate.md) |
| `at-cmd doctor` | Pre-flight health check: backend reachable, credentials valid, model exists | [tactical-doctor.md](tactical-doctor.md) |
| Inline Description (Bash/Zsh) | Show description in inline mode for bash and zsh (Fish already works) | [tactical-inline-description-bash-zsh.md](tactical-inline-description-bash-zsh.md) |
| Description Sanitization | Strip leading `#` from LLM description to prevent `# #` double-prefix | [tactical-description-sanitization.md](tactical-description-sanitization.md) |
| History Compliance (NF3) | Reconcile spec NF3 with current behavior of adding confirmed commands to history | [tactical-history-compliance.md](tactical-history-compliance.md) |
| Available Tools Context | Include installed CLI tools in system prompt for better suggestions | [tactical-available-tools-context.md](tactical-available-tools-context.md) |

## Exploratory

Ambitious ideas that push the boundaries of what a natural-language CLI tool could become.

| Feature | Description | Details |
|---------|-------------|---------|
| Session Context (--resume) | Reuse Claude CLI sessions across invocations for conversational context | [exploratory-shell-history-context.md](exploratory-shell-history-context.md) |
| Streaming Ghost Text | Stream the translated command character-by-character as dim text | [exploratory-streaming-ghost-text.md](exploratory-streaming-ghost-text.md) |
| Teachable Vocabulary | Learn from user edits; store `(request, corrected_command)` pairs locally | [exploratory-teachable-vocabulary.md](exploratory-teachable-vocabulary.md) |
| Self-Improving Calibration | Track edit distance over time and auto-propose prompt amendments | [exploratory-self-improving.md](exploratory-self-improving.md) |
