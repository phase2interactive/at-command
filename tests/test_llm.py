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
        assert "json" in prompt.lower()

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

        captured_args = {}

        def mock_run(*args, **kwargs):
            captured_args["cmd"] = args[0]
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ls -la\nList files\n", stderr=""
            )

        monkeypatch.setattr("subprocess.run", mock_run)

        config = Config(backend="claude", model="sonnet")
        backend_fn = get_backend(config)
        result = backend_fn("system prompt", "list files")
        assert result == "ls -la\nList files\n"
        assert captured_args["cmd"][0] == "/usr/local/bin/claude"

    def test_claude_backend_uses_resolved_path(self, monkeypatch):
        """Regression: cmd[0] must be the resolved path, not bare 'claude'.

        On Windows, shutil.which('claude') returns 'claude.CMD' which
        subprocess.run cannot find without shell=True. Using the resolved
        path avoids this.
        """
        monkeypatch.setattr("shutil.which", lambda x: "C:\\nvm4w\\nodejs\\claude.CMD")

        captured_args = {}

        def mock_run(*args, **kwargs):
            captured_args["cmd"] = args[0]
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ls\nList files\n", stderr=""
            )

        monkeypatch.setattr("subprocess.run", mock_run)

        config = Config(backend="claude", model="sonnet")
        backend_fn = get_backend(config)
        backend_fn("system prompt", "list files")
        assert captured_args["cmd"][0] == "C:\\nvm4w\\nodejs\\claude.CMD"
        assert captured_args["cmd"][0] != "claude"

    def test_openai_backend_requires_api_key(self):
        """Failure case: OpenAI backend without API key."""
        config = Config(backend="openai", api_key="")
        with pytest.raises(BackendError, match="requires AT_CMD_API_KEY"):
            get_backend(config)

    def test_claude_backend_appends_resume_flag(self, monkeypatch):
        """Expected use: --resume is added to subprocess args when session_id is set."""
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/claude")

        captured_args = {}

        def mock_run(*args, **kwargs):
            captured_args["cmd"] = args[0]
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ls\nList files\n", stderr=""
            )

        monkeypatch.setattr("subprocess.run", mock_run)

        config = Config(backend="claude", model="sonnet")
        backend_fn = get_backend(config, session_id="at-cmd-abc123")
        backend_fn("system prompt", "list files")
        assert "--resume" in captured_args["cmd"]
        assert "at-cmd-abc123" in captured_args["cmd"]

    def test_claude_backend_no_resume_without_session(self, monkeypatch):
        """Expected use: no --resume flag when session_id is None."""
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/claude")

        captured_args = {}

        def mock_run(*args, **kwargs):
            captured_args["cmd"] = args[0]
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ls\nList files\n", stderr=""
            )

        monkeypatch.setattr("subprocess.run", mock_run)

        config = Config(backend="claude", model="sonnet")
        backend_fn = get_backend(config, session_id=None)
        backend_fn("system prompt", "list files")
        assert "--resume" not in captured_args["cmd"]
        assert "--session-id" not in captured_args["cmd"]


class TestSessionIdVsResume:
    """Tests for --session-id (new) vs --resume (existing) flag selection."""

    def _capture_cmd(self, monkeypatch):
        """Helper: mock shutil.which and subprocess.run, return captured cmd list."""
        monkeypatch.setattr("shutil.which", lambda x: "/usr/local/bin/claude")
        captured = {}

        def mock_run(*args, **kwargs):
            captured["cmd"] = args[0]
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ls\nList files\n", stderr=""
            )

        monkeypatch.setattr("subprocess.run", mock_run)
        return captured

    def test_new_session_uses_session_id_flag(self, monkeypatch):
        """Expected use: is_new=True sends --session-id to create conversation."""
        captured = self._capture_cmd(monkeypatch)
        config = Config(backend="claude", model="sonnet")
        backend_fn = get_backend(config, session_id="test-uuid-123", is_new=True)
        backend_fn("system prompt", "list files")
        assert "--session-id" in captured["cmd"]
        assert "test-uuid-123" in captured["cmd"]
        assert "--resume" not in captured["cmd"]

    def test_existing_session_uses_resume_flag(self, monkeypatch):
        """Expected use: is_new=False sends --resume to continue conversation."""
        captured = self._capture_cmd(monkeypatch)
        config = Config(backend="claude", model="sonnet")
        backend_fn = get_backend(config, session_id="test-uuid-456", is_new=False)
        backend_fn("system prompt", "list files")
        assert "--resume" in captured["cmd"]
        assert "test-uuid-456" in captured["cmd"]
        assert "--session-id" not in captured["cmd"]

    def test_no_flags_without_session_id(self, monkeypatch):
        """Edge case: no session flags when session_id is None, regardless of is_new."""
        captured = self._capture_cmd(monkeypatch)
        config = Config(backend="claude", model="sonnet")
        backend_fn = get_backend(config, session_id=None, is_new=True)
        backend_fn("system prompt", "list files")
        assert "--session-id" not in captured["cmd"]
        assert "--resume" not in captured["cmd"]

    def test_is_new_defaults_to_false(self, monkeypatch):
        """Edge case: omitting is_new defaults to --resume for existing sessions."""
        captured = self._capture_cmd(monkeypatch)
        config = Config(backend="claude", model="sonnet")
        # Reason: is_new not passed — should default to False → --resume
        backend_fn = get_backend(config, session_id="test-uuid-789")
        backend_fn("system prompt", "list files")
        assert "--resume" in captured["cmd"]
        assert "--session-id" not in captured["cmd"]
