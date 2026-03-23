"""LLM backend abstraction and system prompt builder."""

import json
import shutil
import subprocess
from typing import Protocol

import httpx

from at_cmd.config import Config
from at_cmd.detect import ShellContext


class BackendError(Exception):
    """Raised when the LLM backend fails."""


class BackendFn(Protocol):
    """Callable protocol for LLM backends."""

    def __call__(self, system_prompt: str, user_prompt: str) -> str: ...


def build_system_prompt(ctx: ShellContext) -> str:
    """Build the system prompt from shell context.

    Args:
        ctx: Detected shell context.

    Returns:
        str: System prompt for the LLM.
    """
    return (
        f"You are a shell command translator for {ctx.shell} on {ctx.os_name}.\n"
        f"Working directory: {ctx.cwd}\n"
        f"The user will describe what they want in natural language.\n"
        f"Return EXACTLY two lines:\n"
        f"Line 1: The {ctx.shell} command (no backticks, no markdown, one line, "
        f"use appropriate chaining for {ctx.shell})\n"
        f"Line 2: A brief description (10 words max) of what the command does"
    )


def get_backend(config: Config) -> BackendFn:
    """Get the appropriate backend function for the configured backend.

    Args:
        config: Resolved configuration.

    Returns:
        BackendFn: Callable that takes (system_prompt, user_prompt) and returns raw text.

    Raises:
        BackendError: If the backend is not available or not recognized.
    """
    backends = {
        "claude": _claude_backend,
        "ollama": _ollama_backend,
        "openai": _openai_backend,
    }

    factory = backends.get(config.backend)
    if not factory:
        raise BackendError(f"Unknown backend: {config.backend}")

    return factory(config)


def _claude_backend(config: Config) -> BackendFn:
    """Create a Claude CLI backend.

    Args:
        config: Resolved configuration.

    Returns:
        BackendFn: Backend function using the claude CLI.

    Raises:
        BackendError: If the claude CLI is not installed.
    """
    if not shutil.which("claude"):
        raise BackendError(
            "Claude CLI not found. Install it: https://docs.anthropic.com/claude-code"
        )

    def call(system_prompt: str, user_prompt: str) -> str:
        """Call Claude CLI with the given prompts.

        Args:
            system_prompt: System prompt for context.
            user_prompt: The user's natural language request.

        Returns:
            str: Raw LLM response text.

        Raises:
            BackendError: If the CLI invocation fails.
        """
        full_prompt = f"{system_prompt}\n\nUser request: {user_prompt}"
        result = subprocess.run(
            ["claude", "-p", "--model", config.model],
            input=full_prompt,
            capture_output=True,
            text=True,
            timeout=config.timeout,
        )
        if result.returncode != 0:
            raise BackendError(f"Claude CLI failed: {result.stderr.strip()}")
        return result.stdout

    return call


def _ollama_backend(config: Config) -> BackendFn:
    """Create an Ollama HTTP backend.

    Args:
        config: Resolved configuration.

    Returns:
        BackendFn: Backend function using the Ollama API.
    """
    base_url = config.api_url or "http://localhost:11434"

    def call(system_prompt: str, user_prompt: str) -> str:
        """Call Ollama API.

        Args:
            system_prompt: System prompt for context.
            user_prompt: The user's natural language request.

        Returns:
            str: Raw LLM response text.

        Raises:
            BackendError: If the HTTP request fails.
        """
        try:
            resp = httpx.post(
                f"{base_url}/api/generate",
                json={
                    "model": config.model,
                    "system": system_prompt,
                    "prompt": user_prompt,
                    "stream": False,
                },
                timeout=config.timeout,
            )
            resp.raise_for_status()
            return resp.json()["response"]
        except (httpx.HTTPError, KeyError) as e:
            raise BackendError(f"Ollama request failed: {e}") from e

    return call


def _openai_backend(config: Config) -> BackendFn:
    """Create an OpenAI-compatible HTTP backend.

    Args:
        config: Resolved configuration.

    Returns:
        BackendFn: Backend function using the OpenAI API.

    Raises:
        BackendError: If no API key is configured.
    """
    base_url = config.api_url or "https://api.openai.com/v1"
    if not config.api_key:
        raise BackendError("OpenAI backend requires AT_CMD_API_KEY or config api_key")

    def call(system_prompt: str, user_prompt: str) -> str:
        """Call OpenAI-compatible API.

        Args:
            system_prompt: System prompt for context.
            user_prompt: The user's natural language request.

        Returns:
            str: Raw LLM response text.

        Raises:
            BackendError: If the HTTP request fails.
        """
        try:
            resp = httpx.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=config.timeout,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError) as e:
            raise BackendError(f"OpenAI request failed: {e}") from e

    return call
