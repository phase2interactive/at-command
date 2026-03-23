"""Tests for at_cmd.init — shell init script generation."""

import pytest

from at_cmd.init import generate


class TestGenerate:
    """Tests for the generate() function."""

    def test_fish_inline_default(self):
        """Expected use: fish inline mode intercepts Enter for @ commands."""
        out = generate("fish")
        assert "function _at_cmd_enter" in out
        assert "bind \\r _at_cmd_enter" in out
        assert "_at_cmd_inline" in out
        assert "history append" in out

    def test_fish_submit_default(self, monkeypatch):
        """Expected use: fish submit mode defines @ function."""
        monkeypatch.setenv("AT_CMD_DEFAULT_MODE", "submit")
        out = generate("fish")
        assert "function @" in out
        assert "bind \\r _at_cmd_enter" not in out

    def test_bash_contains_both_modes(self):
        """Expected use: bash defines both submit and inline functions."""
        out = generate("bash")
        assert "_at_cmd_submit()" in out
        assert "_at_cmd_inline()" in out
        assert "history -s" in out

    def test_zsh_inline_default(self):
        """Expected use: zsh inline mode intercepts Enter."""
        out = generate("zsh")
        assert "_at_cmd_enter" in out
        assert "accept-line" in out
        assert "print -z" in out

    def test_powershell_contains_psreadline(self):
        """Expected use: powershell script uses PSReadLine."""
        out = generate("powershell")
        assert "function at" in out
        assert "PSReadLine" in out
        assert "AddToHistory" in out

    def test_unknown_shell_raises(self):
        """Failure case: unsupported shell raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported shell"):
            generate("tcsh")

    def test_generates_header_comment(self):
        """Edge case: output includes generated-by comment and mode."""
        for shell in ("bash", "zsh", "fish", "powershell"):
            out = generate(shell)
            assert f"at-cmd init {shell}" in out
            assert "default_mode:" in out
