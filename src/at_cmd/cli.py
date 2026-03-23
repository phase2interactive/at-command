"""CLI entry point for at-cmd."""

import json
import readline
import sys

import click

from at_cmd.config import load_config
from at_cmd.detect import detect_context
from at_cmd.llm import BackendError, build_system_prompt, get_backend
from at_cmd.sanitize import SanitizeError, sanitize_response


class _DefaultToTranslate(click.Group):
    """Click group that falls through to translate for unknown subcommands."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
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
@click.argument("request", nargs=-1, required=True)
@click.option("--json-output", "--json", "json_mode", is_flag=True, help="Output JSON.")
@click.option("--shell", "shell_name", default=None, help="Override shell detection.")
@click.option("--backend", default=None, help="LLM backend.")
@click.option("--model", default=None, help="Model identifier.")
def translate_cmd(
    request: tuple[str, ...],
    json_mode: bool,
    shell_name: str | None,
    backend: str | None,
    model: str | None,
) -> None:
    """Translate natural language into a shell command."""
    user_prompt = " ".join(request)

    shell_ctx = detect_context(shell_override=shell_name)
    config = load_config(backend_override=backend, model_override=model)

    try:
        backend_fn = get_backend(config)
    except BackendError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    from at_cmd.spinner import Spinner

    try:
        with Spinner("translating"):
            system_prompt = build_system_prompt(shell_ctx)
            raw = backend_fn(system_prompt, user_prompt)
            command, description = sanitize_response(raw)
    except (BackendError, SanitizeError) as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

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


# ── init ──────────────────────────────────────────────────────────


@main.command("init")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish", "powershell"]))
def init_cmd(shell: str) -> None:
    """Print shell init script to stdout.

    \b
    Setup:
      bash/zsh:    eval "$(at-cmd init bash)"
      fish:        at-cmd init fish | source
      powershell:  Invoke-Expression (at-cmd init powershell)
    """
    from at_cmd.init import generate

    click.echo(generate(shell))


# ── config ────────────────────────────────────────────────────────


@main.command("config")
def config_cmd() -> None:
    """Open the interactive configuration TUI."""
    from at_cmd.tui import run_tui

    run_tui()
