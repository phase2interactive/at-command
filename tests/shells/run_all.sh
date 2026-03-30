#!/usr/bin/env bash
# Run shell integration tests for all supported shells (excluding PowerShell).
set -euo pipefail

passed=0
failed=0
errors=()

for script in /tests/test_*.sh; do
    shell_name=$(basename "$script" .sh | sed 's/^test_//')
    printf "\n══════════════════════════════════════\n"
    printf "  Testing: %s\n" "$shell_name"
    printf "══════════════════════════════════════\n\n"

    if "$script"; then
        passed=$((passed + 1))
    else
        failed=$((failed + 1))
        errors+=("$shell_name")
    fi
done

printf "\n══════════════════════════════════════\n"
printf "  Results: %d passed, %d failed\n" "$passed" "$failed"
if ((failed > 0)); then
    printf "  Failed: %s\n" "${errors[*]}"
fi
printf "══════════════════════════════════════\n\n"

exit "$failed"
