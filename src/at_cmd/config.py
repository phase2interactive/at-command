"""Configuration loading: defaults -> TOML config file -> env vars."""

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path


CONFIG_PATH = Path.home() / ".config" / "at-cmd" / "config.toml"

# Keybinding names the user can pick from.
VALID_KEYBINDINGS = [
    "ctrl+enter",
    "ctrl+space",
    "ctrl+g",
    "ctrl+]",
    "ctrl+\\",
    "alt+enter",
    "alt+space",
    "alt+g",
]


@dataclass
class Config:
    """at-cmd configuration.

    Attributes:
        backend: LLM backend name (claude, ollama, openai).
        model: Model identifier passed to the backend.
        api_url: Base URL for HTTP-based backends.
        api_key: API key for authenticated backends.
        timeout: Request timeout in seconds.
        default_mode: Default mode when pressing Enter (inline or submit).
        hotkey: Keybinding for the alternate mode.
        undo_key: Keybinding for undo in inline mode.
    """

    backend: str = "claude"
    model: str = "sonnet"
    api_url: str = ""
    api_key: str = ""
    timeout: int = 30
    default_mode: str = "inline"
    hotkey: str = "alt+g"
    undo_key: str = "ctrl+z"
    resume_session: bool = True


def load_config(
    backend_override: str | None = None,
    model_override: str | None = None,
) -> Config:
    """Load configuration with layered resolution.

    Resolution order: defaults -> TOML file -> env vars -> CLI overrides.

    Args:
        backend_override: Explicit backend from CLI flag.
        model_override: Explicit model from CLI flag.

    Returns:
        Config: Resolved configuration.
    """
    cfg = Config()

    # Layer 2: TOML config file
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)
        for f_info in fields(cfg):
            if f_info.name in data:
                setattr(cfg, f_info.name, data[f_info.name])

    # Layer 3: Environment variables
    cfg.backend = os.environ.get("AT_CMD_BACKEND", cfg.backend)
    cfg.model = os.environ.get("AT_CMD_MODEL", cfg.model)
    cfg.api_url = os.environ.get("AT_CMD_API_URL", cfg.api_url)
    cfg.api_key = os.environ.get("AT_CMD_API_KEY", cfg.api_key)
    cfg.default_mode = os.environ.get("AT_CMD_DEFAULT_MODE", cfg.default_mode)
    cfg.hotkey = os.environ.get("AT_CMD_HOTKEY", cfg.hotkey)
    cfg.undo_key = os.environ.get("AT_CMD_UNDO_KEY", cfg.undo_key)
    timeout_env = os.environ.get("AT_CMD_TIMEOUT")
    if timeout_env:
        cfg.timeout = int(timeout_env)
    resume_env = os.environ.get("AT_CMD_RESUME_SESSION")
    if resume_env is not None:
        cfg.resume_session = resume_env.lower() not in ("false", "0", "no")

    # Layer 4: CLI overrides
    if backend_override:
        cfg.backend = backend_override
    if model_override:
        cfg.model = model_override

    return cfg


def save_config(cfg: Config) -> None:
    """Save configuration to the TOML config file.

    Args:
        cfg: Configuration to persist.
    """
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    for f_info in fields(cfg):
        val = getattr(cfg, f_info.name)
        if isinstance(val, bool):
            lines.append(f"{f_info.name} = {str(val).lower()}")
        elif isinstance(val, str):
            lines.append(f'{f_info.name} = "{val}"')
        else:
            lines.append(f"{f_info.name} = {val}")

    CONFIG_PATH.write_text("\n".join(lines) + "\n")
