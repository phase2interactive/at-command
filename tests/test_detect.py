"""Tests for at_cmd.detect."""

import os
import sys

import pytest

from at_cmd.detect import ShellContext, detect_context


class TestDetectContext:
    """Tests for detect_context."""

    def test_explicit_shell_override(self):
        """Expected use: --shell flag takes priority."""
        ctx = detect_context(shell_override="zsh")
        assert ctx.shell == "zsh"
        assert ctx.os_name in ("macOS", "Linux", "Windows")
        assert ctx.cwd == os.getcwd()

    def test_env_var_override(self, monkeypatch):
        """Edge case: AT_CMD_SHELL env var used when no --shell flag."""
        monkeypatch.setenv("AT_CMD_SHELL", "powershell")
        monkeypatch.delenv("SHELL", raising=False)
        ctx = detect_context()
        assert ctx.shell == "powershell"

    def test_shell_from_env(self, monkeypatch):
        """Expected use: $SHELL basename used as fallback."""
        monkeypatch.delenv("AT_CMD_SHELL", raising=False)
        monkeypatch.setenv("SHELL", "/usr/bin/fish")
        ctx = detect_context()
        assert ctx.shell == "fish"

    def test_fallback_to_bash_on_unix(self, monkeypatch):
        """Fallback: no shell info on Unix defaults to bash."""
        monkeypatch.delenv("AT_CMD_SHELL", raising=False)
        monkeypatch.delenv("SHELL", raising=False)
        monkeypatch.setattr("platform.system", lambda: "Linux")
        ctx = detect_context()
        assert ctx.shell == "bash"

    def test_fallback_to_powershell_on_windows(self, monkeypatch):
        """Fallback: no shell info on Windows defaults to powershell."""
        monkeypatch.delenv("AT_CMD_SHELL", raising=False)
        monkeypatch.delenv("SHELL", raising=False)
        monkeypatch.setattr("platform.system", lambda: "Windows")
        ctx = detect_context()
        assert ctx.shell == "powershell"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_windows_no_env_detects_powershell(self, monkeypatch):
        """Regression: on real Windows with no $SHELL, must not return bash."""
        monkeypatch.delenv("AT_CMD_SHELL", raising=False)
        monkeypatch.delenv("SHELL", raising=False)
        ctx = detect_context()
        assert ctx.shell != "bash"

    def test_context_is_frozen(self):
        """Edge case: ShellContext is immutable."""
        ctx = detect_context(shell_override="fish")
        try:
            ctx.shell = "bash"
            assert False, "Should have raised"
        except AttributeError:
            pass
