#!/usr/bin/env bash
# Integration tests for zsh shell init script.
set -euo pipefail

PASS=0
FAIL=0

assert() {
    local desc="$1"
    shift
    if "$@" 2>/dev/null; then
        printf "  ✓ %s\n" "$desc"
        PASS=$((PASS + 1))
    else
        printf "  ✗ %s\n" "$desc"
        FAIL=$((FAIL + 1))
    fi
}

assert_output() {
    local desc="$1"
    local expected="$2"
    local actual="$3"
    if [[ "$actual" == *"$expected"* ]]; then
        printf "  ✓ %s\n" "$desc"
        PASS=$((PASS + 1))
    else
        printf "  ✗ %s (expected '%s', got '%s')\n" "$desc" "$expected" "$actual"
        FAIL=$((FAIL + 1))
    fi
}

# ── Test 1: init script generates without error ──────────────────

echo "--- Init script generation ---"
init_output=$(at-cmd init zsh)
assert "init script generates successfully" test -n "$init_output"
assert_output "contains header comment" "at-cmd init zsh" "$init_output"
assert_output "contains default_mode" "default_mode:" "$init_output"

# ── Test 2: init script is valid zsh syntax ──────────────────────

echo "--- Syntax validation ---"
# Write to a temp file so zsh -n can parse it
tmpfile=$(mktemp /tmp/at-cmd-zsh-test.XXXXXX)
echo "$init_output" > "$tmpfile"
assert "init script parses without syntax errors" zsh -n "$tmpfile"
rm -f "$tmpfile"

# ── Test 3: functions are defined after sourcing ─────────────────

echo "--- Function definitions ---"

check_fn() {
    local fn="$1"
    zsh -c "
        eval \"\$(at-cmd init zsh)\"
        whence -w $fn
    " >/dev/null 2>&1
}

assert "defines _at_cmd_submit" check_fn _at_cmd_submit
assert "defines _at_cmd_undo"   check_fn _at_cmd_undo
assert "defines at (function)"  check_fn at

# Note: _at_cmd_inline and _at_cmd_enter are ZLE widgets, registered via
# zle -N. They exist as functions but are meant to be invoked as widgets.
zsh_has_widget() {
    local widget="$1"
    zsh -c "
        eval \"\$(at-cmd init zsh)\"
        whence -w $widget
    " 2>/dev/null | grep -q "function"
}

assert "defines _at_cmd_inline (widget)" zsh_has_widget _at_cmd_inline

# ── Test 4: submit function validates args ───────────────────────

echo "--- Submit function behavior ---"
no_args_out=$(zsh -c '
    eval "$(at-cmd init zsh)"
    _at_cmd_submit 2>&1
' 2>&1) || true
assert_output "submit with no args shows usage" "Usage" "$no_args_out"

# ── Test 5: both modes generate valid scripts ────────────────────

echo "--- Mode variants ---"
for mode in inline submit; do
    mode_out=$(AT_CMD_DEFAULT_MODE="$mode" at-cmd init zsh)
    tmpfile=$(mktemp /tmp/at-cmd-zsh-mode.XXXXXX)
    echo "$mode_out" > "$tmpfile"
    assert "$mode mode generates valid syntax" zsh -n "$tmpfile"
    assert_output "$mode mode annotates mode" "default_mode: $mode" "$mode_out"
    rm -f "$tmpfile"
done

# ── Test 6: zsh-specific features ────────────────────────────────

echo "--- Zsh-specific features ---"
assert_output "uses print -z for history" "print -z" "$init_output"
assert_output "uses BUFFER variable" "BUFFER" "$init_output"
assert_output "uses zle redisplay" "zle redisplay" "$init_output"

# ── Summary ──────────────────────────────────────────────────────

printf "\n  zsh: %d passed, %d failed\n" "$PASS" "$FAIL"
exit "$FAIL"
