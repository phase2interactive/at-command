"""Integration tests for the Claude CLI backend.

These tests call the real Claude CLI and are skipped if it's not installed.
Mark: pytest -m integration
"""

import shutil
import uuid

import pytest

from at_cmd.config import Config
from at_cmd.llm import BackendError, get_backend

pytestmark = pytest.mark.integration

requires_claude = pytest.mark.skipif(
    not shutil.which("claude"),
    reason="Claude CLI not installed",
)


@requires_claude
class TestClaudeResume:
    """Tests for --resume interaction with the real Claude CLI."""

    def test_resume_with_nonexistent_session_raises(self):
        """Failure case: --resume with unknown UUID raises BackendError.

        This is the exact scenario that caused the production bug:
        at-cmd generates a deterministic session ID, passes it via --resume,
        but Claude CLI has no conversation with that ID yet.
        """
        config = Config(backend="claude")
        fake_session_id = str(uuid.uuid4())
        backend_fn = get_backend(config, session_id=fake_session_id, is_new=False)

        with pytest.raises(BackendError, match="No conversation found"):
            backend_fn("You are a test.", "echo hello")


@requires_claude
class TestClaudeSessionLifecycle:
    """Tests for --session-id → --resume lifecycle with real Claude CLI."""

    def test_session_id_creates_conversation(self):
        """Expected use: --session-id with a new UUID creates a conversation.

        The first call for a new session must use --session-id so Claude CLI
        creates the conversation. This should succeed without error.
        """
        config = Config(backend="claude")
        session_id = str(uuid.uuid4())
        backend_fn = get_backend(config, session_id=session_id, is_new=True)

        # Reason: A simple prompt that should always produce a valid response
        result = backend_fn(
            "You are a shell command translator. Return ONLY a JSON object "
            'with fields "command" and "description".',
            "echo hello",
        )
        assert result  # non-empty response

    def test_resume_after_session_id_succeeds(self):
        """Expected use: --resume works after conversation was created with --session-id.

        This tests the full lifecycle: first call creates with --session-id,
        second call continues with --resume using the same UUID.
        """
        config = Config(backend="claude")
        session_id = str(uuid.uuid4())

        # First call — create the conversation
        create_fn = get_backend(config, session_id=session_id, is_new=True)
        result1 = create_fn(
            "You are a shell command translator. Return ONLY a JSON object "
            'with fields "command" and "description".',
            "echo hello",
        )
        assert result1

        # Second call — resume the conversation
        resume_fn = get_backend(config, session_id=session_id, is_new=False)
        result2 = resume_fn(
            "You are a shell command translator. Return ONLY a JSON object "
            'with fields "command" and "description".',
            "list files in current directory",
        )
        assert result2
