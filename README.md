# @ Command

Natural language to shell command translator. Type what you want in plain English, get back an editable shell command.

```
$ @ find all python files modified in the last week
  # Find Python files modified in the last 7 days
❯ find . -name '*.py' -mtime -7
```

The translated command is placed in an editable prompt — you review, edit, or cancel before anything runs.

## Features

- **Two interaction modes**: Submit (editable prompt) and Inline (replaces shell buffer in-place with undo support)
- **Shell-aware**: Detects your shell (bash, zsh, fish, PowerShell) and OS, generates correct syntax
- **Multiple LLM backends**: Claude CLI, Ollama (local), or any OpenAI-compatible API
- **Configurable**: TOML config file, environment variables, CLI flags, or interactive TUI
- **Safe by design**: Commands are never auto-executed

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (package manager)
- [jq](https://jqlang.github.io/jq/) (used by shell integration scripts)
- An LLM backend (see [Backends](#backends))

## Installation

```bash
# Clone and install
git clone https://github.com/jzumwalt/at-command.git
cd at-command
uv sync
uv pip install -e .
```

### Shell Setup

Add one of the following to your shell config:

**Bash** (`~/.bashrc`):
```bash
eval "$(at-cmd init bash)"
```

**Zsh** (`~/.zshrc`):
```bash
eval "$(at-cmd init zsh)"
```

**Fish** (`~/.config/fish/conf.d/at-cmd.fish`):
```fish
at-cmd init fish | source
```

**PowerShell** (`$PROFILE`):
```powershell
Invoke-Expression (at-cmd init powershell)
```

## Usage

### Submit Mode

Type `@ <request>` and press Enter. You get a description and an editable prompt with the translated command:

```
$ @ list docker containers sorted by size
  # List Docker containers sorted by size
❯ docker ps -as --format "table {{.Names}}\t{{.Size}}" | sort -k2 -h
```

- **Enter** — execute the command
- **Edit** — modify before executing
- **Ctrl+C / Escape** — cancel

### Inline Mode

Type `@ <request>` and press the hotkey (default: `Alt+G`). The shell buffer is replaced with the translated command, ready to edit or run:

```
$ @ find large jpg files        ← you type this
  [Alt+G]
$ find . -name '*.jpg' -size +5M   ← buffer replaced, editable
```

- **Enter** — execute
- **Ctrl+Z** — undo back to original `@ <request>` text
- Press the hotkey again to regenerate

### JSON Output

```bash
at-cmd --json "find large files"
# {"command": "find . -size +100M", "description": "Find files larger than 100MB"}
```

### CLI Options

```
at-cmd <request>                    # translate (default)
at-cmd --json <request>             # JSON output
at-cmd --shell bash <request>       # override shell detection
at-cmd --backend ollama <request>   # override backend
at-cmd --model gpt-4o <request>     # override model
at-cmd init <shell>                 # print shell integration script
at-cmd config                       # open interactive config TUI
```

## Backends

| Backend | Default Model | Requires |
|---------|--------------|----------|
| `claude` | `sonnet` | [Claude CLI](https://docs.anthropic.com/claude-code) installed |
| `ollama` | — | Ollama running locally on port 11434 |
| `openai` | — | `AT_CMD_API_KEY` set |

## Configuration

Configuration is resolved in layers (later overrides earlier):

1. **Defaults** — sensible out-of-the-box values
2. **Config file** — `~/.config/at-cmd/config.toml`
3. **Environment variables** — `AT_CMD_*` prefix
4. **CLI flags** — `--backend`, `--model`, `--shell`

### Config File

```toml
backend = "claude"
model = "sonnet"
api_url = ""
api_key = ""
timeout = 10
default_mode = "inline"
hotkey = "alt+g"
undo_key = "ctrl+z"
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `AT_CMD_BACKEND` | LLM backend (`claude`, `ollama`, `openai`) |
| `AT_CMD_MODEL` | Model identifier |
| `AT_CMD_API_URL` | Base URL for HTTP backends |
| `AT_CMD_API_KEY` | API key for authenticated backends |
| `AT_CMD_TIMEOUT` | Request timeout in seconds |
| `AT_CMD_DEFAULT_MODE` | `inline` or `submit` |
| `AT_CMD_HOTKEY` | Keybinding for alternate mode |
| `AT_CMD_UNDO_KEY` | Keybinding for undo |
| `AT_CMD_SHELL` | Override shell detection |

### Interactive TUI

Run `at-cmd config` to open a terminal UI for editing settings:

```bash
at-cmd config
```

## Available Hotkeys

| Key | Shells |
|-----|--------|
| `ctrl+enter` | bash, zsh, fish, PowerShell |
| `ctrl+space` | bash, zsh, fish, PowerShell |
| `ctrl+g` | bash, zsh, fish, PowerShell |
| `ctrl+]` | bash, zsh, fish, PowerShell |
| `ctrl+\` | bash, zsh, fish, PowerShell |
| `alt+enter` | bash, zsh, fish, PowerShell |
| `alt+space` | bash, zsh, fish, PowerShell |
| `alt+g` | bash, zsh, fish, PowerShell |

## Development

```bash
just install    # install dependencies
just dev        # editable install
just test       # run tests
just testv      # run tests (verbose)
just lint       # ruff check
just format     # ruff format
just check      # lint + format
```

## License

MIT
