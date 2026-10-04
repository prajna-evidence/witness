#!/usr/bin/env bash
# Conformance: every fixture must normalise to its expected output BYTE FOR BYTE.
#
# Byte-for-byte rather than "semantically equivalent" on purpose. The fields most
# likely to drift are the nulls and their reason codes, and a looser comparison is
# exactly the one that would stop noticing when a reason quietly changes.
set -euo pipefail
cd "$(dirname "$0")/../.."

fail=0
for fixture in conformance/claudecode/fixtures/*.jsonl; do
  name="$(basename "$fixture" .jsonl)"
  expected="conformance/claudecode/expected/$name.json"
  actual="$(mktemp)"
  PYTHONPATH=. python3 -m witness.cli normalize "$fixture" 2>/dev/null > "$actual"
  if diff -u "$expected" "$actual" > /dev/null; then
    echo "  ok   $name"
  else
    echo "  FAIL $name"
    diff -u "$expected" "$actual" | head -30
    fail=1
  fi
  rm -f "$actual"
done

echo
if [ "$fail" -eq 0 ]; then echo "conformance: all green"; else echo "conformance: FAILED"; fi
exit "$fail"
