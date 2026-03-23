# Description Line Sanitization

**Status:** Proposed
**Date:** 2026-03-23
**Priority:** High
**Spec Ref:** Security (line 165), LLM Output Contract (line 82)

## Problem

When displaying the description, `cli.py:136` prepends `# `:

```python
click.echo(f"  \033[2m# {description}\033[0m", err=True)
```

The shell integration scripts do the same (`printf '  \e[2m# %s\e[0m\n' "$desc"`).

But `sanitize.py` does not strip a leading `#` from the description line. If the LLM returns:

```
find . -name '*.py' -mtime -7
# Find Python files modified in the last 7 days
```

The displayed output becomes:

```
  # # Find Python files modified in the last 7 days
```

## Proposed Fix

In `sanitize.py`, strip a leading `#` (and optional space) from the description line:

```python
description = lines[1].strip() if len(lines) > 1 else ""
# Strip leading comment marker — display code adds its own
description = re.sub(r"^#\s*", "", description)
```

This is a small, safe change that should be done alongside the existing sanitization logic.
