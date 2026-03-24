"""Session context management for per-directory LLM conversation persistence."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _storage_path() -> Path:
    """Return the path to the sessions JSON file.

    Returns:
        Path: ~/.local/share/at-cmd/sessions.json
    """
    return Path.home() / ".local" / "share" / "at-cmd" / "sessions.json"


def _load_sessions() -> dict:
    """Load sessions from the storage file.

    Returns:
        dict: Mapping of cwd -> session data. Empty dict on missing/corrupt file.
    """
    path = _storage_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_sessions(data: dict) -> None:
    """Write sessions dict to the storage file.

    Args:
        data: Sessions mapping to persist.
    """
    path = _storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _default_session_id(cwd: str) -> str:
    """Generate a deterministic session ID from a directory path.

    Args:
        cwd: Working directory path.

    Returns:
        str: Session ID as a UUID-5 string (required by Claude CLI --resume).
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"at-cmd:{cwd}"))


def get_or_create_session(cwd: str) -> str:
    """Get existing session for cwd or create a new one.

    Args:
        cwd: Working directory path.

    Returns:
        str: Session ID.
    """
    sessions = _load_sessions()
    if cwd in sessions:
        return sessions[cwd]["session_id"]

    session_id = _default_session_id(cwd)
    sessions[cwd] = {
        "session_id": session_id,
        "created": datetime.now(timezone.utc).isoformat(),
        "interactions": 0,
    }
    _save_sessions(sessions)
    return session_id


def new_session(cwd: str) -> str:
    """Start a fresh session for cwd, replacing any existing one.

    Args:
        cwd: Working directory path.

    Returns:
        str: New session ID.
    """
    sessions = _load_sessions()
    session_id = str(uuid.uuid4())
    sessions[cwd] = {
        "session_id": session_id,
        "created": datetime.now(timezone.utc).isoformat(),
        "interactions": 0,
    }
    _save_sessions(sessions)
    return session_id


def clear_session(cwd: str) -> None:
    """Remove the session entry for cwd.

    Args:
        cwd: Working directory path.
    """
    sessions = _load_sessions()
    if cwd in sessions:
        del sessions[cwd]
        _save_sessions(sessions)


def increment_interactions(cwd: str) -> None:
    """Bump the interaction count for the cwd session.

    Args:
        cwd: Working directory path.
    """
    sessions = _load_sessions()
    if cwd in sessions:
        sessions[cwd]["interactions"] += 1
        _save_sessions(sessions)


def is_new_session(cwd: str) -> bool:
    """Check whether the session for cwd has zero interactions.

    A new session (0 interactions) has never been sent to the Claude CLI,
    so it needs ``--session-id`` to create the conversation.  After the
    first successful call the interaction count is bumped and subsequent
    calls should use ``--resume``.

    Args:
        cwd: Working directory path.

    Returns:
        bool: True when the session has 0 interactions (never used yet).
    """
    sessions = _load_sessions()
    entry = sessions.get(cwd)
    if entry is None:
        return True
    return entry.get("interactions", 0) == 0


def session_info(cwd: str) -> str | None:
    """Get a formatted info string for the cwd session.

    Args:
        cwd: Working directory path.

    Returns:
        str | None: Info string or None if no session exists.
    """
    sessions = _load_sessions()
    entry = sessions.get(cwd)
    if not entry:
        return None

    sid = entry["session_id"]
    count = entry["interactions"]
    created = datetime.fromisoformat(entry["created"])
    delta = datetime.now(timezone.utc) - created

    # Reason: humanize the time delta into a readable format
    seconds = int(delta.total_seconds())
    if seconds < 60:
        age = f"{seconds}s ago"
    elif seconds < 3600:
        age = f"{seconds // 60}m ago"
    elif seconds < 86400:
        age = f"{seconds // 3600}h ago"
    else:
        age = f"{seconds // 86400}d ago"

    return f"Session: {sid} ({count} interactions, started {age})"
