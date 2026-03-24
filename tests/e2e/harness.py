"""E2E test harness: drives at-cmd via pexpect and records with asciinema.

The harness wraps each test run in an asciinema recording so you get both:
  1. pexpect-style assertions during the run (interactive)
  2. A .cast file you can replay or parse after the fact

Usage in a test::

    from tests.e2e.harness import E2ESession

    def test_translate_json(tmp_path):
        with E2ESession(tmp_path / "test.cast") as s:
            s.send("at-cmd --json find big files")
            s.expect_json(keys=["command", "description"])

Usage for manual inspection::

    s = E2ESession(Path("recordings/demo.cast"))
    s.start()
    s.send("at-cmd list docker containers")
    s.expect(r"#.*", timeout=15)   # wait for description comment
    s.send("\\r")                   # press Enter to execute
    s.stop()
    s.print_frames()
"""

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import pexpect

# Braille spinner characters used by at-cmd (see spinner.py)
_SPINNER_CHARS = set("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")

# Reason: matches all ANSI escape sequences — CSI (colors, cursor movement),
# OSC (window titles), bracket paste mode, and simple two-char sequences.
# Built from real capture data: /tmp/capture-raw.cast
_ANSI_RE = re.compile(
    r"\x1b\[\?[0-9;]*[a-zA-Z]"  # private mode sequences (?2004h bracket paste, ?25l cursor hide)
    r"|\x1b\[[0-9;]*[a-zA-Z]"   # CSI sequences (colors, cursor movement, \x1b[K erase line)
    r"|\x1b\][^\x07]*\x07"       # OSC sequences (window titles)
    r"|\x1b[()][0-9A-Z]"         # charset switches
    r"|\x1b[>=<]"                 # keypad mode
)


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text.

    Strips CSI sequences (colors, cursor), OSC sequences (window titles),
    bracket paste toggles, and erase-line codes. Preserves \\r so that
    collapse_cr() can resolve overwritten lines afterward.

    Args:
        text: Raw terminal output with escape codes.

    Returns:
        str: Text with escape codes removed but line structure intact.
    """
    return _ANSI_RE.sub("", text)


def collapse_cr(text: str) -> str:
    """Resolve carriage returns so only the final content of each line remains.

    Terminals use \\r to move the cursor to column 0 and overwrite the line
    (e.g., spinners, progress bars). This replays that logic: for each line,
    only the text after the last \\r survives — which is what the user sees.

    Preserves \\r\\n (standard line endings) — only bare \\r triggers collapse.

    Args:
        text: Text with bare \\r characters (after ANSI stripping).

    Returns:
        str: Text with \\r-overwritten content collapsed.
    """
    # Reason: normalize \r\n to \n first so we don't treat line endings as overwrites
    text = text.replace("\r\n", "\n")
    result = []
    for line in text.split("\n"):
        if "\r" in line:
            # Reason: the last \r-delimited segment is what's visible on screen
            segments = line.split("\r")
            visible = segments[-1]
            result.append(visible)
        else:
            result.append(line)
    return "\n".join(result)


def clean_output(text: str) -> str:
    """Full preprocessing pipeline: strip ANSI, then collapse \\r overwrites.

    This is the main entry point for cleaning raw terminal output.
    It produces text that matches what the human sees on screen.

    Args:
        text: Raw terminal output from asciicast frames.

    Returns:
        str: Clean, human-readable text.
    """
    return collapse_cr(strip_ansi(text))


@dataclass
class CastFrame:
    """A single frame from an asciicast v2 recording.

    Attributes:
        timestamp: Seconds since recording start.
        event_type: 'o' for stdout, 'i' for stdin.
        data: The text content of the frame.
    """

    timestamp: float
    event_type: str
    data: str

    @property
    def clean(self) -> str:
        """Data with ANSI codes stripped and \\r overwrites collapsed.

        Returns:
            str: Human-readable text content.
        """
        return clean_output(self.data)


@dataclass
class CastRecording:
    """Parsed asciicast v2 file.

    Attributes:
        header: The header dict from the cast file.
        frames: List of CastFrame events.
    """

    header: dict = field(default_factory=dict)
    frames: list[CastFrame] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "CastRecording":
        """Parse a .cast file into a CastRecording.

        Args:
            path: Path to the asciicast v2 file.

        Returns:
            CastRecording: The parsed recording.
        """
        rec = cls()
        text = path.read_text()
        lines = text.strip().splitlines()
        if not lines:
            return rec

        rec.header = json.loads(lines[0])
        for line in lines[1:]:
            if not line.strip():
                continue
            ts, etype, data = json.loads(line)
            rec.frames.append(CastFrame(timestamp=ts, event_type=etype, data=data))
        return rec

    def stdout_text(self, clean: bool = True) -> str:
        """Concatenate all stdout frames into a single string.

        Args:
            clean: If True (default), strip ANSI escape codes.

        Returns:
            str: All stdout output joined together.
        """
        raw = "".join(f.data for f in self.frames if f.event_type == "o")
        return clean_output(raw) if clean else raw

    def frames_between(self, start: float, end: float) -> list[CastFrame]:
        """Return frames within a time window.

        Args:
            start: Start time in seconds.
            end: End time in seconds.

        Returns:
            list[CastFrame]: Frames in the time window.
        """
        return [f for f in self.frames if start <= f.timestamp <= end]

    def frame_rate(self, window: float = 0.5) -> list[tuple[float, int]]:
        """Count frames per window — useful for verifying animations.

        Args:
            window: Time window in seconds.

        Returns:
            list[tuple[float, int]]: (window_start, count) pairs.
        """
        if not self.frames:
            return []
        max_ts = self.frames[-1].timestamp
        buckets = []
        t = 0.0
        while t <= max_ts:
            count = len(self.frames_between(t, t + window))
            buckets.append((t, count))
            t += window
        return buckets

    def transcript(
        self,
        pause_threshold: float = 1.5,
        prompt_patterns: tuple[str, ...] = ("$ ",),
    ) -> list["TranscriptEntry"]:
        """Build an annotated transcript from the recording.

        Classifies each frame into semantic events (PROMPT, INPUT, OUTPUT,
        SPINNER, PAUSE, ERROR) and collapses repeated frames (like spinner
        animation) into single entries with duration.

        Args:
            pause_threshold: Minimum gap in seconds to emit a PAUSE entry.
            prompt_patterns: Strings that indicate a shell prompt line.

        Returns:
            list[TranscriptEntry]: Annotated events in chronological order.
        """
        entries: list[TranscriptEntry] = []
        prev_ts = 0.0
        spinner_start: float | None = None
        spinner_count = 0
        spinner_label = ""

        def _flush_spinner() -> None:
            """Emit a SPINNER entry for accumulated spinner frames."""
            nonlocal spinner_start, spinner_count, spinner_label
            if spinner_start is not None:
                duration = prev_ts - spinner_start
                entries.append(TranscriptEntry(
                    timestamp=spinner_start,
                    kind="SPINNER",
                    text=spinner_label,
                    duration=duration,
                    note=f"{spinner_count} frames @ ~{_INTERVAL_MS}ms",
                ))
                spinner_start = None
                spinner_count = 0
                spinner_label = ""

        for frame in self.frames:
            if frame.event_type != "o":
                continue

            gap = frame.timestamp - prev_ts
            clean = clean_output(frame.data)
            raw = frame.data

            # Detect spinner frames: contain braille chars and \r (overwrite)
            is_spinner = (
                "\r" in raw
                and any(ch in raw for ch in _SPINNER_CHARS)
            )

            # Emit PAUSE for significant gaps (but not before the first frame,
            # and not during spinner — spinner has its own duration)
            if gap >= pause_threshold and prev_ts > 0 and spinner_start is None:
                _flush_spinner()
                note = _pause_hint(gap, entries)
                entries.append(TranscriptEntry(
                    timestamp=prev_ts,
                    kind="PAUSE",
                    text="",
                    duration=gap,
                    note=note,
                ))

            if is_spinner:
                if spinner_start is None:
                    _flush_spinner()
                    spinner_start = frame.timestamp
                    # Reason: extract the label text after the braille char
                    spinner_label = clean.strip()
                spinner_count += 1
                prev_ts = frame.timestamp
                continue

            # Non-spinner frame — flush any pending spinner first
            _flush_spinner()

            # Reason: look past PAUSE entries to find the last semantic event,
            # because user input often arrives after a typing-delay PAUSE
            prev_kind = ""
            for e in reversed(entries):
                if e.kind != "PAUSE":
                    prev_kind = e.kind
                    break

            # Skip empty frames (erase-line, bracket paste toggles)
            if not clean.strip():
                prev_ts = frame.timestamp
                continue

            kind = _classify_frame(clean, prompt_patterns, prev_kind)

            # Merge consecutive OUTPUT lines into a single burst
            if kind == "OUTPUT" and entries and entries[-1].kind == "OUTPUT":
                last = entries[-1]
                last.text += "\n" + clean.strip()
                last.duration = frame.timestamp - last.timestamp
                prev_ts = frame.timestamp
                continue

            entries.append(TranscriptEntry(
                timestamp=frame.timestamp,
                kind=kind,
                text=clean.strip(),
            ))
            prev_ts = frame.timestamp

        _flush_spinner()
        return entries

    def transcript_text(self, **kwargs: object) -> str:
        """Render the transcript as formatted text.

        Args:
            **kwargs: Passed through to transcript().

        Returns:
            str: Human-readable annotated transcript.
        """
        entries = self.transcript(**kwargs)
        lines = []
        for e in entries:
            ts = f"[t={e.timestamp:.3f}]"
            note = f"  ← {e.note}" if e.note else ""

            if e.kind == "PAUSE":
                lines.append(f"{ts} PAUSE: {e.duration:.1f}s{note}")
            elif e.kind == "SPINNER":
                lines.append(f"{ts} SPINNER ({e.duration:.1f}s): {e.text}{note}")
            elif e.kind == "RESPONSE":
                # Reason: parse the JSON for a compact display
                try:
                    data = json.loads(e.text)
                    cmd = data.get("command", "")
                    desc = data.get("description", "")
                    lines.append(f"{ts} RESPONSE: `{cmd}` — {desc}{note}")
                except (json.JSONDecodeError, TypeError):
                    lines.append(f"{ts} RESPONSE: {e.text}{note}")
            elif e.kind in ("OUTPUT", "ERROR"):
                # Indent multi-line output
                text_lines = e.text.splitlines()
                duration_str = f" ({e.duration:.1f}s)" if e.duration and e.duration > 0.01 else ""
                if len(text_lines) == 1:
                    lines.append(f"{ts} {e.kind}{duration_str}: {text_lines[0]}{note}")
                else:
                    lines.append(f"{ts} {e.kind}{duration_str}:{note}")
                    for tl in text_lines:
                        lines.append(f"  {tl}")
            else:
                lines.append(f"{ts} {e.kind}: {e.text}{note}")

        return "\n".join(lines)


# Reason: spinner.py uses 80ms interval
_INTERVAL_MS = 80


@dataclass
class TranscriptEntry:
    """A single semantic event in an annotated transcript.

    Attributes:
        timestamp: Seconds since recording start.
        kind: Event type. One of:
            PROMPT      — shell prompt appeared (includes chrome)
            INPUT       — user typed a command
            OUTPUT      — generic program output
            RESPONSE    — at-cmd JSON response (translated command)
            DESCRIPTION — at-cmd description comment (# after spinner)
            SPINNER     — collapsed spinner animation
            PAUSE       — significant gap in output
            ERROR       — error message
        text: Cleaned content of the event.
        duration: Duration in seconds (for SPINNER, PAUSE, OUTPUT bursts).
        note: Optional annotation (e.g., "user hesitation", "LLM latency").
    """

    timestamp: float
    kind: str
    text: str
    duration: float | None = None
    note: str = ""


def _classify_frame(
    clean: str,
    prompt_patterns: tuple[str, ...],
    prev_kind: str = "",
) -> str:
    """Classify a cleaned frame into a transcript event kind.

    Classification relies on:
    - Content patterns from at-cmd's documented behavior (Error: prefix,
      JSON with "command" key, # description prefix)
    - Sequencing (what came before this frame)
    - User-supplied prompt_patterns for shell prompt detection

    Does NOT rely on specific prompt characters, ANSI color codes, or
    shell-specific behaviors.

    Args:
        clean: Cleaned frame text.
        prompt_patterns: Strings that indicate a shell prompt.
        prev_kind: The kind of the previous non-PAUSE transcript entry.

    Returns:
        str: Event kind — see TranscriptEntry.kind for the full list.
    """
    stripped = clean.strip()

    # Reason: errors from at-cmd use click.echo(f"Error: {e}", err=True)
    if stripped.startswith("Error:"):
        return "ERROR"

    # Reason: at-cmd description is a # comment emitted right after the
    # spinner finishes (cli.py: click.echo(f"# {description}", err=True)).
    # The sequencing constraint (prev_kind == SPINNER) prevents false
    # positives from shell comments or other # text.
    if stripped.startswith("#") and prev_kind == "SPINNER":
        return "DESCRIPTION"

    # Reason: at-cmd JSON response follows the documented contract —
    # a JSON object with a "command" key (see sanitize.py, CLAUDE.md).
    if stripped.startswith("{") and '"command"' in stripped:
        return "RESPONSE"

    # Reason: shell prompts contain a user-configured marker string.
    # The caller passes prompt_patterns appropriate to their shell.
    for pat in prompt_patterns:
        if pat in stripped:
            # Reason: if there's content after the prompt marker, it's
            # the prompt + user input combined in one frame
            idx = stripped.rfind(pat)
            after = stripped[idx + len(pat):].strip()
            if after:
                return "INPUT"
            return "PROMPT"

    # Reason: text following a PROMPT is user input — in real captures,
    # the user's typed command arrives as a separate frame after the
    # prompt, often with a PAUSE in between (typing delay).
    if prev_kind == "PROMPT" and not stripped.startswith("#"):
        return "INPUT"

    return "OUTPUT"


def _pause_hint(gap: float, entries: list[TranscriptEntry]) -> str:
    """Generate a human-readable hint about what a pause likely means.

    Args:
        gap: Duration of the pause in seconds.
        entries: Transcript entries so far (for context).

    Returns:
        str: Brief hint like "user hesitation" or "LLM latency".
    """
    if not entries:
        return ""

    last_kind = entries[-1].kind

    # Reason: pause after PROMPT = user is thinking about what to type
    if last_kind == "PROMPT":
        return "user hesitation / thinking"

    # Reason: pause after SPINNER = waiting for backend response
    if last_kind == "SPINNER":
        return "blocked / loading"

    # Reason: pause after INPUT = user typed command, waiting for response
    if last_kind == "INPUT":
        return "waiting for response"

    # Reason: pause after ERROR = user reading error, deciding next step
    if last_kind == "ERROR":
        return "reading error"

    # Reason: pause after RESPONSE or DESCRIPTION = user reading result
    if last_kind in ("RESPONSE", "DESCRIPTION"):
        return "user reading result"

    return ""


class E2ESession:
    """Manages a pexpect session inside an asciinema recording.

    Can be used as a context manager for test functions, or manually
    via start()/stop() for ad-hoc exploration.

    Args:
        cast_path: Where to save the .cast recording.
        cols: Terminal width.
        rows: Terminal height.
        env: Extra environment variables for the child process.
        shell: Shell to use inside asciinema (default: bash).
    """

    def __init__(
        self,
        cast_path: Path | str,
        cols: int = 120,
        rows: int = 30,
        env: dict[str, str] | None = None,
        shell: str = "bash",
    ):
        self.cast_path = Path(cast_path)
        self.cols = cols
        self.rows = rows
        self.shell = shell
        self._extra_env = env or {}
        self._child: pexpect.spawn | None = None

    def start(self) -> "E2ESession":
        """Launch asciinema recording with a shell inside it.

        Returns:
            E2ESession: self, for chaining.
        """
        self.cast_path.parent.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.update(self._extra_env)
        # Reason: force a simple prompt so we can reliably match it
        env["PS1"] = "$ "
        env["TERM"] = "xterm-256color"

        cmd = (
            f"asciinema rec --overwrite --quiet "
            f"--cols {self.cols} --rows {self.rows} "
            f'-c {self.shell} "{self.cast_path}"'
        )

        self._child = pexpect.spawn(
            "bash",
            args=["-c", cmd],
            env=env,
            encoding="utf-8",
            timeout=30,
            dimensions=(self.rows, self.cols),
        )
        # Wait for shell prompt inside asciinema
        self._child.expect(r"\$\s*", timeout=10)
        return self

    def stop(self) -> CastRecording | None:
        """Stop the recording and return the parsed cast file.

        Returns:
            CastRecording | None: Parsed recording, or None if no file.
        """
        if self._child and self._child.isalive():
            self._child.sendline("exit")
            self._child.expect(pexpect.EOF, timeout=10)
            self._child.close()

        if self.cast_path.exists():
            return CastRecording.load(self.cast_path)
        return None

    def send(self, text: str) -> None:
        """Send a line of text to the terminal.

        Args:
            text: The command or text to type.
        """
        assert self._child is not None, "Session not started"
        self._child.sendline(text)

    def send_keys(self, keys: str) -> None:
        """Send raw characters (for hotkeys, arrow keys, etc).

        Args:
            keys: Raw characters to send (e.g. '\\x1b' for Escape).
        """
        assert self._child is not None, "Session not started"
        self._child.send(keys)

    def expect(self, pattern: str, timeout: int = 15) -> str:
        """Wait for a regex pattern in the output.

        Args:
            pattern: Regex pattern to match.
            timeout: Seconds to wait.

        Returns:
            str: The matched text.

        Raises:
            pexpect.TIMEOUT: If pattern not seen within timeout.
        """
        assert self._child is not None, "Session not started"
        self._child.expect(pattern, timeout=timeout)
        return self._child.after if isinstance(self._child.after, str) else ""

    def expect_text(self, text: str, timeout: int = 15) -> str:
        """Wait for literal text in the output.

        Args:
            text: Literal string to look for.
            timeout: Seconds to wait.

        Returns:
            str: The matched text.
        """
        return self.expect(re.escape(text), timeout=timeout)

    def expect_json(self, keys: list[str] | None = None, timeout: int = 15) -> dict:
        """Wait for a JSON line in the output and optionally validate keys.

        Args:
            keys: Expected top-level keys (optional).
            timeout: Seconds to wait.

        Returns:
            dict: The parsed JSON object.

        Raises:
            AssertionError: If expected keys are missing.
        """
        assert self._child is not None, "Session not started"
        # Reason: JSON output is always a single line starting with {
        self._child.expect(r"\{.*\}", timeout=timeout)
        raw = self._child.after if isinstance(self._child.after, str) else ""
        data = json.loads(raw)
        if keys:
            missing = set(keys) - set(data.keys())
            assert not missing, f"Missing keys in JSON response: {missing}"
        return data

    def current_screen(self) -> str:
        """Return everything currently in the pexpect buffer.

        Returns:
            str: Current buffer contents.
        """
        assert self._child is not None, "Session not started"
        return self._child.before or ""

    def wait(self, seconds: float) -> None:
        """Sleep — useful for letting animations render.

        Args:
            seconds: Time to wait.
        """
        time.sleep(seconds)

    # Context manager support
    def __enter__(self) -> "E2ESession":
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.stop()

    def print_frames(self, limit: int = 50) -> None:
        """Print frames from the recording (for debugging).

        Args:
            limit: Max frames to print.
        """
        if not self.cast_path.exists():
            print("No recording file found.")
            return
        rec = CastRecording.load(self.cast_path)
        for i, frame in enumerate(rec.frames[:limit]):
            preview = repr(frame.data[:80])
            print(f"  [{frame.timestamp:6.2f}s] {frame.event_type}: {preview}")
        if len(rec.frames) > limit:
            print(f"  ... and {len(rec.frames) - limit} more frames")
