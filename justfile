set shell := ["bash", "-uc"]
set dotenv-load := true

default:
    @just --list

# Install dependencies
install:
    uv sync

# Install as a uv tool (available globally)
tool:
    uv tool install . --force --reinstall

# Install in editable mode (for development)
dev:
    uv pip install -e .

# Run all tests
test *ARGS:
    uv run pytest {{ARGS}}

# Run tests with verbose output
testv *ARGS:
    uv run pytest -v {{ARGS}}

# Run integration tests (requires Claude CLI)
test-integration *ARGS:
    uv run pytest -m integration -v {{ARGS}}

# Run tests with coverage report
coverage *ARGS:
    uv run pytest --cov=src/at_cmd --cov-report=term-missing {{ARGS}}

# Lint with ruff
lint:
    uv run ruff check src/ tests/

# Format with ruff
format:
    uv run ruff format src/ tests/

# Lint and format
check: lint format

# Open the config TUI
config:
    uv run at-cmd config

# Generate shell init script
init SHELL:
    uv run at-cmd init {{SHELL}}

# Run e2e tests (requires at-cmd installed + LLM backend)
test-e2e *ARGS:
    uv run pytest -m e2e -v {{ARGS}}

# Record an ad-hoc terminal session with asciinema
record SESSION_NAME="adhoc":
    @mkdir -p recordings
    asciinema rec --overwrite --cols 120 --rows 30 "recordings/{{SESSION_NAME}}.cast"

# Replay a recorded session
replay SESSION_NAME="adhoc":
    asciinema play "recordings/{{SESSION_NAME}}.cast"

# Run shell integration tests in Docker (bash, zsh, fish)
test-shells *ARGS:
    docker compose -f tests/shells/docker-compose.yml run --rm --build {{ARGS}} all

# Run a single shell's integration tests in Docker (e.g. just test-shell bash)
test-shell SHELL:
    docker compose -f tests/shells/docker-compose.yml run --rm --build {{SHELL}}

# Translate a natural language request (for quick testing)
translate +REQUEST:
    uv run at-cmd {{REQUEST}}
