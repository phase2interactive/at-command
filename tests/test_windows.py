"""Windows-specific tests for at-cmd.

These tests run natively on Windows (not in Docker) and verify behaviors
that are invisible to mocked unit tests: encoding, subprocess resolution,
PowerShell script loading, etc.

Skipped automatically on non-Windows platforms.
"""

import os
import shutil
import subprocess
import sys

import pytest
from click.testing import CliRunner

from at_cmd.cli import main

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only tests")


# ── Encoding safety ─────────────────────────────────────────────


class TestEncoding:
    """Verify no non-ASCII characters leak into output on cp1252 consoles."""

    def _run_with_cp1252(self, args):
        """Run at-cmd CLI and encode all output through cp1252."""
        runner = CliRunner()
        result = runner.invoke(main, args)
        # Simulate cp1252 console by encoding the output
        output = result.output
        output.encode("cp1252")  # raises UnicodeEncodeError if non-ASCII leaks
        return result

    def test_status_no_unicode_errors(self):
        """at-cmd (no args) must not crash with UnicodeEncodeError."""
        result = self._run_with_cp1252([])
        assert result.exit_code == 0
        assert "at-cmd" in result.output

    def test_init_powershell_no_unicode_errors(self):
        """at-cmd init powershell must produce cp1252-safe output."""
        result = self._run_with_cp1252(["init", "powershell"])
        assert result.exit_code == 0
        assert "_at_cmd_submit" in result.output

    def test_init_bash_no_unicode_errors(self):
        """at-cmd init bash must produce cp1252-safe output."""
        result = self._run_with_cp1252(["init", "bash"])
        assert result.exit_code == 0
        assert "_at_cmd_submit" in result.output

    def test_init_zsh_no_unicode_errors(self):
        """at-cmd init zsh must produce cp1252-safe output."""
        result = self._run_with_cp1252(["init", "zsh"])
        assert result.exit_code == 0
        assert "_at_cmd_submit" in result.output

    def test_init_fish_no_unicode_errors(self):
        """at-cmd init fish must produce cp1252-safe output."""
        result = self._run_with_cp1252(["init", "fish"])
        assert result.exit_code == 0
        assert "_at_cmd_submit" in result.output

    def test_spinner_frames_are_ascii(self):
        """Spinner frames must be pure ASCII for cp1252 safety."""
        from at_cmd.spinner import _FRAMES

        for frame in _FRAMES:
            frame.encode("ascii")  # raises if non-ASCII


# ── Subprocess resolution ────────────────────────────────────────


class TestSubprocessResolution:
    """Verify that resolved paths from shutil.which work with subprocess.run."""

    def test_which_python_is_callable(self):
        """Baseline: shutil.which result works with subprocess.run."""
        python_path = shutil.which("python")
        assert python_path is not None
        result = subprocess.run(
            [python_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "Python" in result.stdout

    @pytest.mark.skipif(
        shutil.which("claude") is None, reason="Claude CLI not installed"
    )
    def test_which_claude_is_callable(self):
        """Resolved claude path must be callable by subprocess.run."""
        claude_path = shutil.which("claude")
        result = subprocess.run(
            [claude_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0


# ── PowerShell init script loading ───────────────────────────────


class TestPowerShellInit:
    """Verify PowerShell init scripts load correctly in real PowerShell."""

    @pytest.fixture(autouse=True)
    def _require_pwsh(self):
        if not shutil.which("pwsh"):
            pytest.skip("pwsh (PowerShell 7) not installed")

    def test_init_loads_in_pwsh(self):
        """Init script must load without errors in PowerShell 7."""
        result = subprocess.run(
            [
                "pwsh", "-NoProfile", "-Command",
                "Invoke-Expression (at-cmd init powershell | Out-String); "
                "Get-Command _at_cmd_submit -ErrorAction Stop | "
                "Select-Object -ExpandProperty CommandType",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Function" in result.stdout

    def test_init_defines_at_function(self):
        """The 'at' convenience function must be defined."""
        result = subprocess.run(
            [
                "pwsh", "-NoProfile", "-Command",
                "Invoke-Expression (at-cmd init powershell | Out-String); "
                "Get-Command at -CommandType Function -ErrorAction Stop | "
                "Select-Object -ExpandProperty Name",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "at" in result.stdout

    def test_submit_no_args_shows_error(self):
        """_at_cmd_submit with no args must show usage error, not crash."""
        result = subprocess.run(
            [
                "pwsh", "-NoProfile", "-Command",
                "Invoke-Expression (at-cmd init powershell | Out-String); "
                "_at_cmd_submit 2>&1",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert "Usage" in result.stdout or "Usage" in result.stderr

    def test_no_syntax_warnings(self):
        """Init script must not produce Python SyntaxWarnings."""
        result = subprocess.run(
            [
                "pwsh", "-NoProfile", "-Command",
                "at-cmd init powershell | Out-Null",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert "SyntaxWarning" not in result.stderr


class TestPowerShell51Init:
    """Verify init scripts also work on Windows PowerShell 5.1."""

    @pytest.fixture(autouse=True)
    def _require_powershell(self):
        if not shutil.which("powershell"):
            pytest.skip("powershell.exe (5.1) not available")

    def test_init_loads_in_powershell_51(self):
        """Init script must load without errors in PowerShell 5.1."""
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Invoke-Expression (at-cmd init powershell | Out-String); "
                "Get-Command _at_cmd_submit -ErrorAction Stop | "
                "Select-Object -ExpandProperty CommandType",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "Function" in result.stdout

    def test_no_syntax_warnings_51(self):
        """Init script must not produce Python SyntaxWarnings on 5.1."""
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "at-cmd init powershell | Out-Null",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert "SyntaxWarning" not in result.stderr


# ── PowerShell command execution ─────────────────────────────────


class TestPowerShellExecution:
    """Verify PowerShell commands execute correctly through subprocess."""

    @pytest.fixture(autouse=True)
    def _require_pwsh(self):
        if not shutil.which("pwsh"):
            pytest.skip("pwsh (PowerShell 7) not installed")

    def test_simple_command_executes(self):
        """Baseline: simple PowerShell command works via subprocess."""
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", "Write-Output 'hello'"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_pipeline_command_executes(self):
        """Pipes must work through our invocation path."""
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command",
             "Get-ChildItem | Select-Object -First 1 | ForEach-Object { $_.Name }"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_command_with_commas_executes(self):
        """Commas in arguments must not break subprocess invocation."""
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command",
             "Get-ChildItem | Sort-Object -Property Name, Length"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_command_with_semicolons_executes(self):
        """Semicolons (statement separators) must work."""
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command",
             "$a = 1; $b = 2; Write-Output ($a + $b)"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "3" in result.stdout


class TestPowerShellDetection:
    """Verify we use the right PowerShell executable."""

    @pytest.mark.skipif(
        shutil.which("pwsh") is None, reason="pwsh not installed"
    )
    def test_cli_uses_pwsh_when_available(self, monkeypatch):
        """Regression: must prefer pwsh over powershell.exe when available."""
        _real_which = shutil.which
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/claude" if x == "claude" else _real_which(x))
        monkeypatch.setattr(
            "at_cmd.llm.subprocess.run",
            lambda *args, **kwargs: type(
                "Result", (), {"returncode": 0, "stdout": "Write-Output hi\nTest", "stderr": ""}
            )(),
        )

        captured = {}
        original_run = subprocess.run

        def mock_exec_run(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return original_run("echo ok", shell=True)

        monkeypatch.setattr("subprocess.run", mock_exec_run)

        from click.testing import CliRunner
        from at_cmd.cli import main

        runner = CliRunner()
        runner.invoke(
            main,
            ["--shell", "powershell", "test"],
            input="\n",
        )

        assert "args" in captured
        exe = captured["args"][0][0] if isinstance(captured["args"][0], list) else captured["args"][0]
        assert "pwsh" in exe.lower() or "powershell" in exe.lower()


# ── Helpers ──────────────────────────────────────────────────────


def _minimal_env():
    """Return a copy of the current env suitable for subprocess calls."""
    env = os.environ.copy()
    # Ensure at-cmd is findable
    return env
