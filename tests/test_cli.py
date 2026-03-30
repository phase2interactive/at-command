"""Tests for at_cmd.cli."""

import json
import subprocess
import sys

import pytest
from click.testing import CliRunner

from at_cmd.cli import main


class TestCli:
    """Tests for the CLI entry point."""

    def test_json_mode_output(self, monkeypatch):
        """Expected use: --json flag produces valid JSON on stdout."""
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/claude")
        monkeypatch.setattr(
            "at_cmd.llm.subprocess.run",
            lambda *args, **kwargs: type(
                "Result", (), {"returncode": 0, "stdout": "ls -la\nList all files", "stderr": ""}
            )(),
        )

        runner = CliRunner()
        result = runner.invoke(main, ["--json", "--shell", "fish", "list", "files"])
        assert result.exit_code == 0
        # stdout contains JSON; stderr has spinner (captured together in click 8.x)
        # Find the JSON line in output
        # CliRunner mixes stdout/stderr; extract the JSON object
        import re

        clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", result.output)
        for line in clean.splitlines():
            line = line.strip()
            if line.startswith("{"):
                data = json.loads(line)
                assert data["command"] == "ls -la"
                assert data["description"] == "List all files"
                break
        else:
            assert False, f"No JSON found in output: {result.output}"

    def test_bare_invocation_shows_status(self, monkeypatch):
        """Expected use: bare at-cmd shows status with setup guidance."""
        monkeypatch.setattr(
            "at_cmd.cli._shell_integration_installed", lambda: False
        )
        runner = CliRunner()
        result = runner.invoke(main, [])
        assert result.exit_code == 0
        assert "at-cmd" in result.output
        assert "Shell integration is not installed" in result.output

    def test_bare_invocation_shows_active_when_installed(self, monkeypatch):
        """Expected use: bare at-cmd shows active status when integration exists."""
        monkeypatch.setattr(
            "at_cmd.cli._shell_integration_installed", lambda: True
        )
        runner = CliRunner()
        result = runner.invoke(main, [])
        assert result.exit_code == 0
        assert "Shell integration is active" in result.output
        assert "@ find large jpg files" in result.output

    def test_backend_error_shows_message(self, monkeypatch):
        """Failure case: backend not available."""
        monkeypatch.setattr("shutil.which", lambda x: None)

        runner = CliRunner()
        result = runner.invoke(main, ["--json", "list", "files"])
        assert result.exit_code != 0
        assert "Claude CLI not found" in result.output


class TestSessionFlags:
    """Tests for session management CLI flags."""

    def test_session_info_no_session(self, monkeypatch):
        """Expected use: --session-info with no session shows message."""
        monkeypatch.setattr("at_cmd.session._load_sessions", lambda: {})
        runner = CliRunner()
        result = runner.invoke(main, ["--session-info"])
        assert result.exit_code == 0
        assert "No active session" in result.output

    def test_clear_session_flag(self, monkeypatch):
        """Expected use: --clear-session prints confirmation."""
        monkeypatch.setattr("at_cmd.session._load_sessions", lambda: {})
        monkeypatch.setattr("at_cmd.session._save_sessions", lambda d: None)
        runner = CliRunner()
        result = runner.invoke(main, ["--clear-session"])
        assert result.exit_code == 0
        assert "Session cleared" in result.output

    def test_no_session_flag(self, monkeypatch):
        """Expected use: --no-session prevents --resume in subprocess call."""
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/claude")

        captured_args = {}

        def mock_run(*args, **kwargs):
            captured_args["cmd"] = args[0]
            import subprocess

            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ls -la\nList files", stderr=""
            )

        monkeypatch.setattr("at_cmd.llm.subprocess.run", mock_run)

        runner = CliRunner()
        result = runner.invoke(
            main, ["--json", "--no-session", "--shell", "bash", "list", "files"]
        )
        assert result.exit_code == 0
        assert "--resume" not in captured_args.get("cmd", [])

    def test_non_claude_backend_session_warning(self, monkeypatch):
        """Edge case: non-claude backend emits session warning."""
        import httpx

        monkeypatch.setattr("at_cmd.session._storage_path", lambda: __import__("pathlib").Path("/tmp/at-cmd-test-sessions.json"))
        monkeypatch.setattr("at_cmd.session._load_sessions", lambda: {})
        monkeypatch.setattr("at_cmd.session._save_sessions", lambda d: None)
        monkeypatch.setattr(
            "at_cmd.session.get_or_create_session",
            lambda cwd: "at-cmd-test123",
        )

        def mock_post(*args, **kwargs):
            return httpx.Response(
                200,
                json={"response": '{"command": "ls", "description": "list"}'},
            )

        monkeypatch.setattr("httpx.post", mock_post)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--json", "--shell", "bash", "--backend", "ollama", "list", "files"],
        )
        assert "Session context requires the claude backend" in result.output


class TestCommandExecution:
    """Tests for how translated commands are executed."""

    def test_powershell_command_uses_powershell(self, monkeypatch):
        """Regression: PowerShell commands must run via powershell, not cmd.exe.

        When at-cmd detects powershell as the shell and the user accepts a
        command, subprocess.run must invoke it through powershell, not the
        default shell=True (which uses cmd.exe on Windows).
        """
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/claude")
        monkeypatch.setattr(
            "at_cmd.llm.subprocess.run",
            lambda *args, **kwargs: type(
                "Result", (), {"returncode": 0, "stdout": "Get-ChildItem\nList files", "stderr": ""}
            )(),
        )

        captured = {}
        original_run = subprocess.run

        def mock_exec_run(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return original_run("echo ok", shell=True)

        monkeypatch.setattr("subprocess.run", mock_exec_run)

        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--shell", "powershell", "list", "files"],
            input="\n",  # accept the default command
        )

        # Verify the command was routed through powershell, not shell=True with cmd.exe
        assert "args" in captured, f"Command was never executed. Output: {result.output}"
        cmd_args = captured["args"]
        kwargs = captured["kwargs"]

        # Should NOT use shell=True (which invokes cmd.exe on Windows)
        if kwargs.get("shell"):
            # If shell=True is used, cmd must be wrapped: powershell -Command ...
            cmd_str = cmd_args[0] if isinstance(cmd_args[0], str) else " ".join(cmd_args[0])
            assert "powershell" in cmd_str.lower() or "pwsh" in cmd_str.lower(), \
                f"PowerShell command executed via shell=True without powershell wrapper: {cmd_args}"
        else:
            # If shell=False, first arg should be powershell/pwsh
            exe = cmd_args[0][0] if isinstance(cmd_args[0], list) else cmd_args[0]
            assert "powershell" in exe.lower() or "pwsh" in exe.lower(), \
                f"PowerShell command not routed through powershell: {cmd_args}"
