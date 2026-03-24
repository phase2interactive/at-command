# Task Tracker

## In Progress

## Completed

- [x] Build e2e test harness with pexpect + asciinema (2026-03-24)
  - `tests/e2e/harness.py` — E2ESession (pexpect driver) + CastRecording (asciicast v2 parser)
  - `tests/e2e/test_basic.py` — 6 sample e2e tests (JSON mode, interactive prompt, spinner animation)
  - `.claude/skills/terminal-session.md` — ad-hoc tmux+asciinema skill for Claude
  - Added `pexpect` and `asciinema` to dev deps, `e2e` pytest marker, just recipes

- [x] Implement JSON Response Format Migration (2026-03-23)
  - File: `docs/backlog/tactical-json-response-format.md`
  - Added `LLMResponse` dataclass and `parse_response()` to `sanitize.py` (JSON-first with text fallback)
  - Updated system prompt in `llm.py` to request JSON
  - Updated `cli.py` to use `parse_response` and `LLMResponse`
  - Added 11 new tests (7 JSON, 4 fallback), all existing tests pass

- [x] Write feature spec for Custom User Prompt (2026-03-23)
  - File: `docs/backlog/tactical-custom-prompt.md`
  - Covers config format, system prompt injection, technical design, edge cases, testing strategy
- [x] Write feature spec for Regenerate / Try Again (2026-03-23)
  - File: `docs/backlog/tactical-regenerate.md`
  - Covers submit + inline mode UX, readline completer approach, shell script changes, config, edge cases, testing
- [x] Write feature spec for Danger Warnings (2026-03-23)
  - File: `docs/backlog/tactical-danger-warnings.md`
  - Covers pattern registry, severity levels, UX for submit/inline/JSON modes, config, edge cases, testing strategy
- [x] Write feature spec for Multi-Candidate Picker (2026-03-23)
  - File: `docs/backlog/tactical-multi-candidate.md`
  - Covers --candidates flag, fzf/builtin picker UX, LLM prompt design, multi-response parsing, picker.py module, config, edge cases, testing strategy
- [x] Write feature spec for Ambiguity Handling (2026-03-23)
  - File: `docs/backlog/tactical-ambiguity-handling.md`
  - Covers LLM prompt design, AMBIGUOUS marker protocol, response parsing, clarification UX, inline mode degradation, config, testing
- [x] Write feature spec for Shell History as Living Context (2026-03-23)
  - File: `docs/backlog/exploratory-shell-history-context.md`
  - Covers privacy design (opt-in, deny-lists, argument stripping), history file locations per shell, sanitization pipeline, history.py module, config, edge cases, testing
- [x] Write feature spec for Teachable Personal Vocabulary (2026-03-23)
  - File: `docs/backlog/exploratory-teachable-vocabulary.md`
  - Covers auto correction detection, learn/vocab subcommands, JSONL storage, fuzzy matching algorithm, system prompt injection, vocabulary.py module, config, edge cases, testing
- [x] Write feature spec for Command Pipeline Builder (2026-03-23)
  - File: `docs/backlog/exploratory-pipeline-builder.md`
  - Covers "then" chaining UX, request decomposition regex, per-step LLM calls with compose pass, connector selection, pipeline.py module, config, edge cases, testing
