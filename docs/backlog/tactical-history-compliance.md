# Shell History Compliance (NF3)

**Status:** Proposed
**Date:** 2026-03-23
**Priority:** Medium
**Spec Ref:** NF3 (line 128)

## Problem

The spec states: "The implementation MUST NOT modify shell history with synthetic entries" (NF3).

The current shell integration scripts explicitly add the confirmed command to history:

- **Fish**: `history append -- "$final_cmd"` (`init.py:57`)
- **Bash**: `history -s "$_final"` (`init.py:146`)
- **PowerShell**: `[Microsoft.PowerShell.PSConsoleReadLine]::AddToHistory($edited)` (`init.py:283`)
- **Zsh**: Uses `print -z` which pushes to the edit buffer, not history — compliant

## Decision Needed

This is a spec-vs-UX tension. The history additions exist so the user can press Up to recall and re-run translated commands, which is good UX. The spec's intent is to prevent *unreviewed* commands from polluting history.

### Option A: Remove history writes (spec-compliant)

Remove `history append`, `history -s`, and `AddToHistory` calls. The user's confirmed command will not appear in history. Simple but reduces usability.

### Option B: Update the spec

Change NF3 to: "The implementation MUST NOT add *unconfirmed* commands to shell history. Commands the user explicitly executes MAY be added."

This reflects the actual intent and preserves the useful behavior.

### Option C: Make it configurable

Add a `history = true|false` config option (default `true`). Users who care about history purity can opt out.

## Recommendation

**Option B** — update the spec. The current behavior is what users expect: if they ran a command, it should be in history. The spec language is overly broad.
