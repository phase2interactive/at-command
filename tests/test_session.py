"""Tests for at_cmd.session — session context management."""

import pytest

from at_cmd.session import (
    _load_sessions,
    _storage_path,
    clear_session,
    get_or_create_session,
    increment_interactions,
    new_session,
    session_info,
)


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path, monkeypatch):
    """Redirect session storage to a temp directory for every test."""
    fake_path = tmp_path / "sessions.json"
    monkeypatch.setattr("at_cmd.session._storage_path", lambda: fake_path)


# ── ID generation ─────────────────────────────────────────────────


class TestSessionIDGeneration:
    """Tests for deterministic session ID generation."""

    def test_deterministic_per_cwd(self):
        """Same cwd always produces the same session ID."""
        id1 = get_or_create_session("/home/dev/project")
        id2 = get_or_create_session("/home/dev/project")
        assert id1 == id2

    def test_different_cwd_different_id(self):
        """Different cwds produce different session IDs."""
        id1 = get_or_create_session("/home/dev/project-a")
        id2 = get_or_create_session("/home/dev/project-b")
        assert id1 != id2

    def test_session_id_is_valid_uuid(self):
        """Session ID must be a valid UUID (required by Claude CLI --resume)."""
        import uuid

        sid = get_or_create_session("/home/dev/project")
        parsed = uuid.UUID(sid)  # raises ValueError if not valid
        assert str(parsed) == sid

    def test_new_session_different_from_default(self):
        """new_session() returns a different ID than get_or_create_session()."""
        import uuid

        default_id = get_or_create_session("/home/dev/project")
        fresh_id = new_session("/home/dev/project")
        assert fresh_id != default_id
        uuid.UUID(fresh_id)  # must be valid UUID


# ── Storage ───────────────────────────────────────────────────────


class TestSessionStorage:
    """Tests for session file I/O."""

    def test_write_and_read(self):
        """Create a session and read it back."""
        sid = get_or_create_session("/home/dev/project")
        sessions = _load_sessions()
        assert "/home/dev/project" in sessions
        assert sessions["/home/dev/project"]["session_id"] == sid
        assert sessions["/home/dev/project"]["interactions"] == 0

    def test_clear_session(self):
        """Create then clear a session."""
        get_or_create_session("/home/dev/project")
        clear_session("/home/dev/project")
        sessions = _load_sessions()
        assert "/home/dev/project" not in sessions

    def test_clear_nonexistent_session(self):
        """Clearing a session that doesn't exist is a no-op."""
        clear_session("/nonexistent")  # should not raise

    def test_corrupt_file_recovery(self, tmp_path):
        """Corrupt JSON file is handled gracefully."""
        path = _storage_path()
        path.write_text("not valid json{{{")
        sessions = _load_sessions()
        assert sessions == {}

    def test_missing_file(self):
        """Missing storage file returns empty dict."""
        sessions = _load_sessions()
        assert sessions == {}

    def test_increment_interactions(self):
        """Interaction count is bumped correctly."""
        get_or_create_session("/home/dev/project")
        increment_interactions("/home/dev/project")
        increment_interactions("/home/dev/project")
        sessions = _load_sessions()
        assert sessions["/home/dev/project"]["interactions"] == 2

    def test_increment_nonexistent_session(self):
        """Incrementing a nonexistent session is a no-op."""
        increment_interactions("/nonexistent")  # should not raise


# ── Session info ──────────────────────────────────────────────────


class TestSessionInfo:
    """Tests for session_info() output."""

    def test_info_format(self):
        """Info string contains session ID and interaction count."""
        get_or_create_session("/home/dev/project")
        increment_interactions("/home/dev/project")
        info = session_info("/home/dev/project")
        assert info is not None
        assert "Session:" in info
        assert "1 interactions" in info
        assert "started" in info

    def test_info_no_session(self):
        """Returns None when no session exists."""
        info = session_info("/nonexistent")
        assert info is None
