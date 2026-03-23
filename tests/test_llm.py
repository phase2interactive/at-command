"""Tests for at_cmd.llm."""

import subprocess

import pytest

from at_cmd.config import Config
from at_cmd.detect import ShellContext
from at_cmd.llm import BackendError, build_system_prompt, get_backend


class TestBuildSystemPrompt:
    """Tests for build_system_prompt."""

    def test_contains_shell_and_os(self):
        """Expected use: prompt includes shell, OS, and cwd."""
        ctx = ShellContext(os_name="Linux", shell="fish", cwd="/home/user")
        prompt = build_system_prompt(ctx)
        assert "fish" in prompt
        assert "Linux" in prompt
        assert "/home/user" in prompt
        assert "two lines" in prompt.lower() or "EXACTLY two lines" in prompt

    def test_different_shell_context(self):
        """Edge case: Windows + PowerShell context."""
        ctx = ShellContext(os_name="Windows", shell="powershell", cwd="C:\\Users\\me")
        prompt = build_system_prompt(ctx)
        assert "powershell" in prompt
        assert "Windows" in prompt


class TestGetBackend:
    """Tests for get_backend."""

    def test_unknown_backend_raises(self):
        """Failure case: unrecognized backend name."""
        config = Config(backend="nonexistent")
        with pytest.raises(BackendError, match="Unknown backend"):
            get_backend(config)

    def test_claude_backend_missing_cli(self, monkeypatch):
        """Failure case: claude CLI not installed."""
        monkeypatch.setattr("shutil.which", lambda x: None)
        config = Config(backend="claude")
        with pytest.raises(BackendError, match="Claude CLI not found"):
            get_backend(config)

    def test_claude_backend_calls_subprocess(self, monkeypatch):
        """Expected use: claude backend invokes subprocess correctly."""
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/claude")

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="ls -la\nList files\n", stderr=""
        )
        monkeypatch.setattr(
            "subprocess.run", lambda *args, **kwargs: mock_result
        )

        config = Config(backend="claude", model="sonnet")
        backend_fn = get_backend(config)
        result = backend_fn("system prompt", "list files")
        assert result == "ls -la\nList files\n"

    def test_openai_backend_requires_api_key(self):
        """Failure case: OpenAI backend without API key."""
        config = Config(backend="openai", api_key="")
        with pytest.raises(BackendError, match="requires AT_CMD_API_KEY"):
            get_backend(config)
