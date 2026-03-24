"""Basic e2e tests for at-cmd using the harness.

These tests require a working LLM backend (Claude CLI by default).
They are marked as e2e and excluded from the default test run.
"""

import json
import shutil

import pytest

from .harness import CastRecording, E2ESession

pytestmark = pytest.mark.e2e


@pytest.fixture
def cast_path(tmp_path):
    """Provide a temporary .cast file path."""
    return tmp_path / "test.cast"


def _skip_if_no_at_cmd():
    if not shutil.which("at-cmd"):
        pytest.skip("at-cmd not installed (run `just dev` first)")


class TestJSONMode:
    """Test the --json output mode end-to-end."""

    def test_json_output_has_required_keys(self, cast_path):
        """Verify --json returns command and description keys."""
        _skip_if_no_at_cmd()

        with E2ESession(cast_path) as s:
            s.send("at-cmd --json list files in current directory")
            # Reason: wait for JSON output, then the shell prompt after
            s.expect(r"\$\s*", timeout=30)

        rec = CastRecording.load(cast_path)
        stdout = rec.stdout_text()
        # Reason: find the JSON line in the output
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                data = json.loads(line)
                assert "command" in data
                assert "description" in data
                return
        pytest.fail("No JSON output found in recording")

    def test_json_output_command_is_plausible(self, cast_path):
        """Verify the command looks like a real shell command."""
        _skip_if_no_at_cmd()

        with E2ESession(cast_path) as s:
            s.send("at-cmd --json show disk usage")
            s.expect(r"\$\s*", timeout=30)

        rec = CastRecording.load(cast_path)
        stdout = rec.stdout_text()
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("{"):
                data = json.loads(line)
                cmd = data.get("command", "")
                # Reason: should contain du or df for disk usage
                assert any(tok in cmd for tok in ["du", "df", "disk"]), (
                    f"Command doesn't look like a disk usage command: {cmd}"
                )
                return
        pytest.fail("No JSON output found in recording")


class TestInteractivePrompt:
    """Test the interactive readline prompt."""

    def test_shows_description_comment(self, cast_path):
        """Verify the dim description comment appears on stderr."""
        _skip_if_no_at_cmd()

        with E2ESession(cast_path) as s:
            s.send("at-cmd list running docker containers")
            # Reason: the description is prefixed with #
            s.expect(r"#\s+\S+", timeout=30)
            # Send Ctrl-C to exit the readline prompt
            s.send_keys("\x03")
            s.expect(r"\$\s*", timeout=5)

        rec = CastRecording.load(cast_path)
        stdout = rec.stdout_text()
        assert "#" in stdout, "Expected a description comment in output"

    def test_ctrl_c_exits_cleanly(self, cast_path):
        """Verify Ctrl-C exits without traceback."""
        _skip_if_no_at_cmd()

        with E2ESession(cast_path) as s:
            s.send("at-cmd show current date")
            s.expect(r"#\s+\S+", timeout=30)
            s.send_keys("\x03")
            s.expect(r"\$\s*", timeout=5)

        rec = CastRecording.load(cast_path)
        stdout = rec.stdout_text()
        assert "Traceback" not in stdout, "Ctrl-C should exit cleanly"


class TestRecordingAnalysis:
    """Tests that verify we can analyze the cast recordings themselves."""

    def test_cast_file_is_valid_asciicast(self, cast_path):
        """Verify the recording is valid asciicast v2 format."""
        _skip_if_no_at_cmd()

        with E2ESession(cast_path) as s:
            s.send("echo hello-e2e-test")
            s.expect("hello-e2e-test", timeout=5)

        rec = CastRecording.load(cast_path)
        assert rec.header.get("version") == 2
        assert len(rec.frames) > 0
        assert "hello-e2e-test" in rec.stdout_text()

    def test_spinner_produces_animation_frames(self, cast_path):
        """Verify the spinner generates multiple output frames quickly.

        This is the kind of test that's only possible with recording analysis —
        we check that the spinner is actually animating by looking at frame rate.
        """
        _skip_if_no_at_cmd()

        with E2ESession(cast_path) as s:
            s.send("at-cmd list files")
            # Reason: wait for spinner to animate, then the response
            s.expect(r"(#|\{)", timeout=30)
            s.send_keys("\x03")
            s.expect(r"\$\s*", timeout=5)

        rec = CastRecording.load(cast_path)
        # Reason: spinner updates at ~80ms intervals, so we should see
        # multiple frames in the first few seconds
        early_frames = rec.frames_between(0.0, 3.0)
        assert len(early_frames) > 5, (
            f"Expected spinner animation frames, got only {len(early_frames)}"
        )
