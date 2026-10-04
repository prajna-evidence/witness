# schemas/

| File | Defines |
|---|---|
| `common.schema.json` | Evidence tiers, the closed reason-code list, the `source` block. **Frozen for major version 1** |
| `observation.schema.json` | One normalised record — a profile of `journal-event`, plus `source` |
| `evidence-bundle.schema.json` | The committed artifact. Each divergence from `provenance.schema.json` v1 is justified inline |
| `adapter-manifest.schema.json` | What an adapter can and cannot tell you, declared before it runs |
| `vendor/` | Verbatim upstream copies, pinned. Never edited — see `vendor/README.md` and **S5** |

`$id`s are relative filenames. Absolute `$id`s under a real domain get assigned at publication;
inventing one now would presume a name and a domain that decisions **S1** and **S8** deliberately
leave open.

## Checking

```sh
./scripts/validate.sh
```

Validates every schema, validates `examples/*.json` against the schema each names, and — the part
that matters — asserts that everything under `examples/invalid/` is **rejected**. A schema that
accepts everything proves nothing, so the negative cases are the real test. They currently pin
two rules: a tier B source must carry a locator, and reason codes are a closed list. (A third rule —
empty `model_turns` forces `tier_floor: C` — was retired in **S17**: the general form of that check,
correct across every section rather than special-cased to model turns, now lives in `witness verify`
instead of the schema.)
