"""Tests for at_cmd.sanitize."""

import pytest

from at_cmd.sanitize import LLMResponse, SanitizeError, parse_response, sanitize_response


class TestSanitizeResponse:
    """Tests for sanitize_response."""

    def test_basic_two_line_response(self):
        """Expected use: clean two-line LLM output."""
        raw = "find . -name '*.py' -mtime -7\nFind Python files modified in the last 7 days"
        cmd, desc = sanitize_response(raw)
        assert cmd == "find . -name '*.py' -mtime -7"
        assert desc == "Find Python files modified in the last 7 days"

    def test_strips_markdown_fences(self):
        """Edge case: markdown code fences around command."""
        raw = "```bash\nls -la /tmp\nList all files in tmp\n```"
        cmd, desc = sanitize_response(raw)
        assert cmd == "ls -la /tmp"
        assert desc == "List all files in tmp"

    def test_strips_leading_dollar_sign(self):
        """Edge case: leading $ prompt character."""
        raw = "$ docker ps -a\nList all Docker containers"
        cmd, desc = sanitize_response(raw)
        assert cmd == "docker ps -a"
        assert desc == "List all Docker containers"

    def test_strips_leading_chevron(self):
        """Edge case: leading > prompt character."""
        raw = "> Get-Process\nList running processes"
        cmd, desc = sanitize_response(raw)
        assert cmd == "Get-Process"
        assert desc == "List running processes"

    def test_strips_leading_hash(self):
        """Edge case: leading # (root prompt)."""
        raw = "# apt update\nUpdate package lists"
        cmd, desc = sanitize_response(raw)
        assert cmd == "apt update"
        assert desc == "Update package lists"

    def test_strips_surrounding_backticks(self):
        """Edge case: command wrapped in backticks."""
        raw = "`git status`\nShow working tree status"
        cmd, desc = sanitize_response(raw)
        assert cmd == "git status"
        assert desc == "Show working tree status"

    def test_command_only_no_description(self):
        """Edge case: LLM returns only one line."""
        raw = "echo hello"
        cmd, desc = sanitize_response(raw)
        assert cmd == "echo hello"
        assert desc == ""

    def test_skips_blank_lines(self):
        """Edge case: blank lines between command and description."""
        raw = "\n\nfind . -type f\n\nFind all regular files\n\n"
        cmd, desc = sanitize_response(raw)
        assert cmd == "find . -type f"
        assert desc == "Find all regular files"

    def test_empty_string_raises(self):
        """Failure case: empty input."""
        with pytest.raises(SanitizeError, match="Empty response"):
            sanitize_response("")

    def test_whitespace_only_raises(self):
        """Failure case: whitespace-only input."""
        with pytest.raises(SanitizeError, match="Empty response"):
            sanitize_response("   \n\n  ")

    def test_none_raises(self):
        """Failure case: None input."""
        with pytest.raises(SanitizeError, match="Empty response"):
            sanitize_response(None)

    def test_only_prompt_chars_raises(self):
        """Failure case: line is just a prompt character."""
        with pytest.raises(SanitizeError, match="empty after sanitization"):
            sanitize_response("$ ")

    def test_strips_percent_prompt(self):
        """Edge case: leading % (zsh default prompt)."""
        raw = "% ls -la\nList all files"
        cmd, desc = sanitize_response(raw)
        assert cmd == "ls -la"
        assert desc == "List all files"


class TestParseResponseJSON:
    """Tests for parse_response with JSON input."""

    def test_valid_json(self):
        """Expected use: clean JSON response."""
        raw = '{"command": "ls -la", "description": "List all files"}'
        result = parse_response(raw)
        assert result == LLMResponse("ls -la", "List all files")

    def test_json_with_fences(self):
        """Edge case: JSON wrapped in markdown code fences."""
        raw = '```json\n{"command": "ls", "description": "List"}\n```'
        result = parse_response(raw)
        assert result == LLMResponse("ls", "List")

    def test_json_missing_command(self):
        """Failure case: JSON missing the command field."""
        with pytest.raises(SanitizeError, match="empty or missing"):
            parse_response('{"description": "oops"}')

    def test_json_empty_command(self):
        """Failure case: JSON with empty command string."""
        with pytest.raises(SanitizeError, match="empty or missing"):
            parse_response('{"command": "", "description": "..."}')

    def test_json_extra_fields_ignored(self):
        """Edge case: extra fields in JSON are silently ignored."""
        raw = '{"command": "ls", "description": "List", "extra": true}'
        result = parse_response(raw)
        assert result == LLMResponse("ls", "List")

    def test_json_command_has_backticks(self):
        """Edge case: backticks in JSON command value are stripped."""
        raw = '{"command": "`ls -la`", "description": "List"}'
        result = parse_response(raw)
        assert result.command == "ls -la"

    def test_json_whitespace_only_command(self):
        """Failure case: command is only whitespace."""
        with pytest.raises(SanitizeError, match="empty or missing"):
            parse_response('{"command": "   ", "description": "..."}')


class TestParseResponseFallback:
    """Tests for parse_response falling back to text parser."""

    def test_fallback_plain_text(self):
        """Expected use: plain text falls back to legacy parser."""
        raw = "ls -la\nList all files"
        result = parse_response(raw)
        assert result == LLMResponse("ls -la", "List all files")

    def test_fallback_with_fences(self):
        """Edge case: non-JSON fenced text falls back."""
        raw = "```\nls -la\nList\n```"
        result = parse_response(raw)
        assert result == LLMResponse("ls -la", "List")

    def test_fallback_empty(self):
        """Failure case: empty input raises SanitizeError."""
        with pytest.raises(SanitizeError, match="Empty response"):
            parse_response("")

    def test_fallback_none(self):
        """Failure case: None input raises SanitizeError."""
        with pytest.raises(SanitizeError, match="Empty response"):
            parse_response(None)
