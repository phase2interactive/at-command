# Available Tools Context

**Status:** Proposed
**Date:** 2026-03-23
**Priority:** Medium
**Spec Ref:** LLM Request Contract, Input (line 78)

## Problem

The spec lists "Available tools — Optionally, a list of installed CLI tools for better suggestions" as a system prompt input. The current implementation only sends shell, OS, and working directory.

Without tool awareness, the LLM may suggest commands using tools that aren't installed (e.g., `fd` instead of `find`, `rg` instead of `grep`, `bat` instead of `cat`).

## Proposed Design

### Detection

Probe for a curated list of common CLI tools at init time:

```python
TOOL_PROBES = [
    "fd", "rg", "bat", "eza", "jq", "yq", "fzf", "git", "docker",
    "kubectl", "aws", "gcloud", "az", "terraform", "curl", "wget",
    "htop", "tmux", "sed", "awk", "perl", "python3", "node",
]

def detect_tools() -> list[str]:
    return [t for t in TOOL_PROBES if shutil.which(t)]
```

### System Prompt Addition

Append to the system prompt:

```
Available CLI tools: fd, rg, jq, fzf, git, docker, curl, python3
Prefer these over alternatives when applicable.
```

### Caching

Tool availability rarely changes within a session. Cache the result for the lifetime of the process (already single-shot, so this is free). For the shell integration scripts, the `at-cmd init` output could bake in a snapshot, or each `at-cmd --json` call could detect on the fly (adds ~10ms).

## Config

Add `detect_tools = true` (default) to config. Users can disable if they want minimal prompts or faster startup.

## Considerations

- Sending a tool list increases prompt size slightly (~50 tokens)
- The LLM may over-index on listed tools — prompt wording matters
- Could be extended to include tool versions (`git 2.43`, `python 3.12`) for version-aware suggestions
