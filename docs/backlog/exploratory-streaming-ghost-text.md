# Streaming Ghost Text Preview

**Status:** Draft
**Date:** 2026-03-23
**Depends on:** Core translate pipeline (`llm.py`, `sanitize.py`, `init.py`, `spinner.py`)

---

## Overview

Today, `at-cmd` inline mode follows a block-wait pattern: the shell integration clears the buffer, invokes `at-cmd --json`, waits for the full response, then replaces the buffer with the finished command. During the wait the user sees nothing but a spinner on stderr, with no indication of whether the LLM is producing useful output.

Streaming Ghost Text replaces that dead time with a live, character-by-character preview of the command as the LLM generates it. The in-progress text renders in dim (ANSI SGR 2) style to signal "not yet final." When generation completes, the text transitions to full brightness and becomes editable. Users can cancel mid-stream to discard, or accept partial output early.

## Motivation

- **Perceived latency drops dramatically.** Even if wall-clock time is identical, watching text appear feels faster than staring at a spinner.
- **Early validation.** If the LLM starts with the wrong tool (`docker` when the user meant `podman`), the user can cancel within the first few tokens instead of waiting 2-3 seconds.
- **Parity with modern AI UX.** Copilot, ChatGPT, and Claude all stream responses. A terminal tool should too.

---

## User Stories

| ID | Story |
|----|-------|
| US-1 | As a user in inline mode, I want to see the command appear token-by-token in dim text so I can gauge accuracy before it finishes. |
| US-2 | As a user, I want to press Escape (or Ctrl+C) mid-stream to cancel generation and restore my original `@ ...` input. |
| US-3 | As a user, I want to press Enter mid-stream to accept whatever has been generated so far and immediately edit or run it. |
| US-4 | As a user in submit mode, I want to see the command stream into the editable prompt area so I know the system is working. |
| US-5 | As a user on a slow backend (large local model), streaming is especially valuable -- I need visual feedback that generation has started. |
| US-6 | As a user whose terminal does not support dim/italic, I want the feature to degrade gracefully with no visual corruption. |

---

## Detailed UX

### Inline Mode (Primary Target)

```
$ @ find large jpg files        <-- user types, then presses hotkey
$ find . -name '*.jpg' -si      <-- dim text streams in, cursor hidden
$ find . -name '*.jpg' -size +5M  <-- still dim, generation complete
$ find . -name '*.jpg' -size +5M  <-- transitions to full brightness, cursor at end
  # Find JPG files larger than 5MB  <-- dim description appears below
```

**Rendering states:**

| State | Buffer content | ANSI style | Cursor | User actions |
|-------|---------------|------------|--------|-------------|
| Idle | `@ find large jpg files` | Normal | Visible, editable | Press hotkey to trigger |
| Streaming | Partial command, growing | Dim (`\e[2m`) | Hidden | Escape = cancel, Enter = accept partial |
| Complete | Full command | Normal (full brightness) | Visible, at end of line | Edit, Enter = run, Undo = restore |
| Cancelled | Original `@ ...` input restored | Normal | Visible | Re-trigger or edit |

**State transitions:**

```
Idle --(hotkey)--> Streaming
Streaming --(LLM done)--> Complete
Streaming --(Escape/Ctrl+C)--> Cancelled (restore original buffer)
Streaming --(Enter)--> Complete (accept partial, stop generation)
Complete --(Undo key)--> Idle (restore original buffer)
Complete --(Enter)--> Execute
```

### Submit Mode

In submit mode, streaming replaces the spinner. The command streams into a preview area on stderr, then transfers to the editable `readline` prompt:

```
$ @ find large jpg files
  find . -name '*.jpg' -size +5M   <-- dim text streams on stderr
  # Find JPG files larger than 5MB
> find . -name '*.jpg' -size +5M   <-- full brightness, editable prompt
```

Cancel (Ctrl+C) during streaming aborts the entire operation, same as today.

### Description Line

The description (line 2 of the LLM response) is not streamed. It appears only after generation completes, rendered as dim text below the command, matching current behavior. This avoids confusion from streaming two conceptually separate lines.

---

## Streaming Support Per Backend

All three backends support streaming. The implementation adds a `StreamingBackendFn` protocol alongside the existing `BackendFn`.

### Claude CLI

The `claude` CLI supports `--output-format stream-json`, which emits newline-delimited JSON objects to stdout as tokens arrive:

```bash
claude -p --model sonnet --output-format stream-json "prompt"
```

Each line is a JSON object. Content chunks have a `type` field indicating the event kind. The streaming adapter reads `subprocess.Popen` stdout line by line, parses each JSON object, extracts text deltas, and yields them.

```python
def _claude_streaming_backend(config: Config) -> StreamingBackendFn:
    def stream(system_prompt: str, user_prompt: str) -> Iterator[str]:
        proc = subprocess.Popen(
            ["claude", "-p", "--model", config.model, "--output-format", "stream-json"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        proc.stdin.write(f"{system_prompt}\n\nUser request: {user_prompt}")
        proc.stdin.close()
        for line in proc.stdout:
            chunk = json.loads(line)
            if delta := _extract_claude_delta(chunk):
                yield delta
    return stream
```

### Ollama (HTTP Streaming)

Ollama streams by default when `"stream": true` (or omitted). The `/api/generate` endpoint returns newline-delimited JSON, each object containing a `"response"` field with the text delta:

```python
def _ollama_streaming_backend(config: Config) -> StreamingBackendFn:
    base_url = config.api_url or "http://localhost:11434"
    def stream(system_prompt: str, user_prompt: str) -> Iterator[str]:
        with httpx.stream(
            "POST",
            f"{base_url}/api/generate",
            json={"model": config.model, "system": system_prompt,
                  "prompt": user_prompt, "stream": True},
            timeout=config.timeout,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                chunk = json.loads(line)
                if text := chunk.get("response", ""):
                    yield text
    return stream
```

### OpenAI (SSE Streaming)

The OpenAI API uses Server-Sent Events (SSE) with `"stream": true`. Each `data:` line contains a JSON object with `choices[0].delta.content`:

```python
def _openai_streaming_backend(config: Config) -> StreamingBackendFn:
    base_url = config.api_url or "https://api.openai.com/v1"
    def stream(system_prompt: str, user_prompt: str) -> Iterator[str]:
        with httpx.stream(
            "POST",
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {config.api_key}",
                     "Content-Type": "application/json"},
            json={"model": config.model, "stream": True,
                  "messages": [
                      {"role": "system", "content": system_prompt},
                      {"role": "user", "content": user_prompt},
                  ]},
            timeout=config.timeout,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                chunk = json.loads(line.removeprefix("data: "))
                if delta := chunk["choices"][0]["delta"].get("content", ""):
                    yield delta
    return stream
```

### Fallback

If streaming is unavailable (network proxy strips SSE, future backend without streaming), the system falls back to block-wait mode with the existing spinner. The config can also force this: `streaming = false` in `config.toml` or `AT_CMD_STREAMING=false`.

---

## Terminal Rendering Approach

### ANSI Escape Sequences Used

| Sequence | Purpose |
|----------|---------|
| `\e[2m` | Dim (faint) -- ghost text while streaming |
| `\e[3m` | Italic -- optional additional ghost signal (not all terminals support this) |
| `\e[0m` | Reset all attributes |
| `\e[?25l` | Hide cursor (during streaming) |
| `\e[?25h` | Show cursor (after streaming completes) |
| `\r` | Carriage return (return to start of line) |
| `\e[K` | Erase from cursor to end of line |
| `\e[A` | Move cursor up one line (for multi-line cleanup) |

### Cursor Management

During streaming, the cursor is hidden (`\e[?25l`) to prevent flickering. After each token:

1. Carriage return to the start of the prompt area.
2. Erase the line (`\e[K`).
3. Write the accumulated text in dim style.
4. Flush stderr/stdout.

When generation completes or the user accepts:

1. Carriage return, erase line.
2. Rewrite the full command in normal (bright) style.
3. Show cursor (`\e[?25h`).
4. Position cursor at end of command.

### Line Clearing

In inline mode, the shell buffer is the target. The Python process communicates with the shell integration via stdout (JSON or raw text). The shell script handles the actual buffer manipulation via `READLINE_LINE` (bash), `BUFFER` (zsh), or `commandline -r` (fish).

In submit mode, all rendering happens on stderr (preview area) and then the final command is handed to the readline prompt, so cursor management is simpler.

---

## Shell Integration Changes

### Current Approach (Block-Wait)

The shell integration calls `at-cmd --json` as a subcommand substitution, waits for it to exit, then parses the JSON result and sets the buffer. This is fundamentally incompatible with streaming because subcommand substitution (`$(...)`) blocks until the process exits.

### New Approach (Streaming Pipe)

For inline mode with streaming, the shell integration changes to a read-loop pattern. The Python CLI writes incremental JSON events to stdout, one per line:

```json
{"event": "delta", "text": "find "}
{"event": "delta", "text": ". -name "}
{"event": "delta", "text": "'*.jpg'"}
{"event": "done", "command": "find . -name '*.jpg' -size +5M", "description": "Find JPG files larger than 5MB"}
```

The `--stream` flag triggers this mode: `at-cmd --stream --shell zsh "find large jpg files"`.

#### Zsh Example

```zsh
_at_cmd_inline_stream() {
    local buf="$BUFFER"
    [[ "$buf" != @\ * ]] && return
    _at_original_buf="$buf"
    BUFFER=""; CURSOR=0; zle redisplay

    local accumulated=""
    at-cmd --stream --shell zsh "${buf#@ }" 2>/dev/null | while IFS= read -r line; do
        local event=$(echo "$line" | jq -r '.event')
        if [[ "$event" == "delta" ]]; then
            accumulated+=$(echo "$line" | jq -r '.text')
            BUFFER="$accumulated"
            CURSOR=${#BUFFER}
            zle redisplay
        elif [[ "$event" == "done" ]]; then
            BUFFER=$(echo "$line" | jq -r '.command')
            CURSOR=${#BUFFER}
            local desc=$(echo "$line" | jq -r '.description')
            [[ -n "$desc" ]] && printf '\n  \e[2m# %s\e[0m' "$desc" >&2
            zle redisplay
        fi
    done

    # If pipe broke (cancel), restore
    if [[ -z "$BUFFER" ]]; then
        BUFFER="$_at_original_buf"
        CURSOR=${#BUFFER}
        zle redisplay
    fi
}
```

#### Cancel (Escape/Ctrl+C)

When the user presses Escape or Ctrl+C during streaming, the shell kills the `at-cmd` process (SIGPIPE or SIGINT). The shell integration detects the abnormal exit and restores the original buffer. The Python CLI installs a SIGINT handler that cleanly closes the streaming connection.

#### Accept Partial (Enter)

When the user presses Enter mid-stream, the shell integration:

1. Kills the `at-cmd` streaming process.
2. Takes whatever is currently in the buffer as the final command.
3. Transitions to the normal editable state.

This requires the shell read-loop to be interruptible by keybindings. In zsh, this is achievable because `zle` widgets can preempt each other. In bash and fish, this is harder and may require the streaming process to run in a background coprocess.

#### Bash Considerations

Bash `bind -x` does not support async buffer updates natively. The approach here uses a coprocess:

```bash
_at_cmd_inline_stream() {
    local buf="$READLINE_LINE"
    [[ "$buf" != @\ * ]] && return
    _at_original_buf="$buf"
    coproc AT_STREAM { at-cmd --stream --shell bash "${buf#@ }" 2>/dev/null; }
    while IFS= read -r line <&${AT_STREAM[0]}; do
        local event=$(echo "$line" | jq -r '.event')
        if [[ "$event" == "delta" ]]; then
            _at_accumulated+=$(echo "$line" | jq -r '.text')
            READLINE_LINE="$_at_accumulated"
            READLINE_POINT=${#READLINE_LINE}
        elif [[ "$event" == "done" ]]; then
            READLINE_LINE=$(echo "$line" | jq -r '.command')
            READLINE_POINT=${#READLINE_LINE}
        fi
    done
}
```

**Known limitation:** Bash does not repaint the prompt during `bind -x` execution. The buffer updates only become visible after the function returns. This means bash may need to fall back to the block-wait approach or use an alternative rendering strategy (direct terminal writes to stderr with the ghost text rendered outside the readline buffer).

#### Fish Considerations

Fish supports `commandline -r` inside event handlers and key bindings. However, fish key binding functions are synchronous. The streaming approach requires either:

- A background job with periodic `commandline -r` updates via `fish_postexec` or a timer event.
- Falling back to block-wait in fish with a dim-text spinner showing partial output on stderr instead of in the buffer.

The recommended initial approach for fish is stderr-based ghost text (similar to submit mode) rather than true buffer streaming.

#### PowerShell Considerations

PSReadLine `ScriptBlock` handlers are synchronous. Streaming into the buffer requires `[Microsoft.PowerShell.PSConsoleReadLine]::Replace()` calls from within an async pipeline. This is possible but fragile. PowerShell will ship with block-wait initially and gain streaming in a later iteration.

---

## Technical Design

### New Modules and Protocols

#### `src/at_cmd/streaming.py` -- Streaming Adapter

```python
"""Streaming backend abstraction."""

from typing import Iterator, Protocol

class StreamingBackendFn(Protocol):
    """Callable protocol for streaming LLM backends."""
    def __call__(self, system_prompt: str, user_prompt: str) -> Iterator[str]: ...

class StreamEvent:
    """Typed event emitted during streaming."""
    pass

class DeltaEvent(StreamEvent):
    """A text chunk from the LLM."""
    def __init__(self, text: str) -> None:
        self.text = text

class DoneEvent(StreamEvent):
    """Generation complete."""
    def __init__(self, command: str, description: str) -> None:
        self.command = command
        self.description = description

class ErrorEvent(StreamEvent):
    """An error occurred during streaming."""
    def __init__(self, message: str) -> None:
        self.message = message
```

#### `src/at_cmd/ghost.py` -- Ghost Text Renderer

Handles writing streaming output to stdout (JSON event stream for shell integration) or stderr (submit mode preview).

```python
"""Ghost text rendering for streaming output."""

import json
import sys
from typing import Iterator

from at_cmd.streaming import StreamingBackendFn, DeltaEvent, DoneEvent
from at_cmd.sanitize import sanitize_response

def stream_json_events(
    stream_fn: StreamingBackendFn,
    system_prompt: str,
    user_prompt: str,
) -> None:
    """Write newline-delimited JSON events to stdout for shell consumption."""
    accumulated = ""
    for chunk in stream_fn(system_prompt, user_prompt):
        accumulated += chunk
        event = {"event": "delta", "text": chunk}
        sys.stdout.write(json.dumps(event) + "\n")
        sys.stdout.flush()

    command, description = sanitize_response(accumulated)
    done = {"event": "done", "command": command, "description": description}
    sys.stdout.write(json.dumps(done) + "\n")
    sys.stdout.flush()

def stream_stderr_preview(
    stream_fn: StreamingBackendFn,
    system_prompt: str,
    user_prompt: str,
) -> tuple[str, str]:
    """Stream ghost text to stderr, return final (command, description)."""
    accumulated = ""
    sys.stderr.write("\033[?25l")  # hide cursor
    for chunk in stream_fn(system_prompt, user_prompt):
        accumulated += chunk
        # Render accumulated text in dim on stderr
        sys.stderr.write(f"\r\033[K  \033[2m{accumulated}\033[0m")
        sys.stderr.flush()

    sys.stderr.write("\033[?25h")  # show cursor
    sys.stderr.write("\r\033[K")   # clear preview line
    sys.stderr.flush()

    return sanitize_response(accumulated)
```

### Changes to Existing Modules

#### `llm.py`

Add a `get_streaming_backend()` function that returns a `StreamingBackendFn` for each backend. The existing `get_backend()` remains unchanged for backward compatibility.

```python
def get_streaming_backend(config: Config) -> StreamingBackendFn | None:
    """Get a streaming backend, or None if streaming is not supported."""
    streaming_backends = {
        "claude": _claude_streaming_backend,
        "ollama": _ollama_streaming_backend,
        "openai": _openai_streaming_backend,
    }
    factory = streaming_backends.get(config.backend)
    if not factory:
        return None
    return factory(config)
```

#### `config.py`

Add a `streaming` field to `Config`:

```python
@dataclass
class Config:
    # ... existing fields ...
    streaming: bool = True
```

Supported via `AT_CMD_STREAMING` env var and `streaming = true/false` in `config.toml`.

#### `cli.py`

Add a `--stream` flag to the `translate` command. When present, the CLI uses the streaming backend and emits JSON events to stdout instead of waiting for the full response:

```python
@click.option("--stream", "stream_mode", is_flag=True, help="Stream output as JSON events.")
```

If `--stream` is set and the backend supports streaming, use `stream_json_events()`. If `--stream` is set but the backend does not support streaming, fall back to block-wait and emit a single `done` event at the end (transparent to the shell integration).

In submit mode (no `--stream` flag), if `config.streaming` is true, use `stream_stderr_preview()` instead of the spinner.

#### `spinner.py`

No changes. The spinner remains the fallback for non-streaming mode.

#### `init.py`

Each shell generator gains a streaming variant of `_inline`. The generator checks `config.streaming` and emits the appropriate shell function. When streaming is disabled, the existing block-wait functions are emitted unchanged.

---

## Edge Cases

### Terminal Does Not Support Dim/Italic

Some terminals (older xterm, raw serial consoles, screen without 256-color) ignore `\e[2m` or render it identically to normal text. This is acceptable -- the ghost text simply appears at full brightness during streaming, which is still better than a blank screen. No detection or fallback is needed because unsupported SGR codes are silently ignored per ECMA-48.

For `\e[3m` (italic), support is patchier. Italic is optional styling on top of dim and should not be relied upon. The implementation uses dim only by default, with italic as an opt-in config flag (`ghost_style = "dim"` vs `ghost_style = "dim+italic"`).

### Multi-Line Commands

The LLM contract specifies single-line commands. However, some valid commands span multiple lines (e.g., `find ... \` continuations or heredocs). During streaming:

- If a newline appears before the LLM emits line 2 (the description), it could be a continuation character. The renderer accumulates text including newlines.
- Multi-line ghost text requires clearing multiple terminal lines on each redraw. Track the number of lines written and issue `\e[A` (cursor up) + `\e[K` (erase line) for each line before redrawing.
- The `done` event always carries the sanitized single-line command (backslash-joined if needed).

### Very Fast Backends

If the backend returns the entire response in under ~50ms (cached response, very fast local model), the ghost text phase is barely visible. This is fine -- the UX is indistinguishable from the current block-wait but without the spinner flash. No artificial delay should be added.

### Very Slow Backends

For backends that take 10+ seconds (large local models, overloaded APIs), streaming is the primary value. The first token provides "generation has started" feedback. If no tokens arrive within the configured timeout, the streaming connection closes and the CLI reports an error, same as today.

### Token-Level vs. Line-Level Buffering

Some backends (especially `claude` CLI with `--output-format stream-json`) may buffer output at the OS pipe level, causing tokens to arrive in bursts rather than individually. The renderer handles this gracefully -- each burst simply causes a larger visual jump. No special handling is needed.

### Partial Output Contains Markdown/Backticks

During streaming, partial output is rendered raw (not sanitized) because `sanitize_response()` operates on complete text. Backticks or markdown fences may briefly appear in the ghost text. This is acceptable because:

1. Ghost text is dim and provisional.
2. The `done` event carries the sanitized command.
3. The LLM prompt explicitly requests no markdown, so artifacts are rare.

### SIGPIPE Handling

When the user cancels mid-stream, the shell kills the `at-cmd` process. Writing to a closed stdout raises `BrokenPipeError`. The CLI must catch this and exit cleanly (no traceback):

```python
try:
    stream_json_events(...)
except BrokenPipeError:
    sys.exit(0)
```

### Terminal Resize During Streaming

If the terminal is resized while ghost text is being rendered, the line-clearing logic may leave artifacts. A SIGWINCH handler can trigger a full redraw of the current ghost text. This is a low-priority edge case -- most users do not resize their terminal mid-command.

---

## Testing Strategy

### Unit Tests

| Test | Module | Description |
|------|--------|-------------|
| `test_streaming_ollama_yields_deltas` | `test_streaming.py` | Mock `httpx.stream` to return chunked responses, verify `Iterator[str]` yields correct deltas. |
| `test_streaming_openai_parses_sse` | `test_streaming.py` | Feed synthetic SSE lines, verify delta extraction including `data: [DONE]` termination. |
| `test_streaming_claude_parses_json` | `test_streaming.py` | Feed synthetic `stream-json` lines to mock Popen stdout, verify delta extraction. |
| `test_ghost_json_events` | `test_ghost.py` | Capture stdout from `stream_json_events()`, verify well-formed NDJSON with correct event types. |
| `test_ghost_stderr_preview` | `test_ghost.py` | Capture stderr from `stream_stderr_preview()`, verify ANSI codes and final return value. |
| `test_stream_fallback_to_block` | `test_streaming.py` | When streaming backend returns None, verify the CLI falls back to the non-streaming path. |
| `test_stream_cancel_sigpipe` | `test_ghost.py` | Simulate BrokenPipeError during `stream_json_events()`, verify clean exit. |
| `test_config_streaming_flag` | `test_config.py` | Verify `streaming = false` in config.toml and `AT_CMD_STREAMING=false` both disable streaming. |
| `test_sanitize_on_partial` | `test_ghost.py` | Verify that `sanitize_response()` is called only on the complete accumulated text, not on partial deltas. |

### Integration Tests

| Test | Description |
|------|-------------|
| `test_cli_stream_flag` | Run `at-cmd --stream --shell zsh "list files"` with a mock backend, verify stdout contains NDJSON events. |
| `test_cli_submit_streaming` | Run `at-cmd "list files"` with `streaming=true` and a mock backend, verify stderr contains dim ANSI text. |

### Manual Testing Checklist

- [ ] Zsh inline mode: ghost text streams into buffer, transitions to editable on completion.
- [ ] Zsh inline mode: Escape mid-stream restores original buffer.
- [ ] Zsh inline mode: Undo after completion restores original buffer.
- [ ] Bash inline mode: verify fallback behavior is acceptable.
- [ ] Fish inline mode: verify stderr-based ghost text displays correctly.
- [ ] Submit mode: ghost text streams on stderr, then appears in editable prompt.
- [ ] `streaming = false` in config: verify block-wait with spinner is used.
- [ ] Each backend (claude, ollama, openai) streams correctly.
- [ ] Terminal without dim support (e.g., `TERM=dumb`): no visual corruption.
- [ ] Very fast response: no flickering or artifacts.
- [ ] Slow response (10+ seconds): first token appears, timeout works.

---

## Out of Scope

The following are explicitly excluded from this feature and may be addressed in future work:

- **Multi-candidate streaming.** Streaming multiple alternative commands simultaneously (e.g., side-by-side) is a separate feature.
- **Description streaming.** Only the command (line 1) is streamed. The description (line 2) appears after generation completes.
- **Syntax highlighting of ghost text.** Ghost text is rendered in a single dim style. Syntax-aware coloring (e.g., highlighting pipes, flags) is a future enhancement.
- **Ghost text in non-terminal contexts.** IDE terminal emulators, tmux/screen compatibility testing, and SSH-forwarded terminals are not in scope for the initial implementation, though the ANSI approach should work in most cases.
- **Streaming for the `config` TUI.** The Textual-based config editor does not use streaming.
- **Token counting or cost display during streaming.** Displaying token usage or estimated cost as tokens arrive is a separate feature.
- **Caching integration.** If a future caching layer is added, cached responses should bypass streaming entirely and return instantly. That integration is deferred.
- **Windows Terminal / cmd.exe support.** PowerShell is the only Windows target. cmd.exe is not supported.

---

## Configuration Summary

| Config key | Env var | Default | Description |
|-----------|---------|---------|-------------|
| `streaming` | `AT_CMD_STREAMING` | `true` | Enable streaming ghost text. Set to `false` to use block-wait with spinner. |
| `ghost_style` | `AT_CMD_GHOST_STYLE` | `"dim"` | ANSI style for ghost text. Options: `"dim"`, `"dim+italic"`. |

---

## Rollout Plan

1. **Phase 1: Backend streaming adapters.** Add `StreamingBackendFn` and streaming factories for all three backends. Unit test with mocked HTTP/subprocess. No UX changes yet.
2. **Phase 2: Submit mode ghost text.** Replace the spinner with `stream_stderr_preview()` in submit mode. Low risk -- stderr rendering does not touch shell buffers.
3. **Phase 3: CLI `--stream` flag and JSON event protocol.** Add the `--stream` flag that emits NDJSON events to stdout. Test with `at-cmd --stream "list files" | cat`.
4. **Phase 4: Zsh inline streaming.** Update the zsh shell integration to use the streaming read-loop. This is the highest-value, highest-risk change.
5. **Phase 5: Bash and fish.** Implement bash coprocess approach and fish stderr-based preview. Evaluate whether true buffer streaming is feasible in bash.
6. **Phase 6: PowerShell.** Add PSReadLine streaming if feasible, otherwise leave as block-wait.
