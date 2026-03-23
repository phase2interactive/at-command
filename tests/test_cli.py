"""Tests for at_cmd.cli."""

import json

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
