"""Tests for at_cmd.keybindings — key name to escape sequence mapping."""

from at_cmd.keybindings import get_binding


class TestGetBinding:
    """Tests for get_binding()."""

    def test_known_key_and_shell(self):
        """Expected use: returns escape sequence for a known combo."""
        assert get_binding("ctrl+enter", "fish") is not None
        assert get_binding("ctrl+z", "bash") is not None

    def test_unknown_key_returns_none(self):
        """Failure case: unrecognized key name."""
        assert get_binding("super+f12", "bash") is None

    def test_unknown_shell_returns_none(self):
        """Failure case: unrecognized shell name."""
        assert get_binding("ctrl+enter", "tcsh") is None

    def test_case_insensitive(self):
        """Edge case: key names and shell names are case-insensitive."""
        assert get_binding("Ctrl+Enter", "Fish") == get_binding("ctrl+enter", "fish")

    def test_all_shells_have_ctrl_enter(self):
        """Edge case: every shell has a binding for ctrl+enter."""
        for shell in ("bash", "zsh", "fish", "powershell"):
            assert get_binding("ctrl+enter", shell) is not None
