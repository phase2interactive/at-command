"""CLI entry point for at-cmd."""

import json
import os
import readline
import shutil
import subprocess
import sys
from pathlib import Path

import click

from at_cmd.config import load_config
from at_cmd.detect import detect_context
from at_cmd.llm import BackendError, build_system_prompt, get_backend
from at_cmd.sanitize import SanitizeError, parse_response


def _shell_integration_installed() -> bool:
    """Check if the shell integration function exists in the current shell.

    Returns:
        bool: True if the _at_cmd_submit function is defined in the shell.
    """
    shell_env = detect_context().shell

    if shell_env == "fish":
        cmd = ["fish", "-c", "functions -q _at_cmd_submit"]
    elif shell_env == "zsh":
        cmd = ["zsh", "-ic", "whence -w _at_cmd_submit"]
    elif shell_env == "bash":
        cmd = ["bash", "-ic", "type _at_cmd_submit"]
    else:
        return False

    shell_bin = cmd[0]
    if not shutil.which(shell_bin):
        return False

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=5)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _show_status() -> None:
    """Show at-cmd status and setup guidance."""
    ctx = detect_context()
    installed = _shell_integration_installed()

    click.echo("at-cmd — natural language to shell commands\n")

    if installed:
        click.echo("  ✓ Shell integration is active.\n")
        click.echo("  Usage:")
        click.echo("    @ find large jpg files      translate and edit")
        click.echo("    @ list running docker containers")
        click.echo(f"\n  Shell: {ctx.shell}  |  OS: {ctx.os_name}")
    else:
        click.echo("  ✗ Shell integration is not installed.\n")
        click.echo("  Run the following to set it up:\n")
        click.echo("    at-cmd setup")

    click.echo()


class _DefaultToTranslate(click.Group):
    """Click group that falls through to translate for unknown subcommands."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        # No arguments at all — show status instead of help.
        if not args:
            _show_status()
            ctx.exit(0)

        # Find the first non-flag argument to decide routing.
        first_word = next((a for a in args if not a.startswith("-")), None)
        if first_word and first_word not in self.commands:
            args = ["translate"] + args
        elif not first_word and args:
            # All flags, no subcommand — assume translate (e.g. --json)
            args = ["translate"] + args
        return super().parse_args(ctx, args)


@click.group(cls=_DefaultToTranslate)
def main() -> None:
    """at-cmd: translate natural language into shell commands."""


# ── translate (default) ───────────────────────────────────────────


@main.command("translate", hidden=True)
@click.argument("request", nargs=-1, required=False)
@click.option("--json-output", "--json", "json_mode", is_flag=True, help="Output JSON.")
@click.option("--shell", "shell_name", default=None, help="Override shell detection.")
@click.option("--backend", default=None, help="LLM backend.")
@click.option("--model", default=None, help="Model identifier.")
@click.option("--no-session", is_flag=True, help="Run stateless, no session context.")
@click.option("--new-session", "new_session_flag", is_flag=True, help="Start a fresh session.")
@click.option("--clear-session", is_flag=True, help="Clear session for current directory.")
@click.option("--session-info", is_flag=True, help="Show current session info.")
def translate_cmd(
    request: tuple[str, ...] | None,
    json_mode: bool,
    shell_name: str | None,
    backend: str | None,
    model: str | None,
    no_session: bool,
    new_session_flag: bool,
    clear_session: bool,
    session_info: bool,
) -> None:
    """Translate natural language into a shell command."""
    from at_cmd.session import (
        clear_session as do_clear_session,
        get_or_create_session,
        increment_interactions,
        is_new_session,
        new_session as do_new_session,
        session_info as get_session_info,
    )

    cwd = os.getcwd()

    # Session management flags — early return, no translation needed
    if clear_session:
        do_clear_session(cwd)
        click.echo("Session cleared.", err=True)
        return

    if session_info:
        info = get_session_info(cwd)
        click.echo(info or "No active session.", err=True)
        return

    if not request:
        click.echo("Error: Missing request text.", err=True)
        sys.exit(1)

    user_prompt = " ".join(request)

    shell_ctx = detect_context(shell_override=shell_name)
    config = load_config(backend_override=backend, model_override=model)

    # Resolve session ID
    session_id: str | None = None
    if not no_session and config.resume_session:
        if new_session_flag:
            session_id = do_new_session(cwd)
        else:
            session_id = get_or_create_session(cwd)

    if session_id and config.backend != "claude":
        click.echo(
            "Warning: Session context requires the claude backend. Running stateless.",
            err=True,
        )
        session_id = None

    # Determine if session is brand-new (needs --session-id instead of --resume)
    session_is_new = bool(session_id) and is_new_session(cwd)

    try:
        backend_fn = get_backend(config, session_id=session_id, is_new=session_is_new)
    except BackendError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    from at_cmd.spinner import Spinner

    try:
        with Spinner("translating"):
            system_prompt = build_system_prompt(shell_ctx)
            raw = backend_fn(system_prompt, user_prompt)
            response = parse_response(raw)
    except (BackendError, SanitizeError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    if session_id:
        increment_interactions(cwd)

    command, description = response.command, response.description

    if json_mode:
        click.echo(json.dumps({"command": command, "description": description}))
        return

    if description:
        click.echo(f"  \033[2m# {description}\033[0m", err=True)

    try:
        readline.set_startup_hook(lambda: readline.insert_text(command))
        try:
            final_cmd = input("\033[32m\u276f \033[0m")
        finally:
            readline.set_startup_hook()
    except (KeyboardInterrupt, EOFError):
        click.echo("", err=True)
        sys.exit(130)

    if final_cmd.strip():
        import subprocess

        subprocess.run(final_cmd, shell=True)


# ── setup / init ──────────────────────────────────────────────────


_SUPPORTED_SHELLS = ("bash", "zsh", "fish", "powershell")

_INIT_MARKER = "# at-cmd shell integration"

_RC_FILES: dict[str, str] = {
    "bash": "~/.bashrc",
    "zsh": "~/.zshrc",
    "fish": "~/.config/fish/config.fish",
    "powershell": "",  # resolved at runtime via $PROFILE
}

_EVAL_LINES: dict[str, str] = {
    "bash": 'eval "$(at-cmd init bash)"',
    "zsh": 'eval "$(at-cmd init zsh)"',
    "fish": "at-cmd init fish | source",
    "powershell": "Invoke-Expression (at-cmd init powershell)",
}


def _get_rc_path(shell: str) -> Path:
    """Resolve the RC file path for a shell.

    Args:
        shell: Shell name.

    Returns:
        Path: Absolute path to the shell config file.
    """
    if shell == "powershell":
        ps_profile = os.environ.get("PROFILE", "")
        if ps_profile:
            return Path(ps_profile).expanduser()
        # Reason: common default location when $PROFILE is unset
        return Path("~/.config/powershell/Microsoft.PowerShell_profile.ps1").expanduser()
    return Path(_RC_FILES[shell]).expanduser()


def _rc_has_integration(rc_path: Path) -> bool:
    """Check if the RC file already contains the at-cmd integration line.

    Args:
        rc_path: Path to the shell config file.

    Returns:
        bool: True if the marker is already present.
    """
    if not rc_path.exists():
        return False
    return _INIT_MARKER in rc_path.read_text()


@main.command("setup")
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt.")
def setup_cmd(yes: bool) -> None:
    """Set up shell integration.

    Detects your shell and adds the at-cmd integration to your shell config.
    """
    detected = detect_context().shell
    if detected not in _SUPPORTED_SHELLS:
        click.echo(
            f"Error: could not detect a supported shell (got '{detected}').\n"
            f"Supported: {', '.join(_SUPPORTED_SHELLS)}",
            err=True,
        )
        sys.exit(1)

    rc_path = _get_rc_path(detected)
    eval_line = _EVAL_LINES[detected]

    click.echo(f"  Detected shell: {detected}")
    click.echo(f"  Config file:    {rc_path}")

    if _rc_has_integration(rc_path):
        click.echo(f"\n  Shell integration is already installed.")
        click.echo(f"  To reinstall, remove the '{_INIT_MARKER}' line from {rc_path} and run again.")
        return

    click.echo(f"\n  This will add the following line to {rc_path}:\n")
    click.echo(f"    {eval_line}")

    if not yes and not click.confirm(f"\n  Proceed?"):
        sys.exit(0)

    # Ensure parent directories exist (e.g. ~/.config/fish/).
    rc_path.parent.mkdir(parents=True, exist_ok=True)

    # Append the eval line with the marker.
    with open(rc_path, "a") as f:
        f.write(f"\n{_INIT_MARKER}\n{eval_line}\n")

    click.echo(f"\n  Done! Restart your shell or run:\n")
    if detected == "fish":
        click.echo(f"    source {rc_path}")
    elif detected == "powershell":
        click.echo(f"    . $PROFILE")
    else:
        click.echo(f"    source {rc_path}")


@main.command("init", hidden=True)
@click.argument("shell")
def init_cmd(shell: str) -> None:
    """Print raw shell init script to stdout (used by eval line)."""
    from at_cmd.init import generate

    if shell not in _SUPPORTED_SHELLS:
        click.echo(
            f"Error: invalid shell '{shell}'. Choose from: {', '.join(_SUPPORTED_SHELLS)}",
            err=True,
        )
        sys.exit(1)
    click.echo(generate(shell))


# ── config ────────────────────────────────────────────────────────


@main.command("config")
def config_cmd() -> None:
    """Open the interactive configuration TUI."""
    from at_cmd.tui import run_tui

    run_tui()
