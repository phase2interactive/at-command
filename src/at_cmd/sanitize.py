"""Sanitize and parse LLM output into structured responses."""

import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class SanitizeError(Exception):
    """Raised when LLM output cannot be parsed into a valid command."""


@dataclass(frozen=True)
class LLMResponse:
    """Parsed response from the LLM backend.

    Attributes:
        command: The translated shell command.
        description: Brief description of what the command does.
    """

    command: str
    description: str


def parse_response(raw: str) -> LLMResponse:
    """Parse a JSON LLM response into an LLMResponse.

    Tries JSON parsing first. Falls back to the legacy 2-line
    text parser for robustness (LLMs sometimes ignore JSON instructions).

    Args:
        raw: Raw text from the LLM backend.

    Returns:
        LLMResponse with command and description.

    Raises:
        SanitizeError: If neither JSON nor text parsing succeeds.
    """
    if not raw or not raw.strip():
        raise SanitizeError("Empty response from LLM")

    text = raw.strip()

    # Strip markdown code fences that may wrap JSON
    text = re.sub(r"^```[a-zA-Z]*\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()

    # Attempt JSON parsing first
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            command = data.get("command")
            description = data.get("description", "")

            if not command or not isinstance(command, str) or not command.strip():
                raise SanitizeError("JSON response has empty or missing 'command' field")

            if not isinstance(description, str):
                description = str(description)

            command = _clean_command(command)
            if not command:
                raise SanitizeError("Command is empty after sanitization")

            return LLMResponse(command=command, description=description.strip())
    except (json.JSONDecodeError, TypeError):
        pass

    # Fall back to legacy 2-line text parser
    logger.warning("LLM did not return valid JSON; falling back to text parser")
    command, description = sanitize_response(raw)
    return LLMResponse(command=command, description=description)


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
