# Witness

**A verifiable record of what AI coding agents did to your code.**

Witness attaches to agents you already run (Claude Code, GitHub Actions; Copilot / Agent HQ planned).
For each change it commits an **evidence bundle** to your repo recording which model touched which
files, under whose approval, citing what context, at what cost. Nothing is sent anywhere.

## Why it's different: every claim says how much to trust it

| Tier | Source | What catches a lie |
|---|---|---|
| **A** attested | a runner you control, hash-chained | post-hoc edits |
| **B** host-attested | a third party (e.g. GitHub attestations) | local fabrication |
| **C** self-reported | the agent's own hooks and transcript | nothing, but it is fixed once anchored in git |

Tiers are assigned **per claim, not per bundle**. Corroboration never upgrades a tier. Missing data
is recorded as missing (`null` + reason), never as zero.

## Quick start

```bash
pipx install git+https://github.com/prajna-evidence/witness   # Python 3.11+

witness init                                   # install capture hooks in this repo
# ... work with your agent, commit ...
witness bundle                                 # assemble .witness/evidence/<id>.evidence.json
witness verify .witness/evidence/<id>.evidence.json   # re-derive every claim, offline
witness view   .witness/evidence/<id>.evidence.json   # self-contained HTML report
```

After merging: `witness reconcile <bundle> --merge-commit <sha>`. Use `verify --online` to re-check tier B claims.

## Docs

- [`RUN.md`](RUN.md): end-to-end walkthrough, plus session, git and CI wiring
- [`SPEC.md`](SPEC.md): the normative format (§4 defines the tiers)
- [`docs/adapters.md`](docs/adapters.md): what each host exposes, and its limits
- [`docs/decisions.md`](docs/decisions.md): design decisions and why

## Status

`0.1.0`, pre-release. Claude Code adapter (hooks + transcript), GitHub Actions build-provenance adapter,
bundling, reconciliation, verify and viewer all work; 158 tests and a conformance suite.
Not in scope: running agents, re-deriving SLSA provenance, dashboards, policy judgement.

Observations are a profile of [`prajna-schemas`](https://github.com/prajna-agent/prajna-schemas)
`journal-event`, vendored in `schemas/vendor/`.

Found an ambiguity in the spec? That's a bug: [open an issue](https://github.com/prajna-evidence/witness/issues).

## License

[Apache-2.0](LICENSE)
