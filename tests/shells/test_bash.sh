#!/usr/bin/env bash
# Integration tests for bash shell init script.
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
init_output=$(at-cmd init bash)
assert "init script generates successfully" test -n "$init_output"
assert_output "contains header comment" "at-cmd init bash" "$init_output"
assert_output "contains default_mode" "default_mode:" "$init_output"

# ── Test 2: init script is valid bash syntax ─────────────────────

echo "--- Syntax validation ---"
assert "init script parses without syntax errors" bash -n <(echo "$init_output")

# ── Test 3: functions are defined after sourcing ─────────────────

echo "--- Function definitions ---"

# Source the init script and check each function exists
check_fn() {
    local fn="$1"
    bash -c "
        eval \"\$(at-cmd init bash)\"
        type $fn
    " >/dev/null 2>&1
}

assert "defines _at_cmd_submit" check_fn _at_cmd_submit
assert "defines _at_cmd_inline" check_fn _at_cmd_inline
assert "defines _at_cmd_undo"   check_fn _at_cmd_undo
assert "defines at (alias)"     check_fn at

# ── Test 4: submit function calls at-cmd --json ─────────────────

echo "--- Submit function behavior ---"

# Use mock-at-cmd by putting it first in PATH
submit_out=$(bash -c '
    # Replace at-cmd with mock for translate calls
    at-cmd() {
        if [[ "$1" == "init" ]]; then
            command at-cmd "$@"
        else
            mock-at-cmd "$@"
        fi
    }
    export -f at-cmd
    eval "$(command at-cmd init bash)"
    # Call submit non-interactively — capture the JSON path
    result=$(_at_cmd_submit "list files" 2>&1 <<< "")
    echo "$result"
' 2>&1) || true
# The submit function uses read -e which requires a tty, so we just verify
# the function can be invoked without crashing on missing args
no_args_out=$(bash -c '
    eval "$(at-cmd init bash)"
    _at_cmd_submit 2>&1
' 2>&1) || true
assert_output "submit with no args shows usage" "Usage" "$no_args_out"

# ── Test 5: both modes generate valid scripts ────────────────────

echo "--- Mode variants ---"
for mode in inline submit; do
    mode_out=$(AT_CMD_DEFAULT_MODE="$mode" at-cmd init bash)
    assert "$mode mode generates valid syntax" bash -n <(echo "$mode_out")
    assert_output "$mode mode annotates mode" "default_mode: $mode" "$mode_out"
done

# ── Summary ──────────────────────────────────────────────────────

printf "\n  bash: %d passed, %d failed\n" "$PASS" "$FAIL"
exit "$FAIL"
