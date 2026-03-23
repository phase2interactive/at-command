# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

`at-cmd` is a terminal tool that translates natural language into shell commands using an LLM backend. The user types `@ find large jpg files` and gets back an editable shell command with a brief description. Commands are never auto-executed — the user always reviews first.

Two interaction modes:
- **Submit mode**: `@ <request>` + Enter opens an editable prompt with the translated command
- **Inline mode**: `@ <request>` + hotkey replaces the shell buffer in-place (supports undo)

## Build & Development Commands

```bash
just install        # uv sync — install all dependencies
just dev            # uv pip install -e . — editable install
just test           # uv run pytest
just testv          # uv run pytest -v
just test tests/test_sanitize.py              # run single test file
just test tests/test_sanitize.py::test_name   # run single test
just lint           # uv run ruff check src/ tests/
just format         # uv run ruff format src/ tests/
just check          # lint + format
```

Uses `uv` for Python package management and `just` as the task runner. Python 3.12+.

## Architecture

All source lives in `src/at_cmd/`. The CLI entry point is `at_cmd.cli:main` (registered as `at-cmd` console script).

**Request flow**: `cli.py` → `detect.py` (OS/shell context) → `config.py` (layered config) → `llm.py` (backend call) → `sanitize.py` (parse 2-line response) → editable prompt or JSON output.

Key modules:
- **`cli.py`** — Click group with `_DefaultToTranslate` that routes unknown subcommands to the `translate` command. Subcommands: `translate` (hidden default), `init`, `config`.
- **`llm.py`** — Backend abstraction. Three backends: `claude` (shells out to `claude` CLI), `ollama` (HTTP via httpx), `openai` (HTTP via httpx). Each factory returns a `BackendFn` callable.
- **`config.py`** — Layered config resolution: defaults → `~/.config/at-cmd/config.toml` → `AT_CMD_*` env vars → CLI flags. Uses a plain `@dataclass`, not pydantic.
- **`init.py`** — Generates shell integration scripts for bash/zsh/fish/powershell. Each shell gets submit, inline, and undo functions plus keybindings. Output is meant to be `eval`'d.
- **`keybindings.py`** — Maps logical key names (e.g., `alt+g`) to shell-specific escape sequences.
- **`sanitize.py`** — Strips markdown fences, backticks, and prompt characters from LLM output. Expects exactly 2 lines: command + description.
- **`tui.py`** — Textual-based config editor (`at-cmd config`).
- **`spinner.py`** — Braille-dot animated spinner on stderr during LLM calls.

## LLM Response Contract

The LLM must return exactly two lines:
1. The shell command (no backticks, no markdown, single line)
2. A brief description (10 words or fewer)

`sanitize.py` enforces this by stripping markdown artifacts and raising `SanitizeError` on empty/unparseable output.

## Configuration

Config file: `~/.config/at-cmd/config.toml`
Env var prefix: `AT_CMD_` (e.g., `AT_CMD_BACKEND`, `AT_CMD_MODEL`, `AT_CMD_API_KEY`)

## Testing

Tests are in `tests/` using pytest + pytest-mock. Test files mirror source modules (e.g., `test_sanitize.py`, `test_llm.py`, `test_config.py`). The spec document lives at `docs/at-command-spec.md`.
