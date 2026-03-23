# Feature Spec: `at-cmd doctor`

**Version:** 1.0
**Date:** 2026-03-23
**Status:** Draft
**Origin:** Tactical backlog item "at-cmd doctor"

---

## Overview

`at-cmd doctor` is a health-check subcommand that verifies the user's environment is correctly configured before they attempt their first translation. It inspects the active backend, credentials, network connectivity, shell integration, config file integrity, and Python version, then prints a clear pass/warn/fail report with actionable fix suggestions.

### Motivation

Setup failures are the number-one reason users abandon CLI tools. Today, a misconfigured backend surfaces as a cryptic error after a spinner timeout. `doctor` front-loads that diagnosis: one command, a list of green/yellow/red checks, and a concrete "run this to fix it" for every failure. It also serves as a support artifact -- users can paste `at-cmd doctor` output into a bug report.

---

## User Stories

| ID | Story |
|----|-------|
| US-1 | As a new user, I want to run `at-cmd doctor` after install so I can confirm everything works before I try my first translation. |
| US-2 | As a user switching backends, I want `doctor` to tell me exactly what is missing (API key, model name, running server) so I can fix it without guessing. |
| US-3 | As a user filing a bug report, I want to paste `at-cmd doctor --json` output so the maintainer can see my environment at a glance. |
| US-4 | As a user who ran `at-cmd setup` but forgot to reload their shell, I want `doctor` to tell me shell integration is not active yet. |

---

## UX Design

### Invocation

```
at-cmd doctor [--json] [--backend <name>] [--verbose]
```

| Flag | Purpose |
|------|---------|
| `--json` | Output results as a JSON object instead of human-readable text. Useful for bug reports and scripting. |
| `--backend` | Override the configured backend for this check only (same semantics as the translate flag). |
| `--verbose` | Show additional detail for passing checks (e.g., resolved model name, config file path, API URL). |

### Human-Readable Output

```
at-cmd doctor

  General
    [PASS]  Python version ................... 3.12.3
    [PASS]  Config file parseable ............ ~/.config/at-cmd/config.toml
    [PASS]  Shell integration installed ...... zsh

  Backend: ollama
    [PASS]  Server reachable ................. http://localhost:11434
    [PASS]  Model available .................. llama3
    [FAIL]  Test generation .................. Model returned empty response
            -> Try: ollama run llama3 "hello" to verify the model works.

  2 passed, 0 warnings, 1 failed
```

#### Indicators

| Symbol | Meaning | Color (ANSI) |
|--------|---------|--------------|
| `[PASS]` | Check succeeded | Green (`\033[32m`) |
| `[WARN]` | Non-blocking issue; the tool may still work | Yellow (`\033[33m`) |
| `[FAIL]` | Blocking issue; translation will not work | Red (`\033[31m`) |
| `[SKIP]` | Check not applicable to the current backend | Dim (`\033[2m`) |

Each `[WARN]` or `[FAIL]` line is followed by an indented `->` line containing an actionable fix suggestion. Suggestions must be concrete shell commands or URLs, never vague advice.

### JSON Output

When `--json` is passed, output a single JSON object to stdout with no ANSI codes:

```json
{
  "version": "0.1.0",
  "python": "3.12.3",
  "backend": "ollama",
  "model": "llama3",
  "config_path": "~/.config/at-cmd/config.toml",
  "checks": [
    {
      "group": "general",
      "name": "python_version",
      "status": "pass",
      "detail": "3.12.3"
    },
    {
      "group": "backend",
      "name": "test_generation",
      "status": "fail",
      "detail": "Model returned empty response",
      "fix": "Try: ollama run llama3 \"hello\" to verify the model works."
    }
  ],
  "summary": {
    "passed": 2,
    "warnings": 0,
    "failed": 1
  }
}
```

---

## Checks

### General Checks

These run regardless of the selected backend.

| Check | What it verifies | Pass condition | Warn condition | Fail condition | Fix suggestion |
|-------|-----------------|----------------|----------------|----------------|----------------|
| **Python version** | `sys.version_info` | >= 3.12 | 3.10-3.11 (works but unsupported) | < 3.10 | "Upgrade Python to 3.12+: https://python.org/downloads" |
| **Config file parseable** | Load `~/.config/at-cmd/config.toml` via `tomllib` | File parses without error, or file does not exist (defaults are fine) | -- | TOML parse error | "Fix syntax errors in {path}, or delete it to use defaults: rm {path}" |
| **Config values valid** | Backend name is one of `claude`, `ollama`, `openai`; hotkey is in `VALID_KEYBINDINGS` | All values recognized | -- | Unknown backend or invalid keybinding | "Run `at-cmd config` to fix, or edit {path}" |
| **Shell integration installed** | Detect whether `_at_cmd_submit` function exists in the current shell (reuse `_shell_integration_installed()` from cli.py) | Function defined | -- | Not defined | "Run `at-cmd setup` to install shell integration, then restart your shell." |

### Backend: claude

| Check | What it verifies | Pass condition | Fail condition | Fix suggestion |
|-------|-----------------|----------------|----------------|----------------|
| **Binary exists** | `shutil.which("claude")` returns a path | Binary found on PATH | Binary not found | "Install the Claude CLI: https://docs.anthropic.com/claude-code" |
| **Authentication** | Run `claude --version` (or `claude -p --model {model} "say ok"` with a short timeout) to verify the CLI responds without auth errors | Exit code 0, output is non-empty | Non-zero exit or stderr contains "auth" / "login" / "unauthorized" | "Authenticate the Claude CLI: run `claude` and follow the login flow." |
| **Model accessible** | Issue a trivial prompt: `claude -p --model {model} "say ok"` | Returns any non-empty text | Timeout or error | "Check that model '{model}' is valid. Run `claude --help` for available models." |

### Backend: ollama

| Check | What it verifies | Pass condition | Fail condition | Fix suggestion |
|-------|-----------------|----------------|----------------|----------------|
| **Server reachable** | HTTP GET to `{api_url}/` or `{api_url}/api/tags` returns 200 | 200 status | Connection refused, timeout, non-200 | "Start ollama: `ollama serve` (or check that {api_url} is correct)." |
| **Model pulled** | GET `{api_url}/api/tags` and check that the configured model name appears in the `models[].name` list | Model name present | Model name absent | "Pull the model: `ollama pull {model}`" |
| **Test generation** | POST a trivial generate request (`"say ok"`) to `{api_url}/api/generate` | Non-empty `response` field | Empty response or HTTP error | "Try: `ollama run {model} \"hello\"` to verify the model works." |

### Backend: openai

| Check | What it verifies | Pass condition | Fail condition | Fix suggestion |
|-------|-----------------|----------------|----------------|----------------|
| **API key present** | `config.api_key` is non-empty | Key set | Key empty | "Set your API key: `export AT_CMD_API_KEY=sk-...` or add `api_key` to config.toml." |
| **API key valid** | GET `{api_url}/models` with the configured key; expect 200 | 200 status | 401 Unauthorized | "Your API key is invalid. Generate a new one at https://platform.openai.com/api-keys" |
| **Model exists** | Parse the `/models` response and check for the configured model ID | Model ID found in list | Model ID absent | "Model '{model}' not found. Check available models at https://platform.openai.com/docs/models" |
| **Test completion** | POST a minimal chat completion (`"say ok"`, max_tokens=5) | Non-empty response | Error or empty | "The API returned an error. Check your quota at https://platform.openai.com/usage" |

### Check Ordering

Checks within each group run in dependency order. If an earlier check fails critically (e.g., binary not found, server not reachable), later checks in that group are skipped and marked `[SKIP]` with the reason "skipped because {earlier check} failed."

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All checks passed |
| 1 | At least one warning, no failures |
| 2 | At least one failure |

This allows scripts to gate on `at-cmd doctor` in CI or setup workflows:

```bash
at-cmd doctor || echo "at-cmd is not ready"
```

---

## Technical Design

### New Module: `src/at_cmd/doctor.py`

The module defines a small check registry and a runner.

#### Data Structures

```python
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class Status(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class CheckResult:
    """Result of a single health check.

    Attributes:
        group: Logical grouping (general, backend).
        name: Machine-readable check identifier.
        label: Human-readable short label for display.
        status: Outcome of the check.
        detail: Explanation of what was found.
        fix: Actionable suggestion (empty string if status is PASS).
    """
    group: str
    name: str
    label: str
    status: Status
    detail: str
    fix: str = ""
```

#### Check Registry Pattern

Each check is a plain function that accepts a `Config` object (and optionally other resolved context) and returns a `CheckResult`. Checks are registered in ordered lists, not via decorators, to keep the dependency order explicit and testable.

```python
# Type alias for a check function.
CheckFn = Callable[[Config], CheckResult]

# Ordered lists -- later checks may be skipped if earlier ones fail.
GENERAL_CHECKS: list[CheckFn] = [
    check_python_version,
    check_config_parseable,
    check_config_values,
    check_shell_integration,
]

BACKEND_CHECKS: dict[str, list[CheckFn]] = {
    "claude": [check_claude_binary, check_claude_auth, check_claude_model],
    "ollama": [check_ollama_server, check_ollama_model_pulled, check_ollama_generate],
    "openai": [check_openai_key_present, check_openai_key_valid, check_openai_model_exists, check_openai_generate],
}
```

#### Runner

```python
def run_checks(config: Config) -> list[CheckResult]:
    """Execute all applicable checks in order.

    Runs general checks first, then backend-specific checks.
    If a check returns FAIL, subsequent checks in the same group
    are skipped (marked SKIP).

    Args:
        config: Resolved at-cmd configuration.

    Returns:
        list[CheckResult]: Ordered list of results.
    """
```

#### Formatters

Two formatting functions:

- `format_human(results: list[CheckResult], verbose: bool) -> str` -- produces the colorized terminal output shown above.
- `format_json(results: list[CheckResult], config: Config) -> str` -- produces the JSON output shown above.

### CLI Integration: `cli.py`

Add a new Click command to the existing group:

```python
@main.command("doctor")
@click.option("--json-output", "--json", "json_mode", is_flag=True, help="Output JSON.")
@click.option("--backend", default=None, help="Override backend for this check.")
@click.option("--verbose", is_flag=True, help="Show extra detail for passing checks.")
def doctor_cmd(json_mode: bool, backend: str | None, verbose: bool) -> None:
    """Run health checks on your at-cmd setup."""
    from at_cmd.doctor import run_checks, format_human, format_json

    config = load_config(backend_override=backend)
    results = run_checks(config)

    if json_mode:
        click.echo(format_json(results, config))
    else:
        click.echo(format_human(results, verbose))

    # Determine exit code from worst status.
    if any(r.status == Status.FAIL for r in results):
        sys.exit(2)
    elif any(r.status == Status.WARN for r in results):
        sys.exit(1)
    sys.exit(0)
```

### Refactoring

The existing `_shell_integration_installed()` function in `cli.py` should be extracted to a shared location (e.g., `detect.py` or a new `shell.py` utility) so that both `cli.py` and `doctor.py` can use it without circular imports.

### Network Requests

All HTTP checks use `httpx` (already a dependency) with a short timeout (5 seconds) to avoid blocking on unresponsive servers. The timeout is hardcoded for doctor checks and does not use the user's configured `timeout` value, since the user's timeout is tuned for LLM generation latency, not health checks.

---

## Configuration

`doctor` requires no new configuration. It reads the existing `Config` dataclass via `load_config()` and inspects whatever backend, model, API URL, and API key are resolved through the standard layered config.

---

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| **No config file exists** | PASS -- defaults are valid. The check reports "using defaults" in detail. |
| **Config file exists but is empty** | PASS -- `tomllib` parses an empty file successfully. |
| **Config file has unknown keys** | PASS with WARN -- unknown keys are ignored by `load_config`, but doctor notes them so the user knows they have no effect. |
| **Network timeout on backend check** | FAIL with detail "Connection timed out after 5s" and fix suggestion to check the URL / start the server. |
| **Ollama running but model not pulled** | Server check PASSes, model check FAILs with `ollama pull {model}` suggestion. |
| **OpenAI key valid but insufficient quota** | Key-valid check PASSes (200 on `/models`), test-completion FAILs with link to usage dashboard. |
| **Claude CLI installed but not authenticated** | Binary check PASSes, auth check FAILs with login instructions. |
| **Multiple failures across groups** | All groups run to completion (skip logic is per-group only). The summary shows total counts and the exit code reflects the worst status. |
| **`--backend` override points to unconfigured backend** | Checks run against that backend using whatever config values exist (possibly defaults). Missing API keys surface naturally as FAIL. |
| **Non-TTY invocation (piped output)** | ANSI color codes are suppressed when stdout is not a TTY. Click handles this automatically. |
| **Ctrl+C during a network check** | `KeyboardInterrupt` is caught at the runner level. Already-collected results are printed, remaining checks are marked SKIP with detail "interrupted by user". Exit code 2. |

---

## Testing Strategy

Test file: `tests/test_doctor.py`

### Unit Tests (check functions in isolation)

Each check function is a pure-ish function that takes a `Config` and returns a `CheckResult`. Mock external dependencies (subprocess, httpx, shutil.which, sys.version_info) to test all branches.

| Test | What it covers |
|------|---------------|
| `test_python_version_pass` | `sys.version_info >= (3, 12)` returns PASS |
| `test_python_version_warn` | `sys.version_info == (3, 11)` returns WARN |
| `test_python_version_fail` | `sys.version_info == (3, 9)` returns FAIL |
| `test_config_parseable_no_file` | Config path does not exist, returns PASS |
| `test_config_parseable_bad_toml` | Config path contains invalid TOML, returns FAIL |
| `test_config_values_unknown_backend` | Backend set to "gemini", returns FAIL |
| `test_shell_integration_installed` | Mock subprocess to return 0, returns PASS |
| `test_shell_integration_missing` | Mock subprocess to return 1, returns FAIL |
| `test_claude_binary_missing` | `shutil.which` returns None, returns FAIL |
| `test_claude_auth_failure` | subprocess returns stderr with "unauthorized", returns FAIL |
| `test_ollama_server_unreachable` | httpx raises `ConnectError`, returns FAIL |
| `test_ollama_model_not_pulled` | `/api/tags` returns list without configured model, returns FAIL |
| `test_ollama_model_pulled` | `/api/tags` includes model, returns PASS |
| `test_openai_key_missing` | Empty `api_key`, returns FAIL |
| `test_openai_key_invalid` | httpx returns 401, returns FAIL |
| `test_openai_model_not_found` | `/models` response lacks model, returns FAIL |

### Integration Tests (runner + formatter)

| Test | What it covers |
|------|---------------|
| `test_run_checks_skips_after_fail` | First backend check fails, subsequent checks in group are SKIP |
| `test_format_human_colors` | Output contains ANSI codes for PASS/WARN/FAIL |
| `test_format_human_no_colors_non_tty` | When `isatty()` is False, no ANSI codes |
| `test_format_json_schema` | JSON output matches expected keys and structure |

### CLI Tests

| Test | What it covers |
|------|---------------|
| `test_doctor_exit_0_all_pass` | All checks mocked to PASS, exit code 0 |
| `test_doctor_exit_1_warning` | One WARN, exit code 1 |
| `test_doctor_exit_2_failure` | One FAIL, exit code 2 |
| `test_doctor_json_flag` | `--json` produces valid JSON to stdout |
| `test_doctor_backend_override` | `--backend ollama` runs ollama checks even if config says claude |

---

## Out of Scope

The following are explicitly not part of this feature:

- **Auto-fix**: `doctor` diagnoses but does not modify the user's environment (no auto-installing binaries, no writing config files, no starting servers). Fix suggestions are printed for the user to execute manually.
- **Continuous monitoring / watch mode**: `doctor` runs once and exits. No daemon, no polling.
- **Backend-specific version checks**: We do not check whether the ollama server version or Claude CLI version meets a minimum. Version compatibility is the user's responsibility.
- **Proxy / corporate firewall detection**: Network checks report connection failures but do not diagnose proxy misconfiguration.
- **Shell integration correctness**: `doctor` checks whether the integration is installed (function defined) but does not verify that keybindings are active or that the eval line is up to date.
- **Performance benchmarking**: `doctor` does not measure or report LLM response latency beyond pass/fail of a test generation.
