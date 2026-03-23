"""Sanitize LLM output into (command, description) tuples."""

import re


class SanitizeError(Exception):
    """Raised when LLM output cannot be parsed into a valid command."""


def sanitize_response(raw: str) -> tuple[str, str]:
    """Clean LLM output and extract command + description.

    Args:
        raw: Raw text from the LLM backend.

    Returns:
        tuple[str, str]: (command, description) pair.

    Raises:
        SanitizeError: If the input is empty or yields no command.
    """
    if not raw or not raw.strip():
        raise SanitizeError("Empty response from LLM")

    text = raw.strip()

    # Strip markdown code fences
    text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)

    lines = [line for line in text.splitlines() if line.strip()]

    if not lines:
        raise SanitizeError("No usable content in LLM response")

    command = _clean_command(lines[0])
    description = lines[1].strip() if len(lines) > 1 else ""

    if not command:
        raise SanitizeError("Command line is empty after sanitization")

    return command, description


def _clean_command(line: str) -> str:
    """Strip shell prompt artifacts and backticks from a command line.

    Args:
        line: A single line of text.

    Returns:
        str: The cleaned command string.
    """
    text = line.strip()

    # Remove surrounding backticks
    if text.startswith("`") and text.endswith("`"):
        text = text[1:-1].strip()

    # Remove leading shell prompt characters: $, >, #, %
    text = re.sub(r"^[$>#%]\s*", "", text)

    return text.strip()
