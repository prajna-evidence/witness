# schemas/vendor/ — upstream copies, never edited

Verbatim copies of `prajna-agent/prajna-schemas`, pinned at the commit in `PINNED_AT`.

**These files are vendored, not forked.** Decision **S5** forbids forking them; vendoring is the
lockfile equivalent and is how offline validation works without a network fetch of
`https://schemas.prajnaagent.com/...`.

Rules:

- **Never edit a file in this directory.** A needed change is a PR upstream, then a re-vendor.
- Re-vendor by copying and updating `PINNED_AT` in the same commit, so a reviewer can see the
  version move.
- `scripts/validate.sh` fails if a vendored file differs from what `PINNED_AT` names, when the
  upstream checkout is present.

Why these two: `journal-event.schema.json` is the normalisation target (S5), and it `$ref`s
`memory-unit.schema.json#/$defs/prajnaUri` for `injected_units`, so both are required to resolve.
