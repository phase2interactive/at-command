"""Detect OS, shell, and working directory context."""

import os
import platform
from dataclasses import dataclass
from pathlib import Path


# Map platform.system() values to human-friendly names
_OS_MAP = {
    "Darwin": "macOS",
    "Linux": "Linux",
    "Windows": "Windows",
}


@dataclass(frozen=True)
class ShellContext:
    """Runtime context for the shell command translator.

    Attributes:
        os_name: Human-friendly OS name (macOS, Linux, Windows).
        shell: Shell name (fish, bash, zsh, powershell, etc.).
        cwd: Current working directory path.
    """

    os_name: str
    shell: str
    cwd: str


def detect_context(shell_override: str | None = None) -> ShellContext:
    """Build a ShellContext from the current environment.

    Args:
        shell_override: Explicit shell name; skips auto-detection if provided.

    Returns:
        ShellContext: Detected runtime context.
    """
    os_name = _OS_MAP.get(platform.system(), platform.system())
    shell = _detect_shell(shell_override)
    cwd = os.getcwd()

    return ShellContext(os_name=os_name, shell=shell, cwd=cwd)


def _detect_shell(override: str | None) -> str:
    """Resolve the current shell name.

    Args:
        override: Explicit shell name from --shell flag.

    Returns:
        str: Shell basename (e.g., "fish", "bash", "zsh").
    """
    if override:
        return override

    # Check AT_CMD_SHELL env var
    env_shell = os.environ.get("AT_CMD_SHELL")
    if env_shell:
        return env_shell

    # Fall back to $SHELL basename
    shell_path = os.environ.get("SHELL", "")
    if shell_path:
        return Path(shell_path).name

    return "bash"  # safe fallback
