#!/usr/bin/env bash
# Schema and example validation. Also checks that vendored upstream copies still
# match their pin, when an upstream checkout is available.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== schemas and examples =="
python3 scripts/validate.py

echo
echo "== vendored pin =="
UPSTREAM="${PRAJNA_SCHEMAS_DIR:-$HOME/source/prajna/prajna-schemas}"
if [ -d "$UPSTREAM/schemas" ]; then
  pinned_commit=$(sed -n '2p' schemas/vendor/PINNED_AT | cut -d' ' -f1)
  head_commit=$(git -C "$UPSTREAM" rev-parse HEAD)
  for f in journal-event memory-unit; do
    if diff -q "schemas/vendor/$f.schema.json" "$UPSTREAM/schemas/$f.schema.json" >/dev/null; then
      echo "  ok   $f.schema.json matches upstream working tree"
    else
      echo "  WARN $f.schema.json differs from upstream working tree — re-vendor or check S5"
    fi
  done
  [ "$pinned_commit" = "$head_commit" ] || echo "  note pinned $pinned_commit, upstream HEAD $head_commit"
else
  echo "  skip upstream checkout not found at $UPSTREAM"
fi
