#!/usr/bin/env bash
# Integration tests for fish shell init script.
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
init_output=$(at-cmd init fish)
assert "init script generates successfully" test -n "$init_output"
assert_output "contains header comment" "at-cmd init fish" "$init_output"
assert_output "contains default_mode" "default_mode:" "$init_output"

# ── Test 2: init script is valid fish syntax ─────────────────────

echo "--- Syntax validation ---"
tmpfile=$(mktemp /tmp/at-cmd-fish-test.XXXXXX.fish)
echo "$init_output" > "$tmpfile"
# fish doesn't have -n flag; use --no-execute for syntax check
assert "init script parses without syntax errors" fish --no-execute "$tmpfile"
rm -f "$tmpfile"

# ── Test 3: functions are defined after sourcing ─────────────────

echo "--- Function definitions ---"

check_fn() {
    local fn="$1"
    fish -c "
        at-cmd init fish | source
        functions -q $fn
    " 2>/dev/null
}

assert "defines _at_cmd_submit" check_fn _at_cmd_submit
assert "defines _at_cmd_inline" check_fn _at_cmd_inline
assert "defines _at_cmd_undo"   check_fn _at_cmd_undo

# ── Test 4: submit function validates args ───────────────────────

echo "--- Submit function behavior ---"
no_args_out=$(fish -c '
    at-cmd init fish | source
    _at_cmd_submit 2>&1
' 2>&1) || true
assert_output "submit with no args shows error" "at-cmd failed" "$no_args_out"

# ── Test 5: both modes generate valid scripts ────────────────────

echo "--- Mode variants ---"
for mode in inline submit; do
    mode_out=$(AT_CMD_DEFAULT_MODE="$mode" at-cmd init fish)
    tmpfile=$(mktemp /tmp/at-cmd-fish-mode.XXXXXX.fish)
    echo "$mode_out" > "$tmpfile"
    assert "$mode mode generates valid syntax" fish --no-execute "$tmpfile"
    assert_output "$mode mode annotates mode" "default_mode: $mode" "$mode_out"
    rm -f "$tmpfile"
done

# ── Test 6: inline mode defines enter handler ────────────────────

echo "--- Inline mode specifics ---"
inline_out=$(AT_CMD_DEFAULT_MODE=inline at-cmd init fish)
assert_output "inline mode defines _at_cmd_enter" "function _at_cmd_enter" "$inline_out"
assert_output "inline mode binds Enter" 'bind \r _at_cmd_enter' "$inline_out"

# ── Test 7: submit mode defines @ function ───────────────────────

echo "--- Submit mode specifics ---"
submit_out=$(AT_CMD_DEFAULT_MODE=submit at-cmd init fish)
assert_output "submit mode defines @ function" 'function @' "$submit_out"

# ── Test 8: fish-specific features ───────────────────────────────

echo "--- Fish-specific features ---"
assert_output "uses commandline builtin" "commandline" "$init_output"
assert_output "uses history append" "history append" "$init_output"
assert_output "uses string match" "string match" "$init_output"

# ── Summary ──────────────────────────────────────────────────────

printf "\n  fish: %d passed, %d failed\n" "$PASS" "$FAIL"
exit "$FAIL"
