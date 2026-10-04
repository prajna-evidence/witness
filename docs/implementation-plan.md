# Witness — implementation plan

**Status:** draft, 2026-09-09 · **Author:** initial planning session
**Reads with:** [`../SPEC.md`](../SPEC.md) (what we're building) · [`adapters.md`](adapters.md)
(what the hosts will give us) · [`decisions.md`](decisions.md) (what is locked)

---

## 0. TL;DR

- Witness is the **evidence layer over agents we do not run**. The pivot is that it stops
  competing with GitHub Agent HQ / Claude Code / Kiro and starts consuming them.
- The whole product is `SPEC.md` §4: **honest evidence tiers**. Everything else is plumbing that
  a competent engineer could write. The tier model is the part that is hard to copy and the part
  a compliance buyer is actually paying for.
- **Scope collapses by an order of magnitude** versus Prajna. Witness does not execute Java, Node,
  Python, AWS or GitHub Actions — it parses them. Roughly half of Prajna's v1.1 slice list
  (shell runtime, deploy gates, CI-orchestrator personas, MCP host) demotes from product surface
  to optional reference implementation.
- Two assets are reused unchanged: `journal-event.schema.json` as the normalisation target, and
  the git-tree-hashing rule from `provenance.schema.json`. Neither is forked.
- **The critical path is not engineering.** W5 needs an enterprise with Enterprise Managed Users.
  Start that conversation in W0, not W4.

---

## 1. What is new versus Prajna, precisely

| | Prajna | Witness |
|---|---|---|
| Runs agents | yes — the product | **no, ever** |
| Emits evidence | yes, first-party only | yes, first- **and** third-party |
| Tier model | implicit, single-tier | **explicit, per-claim** — the new idea |
| Buyer install | replace your agent | **keep your agent**, add an observer |
| Adoption friction | high | low — this is the whole thesis |

Prajna's runner is not thrown away. It becomes the tier-A reference implementation: the existence
proof that the highest tier is reachable, and the upgrade path a customer buys into after they have
lived at tier C for a quarter.

---

## 2. Milestones

Estimates are solo-maintainer working days, and assume the maintainer is not simultaneously
shipping Prajna. They are deliberately not compressed; every prior plan in this workspace
underestimated.

### W0 — Repo hygiene, first ⏱ 0.5d

The predecessor's top risk (R1) was a tree with one commit and 300 untracked files, discovered
months in. Do not repeat it.

- `git init`, `.gitignore` **before** the first `git add` (already written).
- Initial commit of `SPEC.md`, `docs/`, this plan.
- ~~Decide public vs private~~ — settled: own org, one repo (**S1**, **S9**); public since 2026-10-04 (**S21**).

**Acceptance:** `git status --porcelain` empty; remote created; pushed. ✅ done 2026-09-10 —
`github.com/prajna-evidence/witness`.

### W1 — Freeze the contract ⏱ 3d ✅ done 2026-09-10

Turn `SPEC.md` from draft to normative and write the schemas it references.

- `schemas/observation.schema.json` — profile of `journal-event` + the `source` object (§3.1).
- `schemas/evidence-bundle.schema.json` — the widened artifact (§5), with every v1 divergence in
  the table at §5.1 justified in its `description`, house style.
- `schemas/adapter-manifest.schema.json` — host, channels, max tier, permanently-null fields.
- Reason codes (§3.3) and tier definitions (§4.2) marked **frozen for v1** in the schema text.

**Acceptance:** all three validate; a hand-written example bundle validates; `SPEC.md` status
line changes to `normative`. ✅ all met. Beyond acceptance: a fourth schema (`common`) holds the
frozen tier and reason-code definitions so they have exactly one home, upstream schemas are
vendored and pinned (**S13**), and `examples/invalid/` asserts the tier rules actually reject —
without which "all green" would have meant nothing.

**Do not skip to W2.** The tier model is the product; getting it wrong after adapters exist means
rewriting them.

### W2 — Claude Code adapter + conformance kit ⏱ 5d ✅ done 2026-09-10

First adapter, because it needs no entitlement and carries the richest payload. Language settled:
**Python** (**S11**). Unblocked.

Per **S10**, the hook writes raw events and nothing else; all parsing lives in the cold path.

- Hook capture → observations. Model id, tokens, cost estimate, tool calls, file writes.
- `conformance/` modelled on `prajna-schemas/conformance/`: golden captured payloads, expected
  normalised outputs, `check.sh` requiring byte-for-byte reproduction.
- Fixtures MUST include a **gap case** — a session with a missing hook — proving the adapter emits
  `null` + `collection_failed` rather than silently shortening the record.

**Acceptance:** `check.sh` green; adapter manifest declares tier C honestly and lists every
permanently-null field. ✅ all met — 4 fixtures byte-for-byte, 16 tests, schemas + negative cases
green.

Beyond acceptance: the gap fixture proved its worth immediately, and building the adapter turned up
a survey error worth reading — the host has **two** channels, not one, and the hook carries no
timestamp, model id or token data (see `adapters.md`). That is now W2b.

### W2b — Claude Code transcript channel ⏱ 2d ✅ done 2026-09-23

The hook channel cannot see model id, tokens or cost; the transcript can. Until this ships, every
bundle from this adapter nulls those with `host_does_not_emit` — correct, but it means the richest
half of the "pair it with the GitHub adapter" argument is not yet real.

**Acceptance:** `model_turns` populated with model id and token counts; the manifest moves those
paths off `permanently_null` and onto the transcript channel; fixtures for a session where the
transcript is absent, which must still produce a valid bundle. ✅ all met —
`witness/adapters/claudecode/normalize.py`'s `normalize_transcript`/`transcript_path`, wired into
`bundle.assemble` via the adapter-optional `collect_model_turns` hook (`bundle.read_model_turns`);
`tests/test_transcript.py` covers a real captured transcript line shape, a missing-transcript
session, and the schema fragment for `model_turns[]` directly. `cost_usd` stays permanently null —
out of scope, no price table exists yet — and is called out as such in the manifest notes rather
than silently left unexplained.

### W3 — Bundle assembler + offline verify ⏱ 5d ✅ assembler done 2026-09-18 (S15), verify done 2026-09-23 (B4)

The first end-to-end deliverable and the first thing worth demoing.

- Assemble observations → `.witness/evidence/<id>.evidence.json`; commit on the branch.
- File hashes taken from the **git tree object at `commit_sha`** (`git cat-file`), never the
  working tree. This is non-negotiable and is the single most likely thing to be quietly got
  wrong under demo pressure.
- `witness verify --offline`: schema, hashes, `tier_floor` honesty check, `unavailable` coverage.
- Tier B claims MUST print as `unverified-offline`, never as passing.

**Acceptance:** a bundle made today still verifies after 30 subsequent commits, on a fresh clone.
That test is the product; write it first and let it fail. ✅ met, at the harder version of the
test: `tests/test_verify.py::test_content_reverifies_after_squash_merge_branch_delete_and_gc`
squashes, deletes the branch, expires the reflog and `git gc --prune=now`s before verifying — the
commit_sha locator is confirmed dead (`gitrepo.exists` is False) and every content claim still
holds via `gitrepo.find_containing_commit`'s history recovery. `witness/verify.py` implements all
five offline checks from SPEC.md section 6.1 (schema, content, tier_floor honesty, unavailable
coverage, tier-A hash chain) plus explicit `unverified-offline` labelling of every tier B claim,
and `--online` with a pluggable `ONLINE_VERIFIERS` registry per SPEC.md section 6.2. 140 tests pass;
`witness verify` is wired into the CLI (`witness verify <bundle> [--root] [--online] [--json]`).

### W4 — GitHub Actions attestation adapter ⏱ 3d ✅ done 2026-09-23

- Consume in-toto / SLSA build-provenance attestations by digest; record verification outcome.
- `workflow_run` correlation to tie a build to the change that caused it.
- **Do not re-derive build provenance.** Reference it.

**Acceptance:** a bundle reaches `tier_floor: B` for its build section. ✅ met, with a correction to
how "reaches tier_floor B" was read: `tier_floor` is a bundle-wide **floor** (S2), so a build-only
tier B claim never raises the single `tier_floor` value on a bundle that also carries a tier C hook
source — that would be exactly the aggregate-tier dishonesty S2 forbids. What the acceptance
criterion actually meant, confirmed while building it: the adapter's own contribution — its
sources, gates and observations — is tier B in isolation, which `witness/adapters/githubactions/`
delivers via two collection paths (`collect_via_api`: existence-only, tier B on its own since a
verifier can re-fetch it; `collect_via_verify`: runs `gh attestation verify` and records its exit
code as the authoritative verified/failed signal, never re-deriving Sigstore's trust chain per S6).
Building this surfaced a real bug in a schema rule that predated it — see decisions.md **S17**.

### W5 — GitHub Agent HQ audit-log adapter ⏱ 5d ⚠ **externally blocked**

- Enterprise audit-log stream / REST ingestion; `actor:Copilot` filter.
- Correlate host session ids with tier C local captures via `payload.corroborated_by` —
  and per §4.4, **corroboration never upgrades a tier**. Expect to want to break this rule the
  first time a demo looks weak. Don't.

**Blocked on:** access to an enterprise with EMU or GHEC data residency. Cannot be faked
convincingly; recorded fixtures from a real tenant are the only honest test.

**Acceptance:** fixtures from a real tenant; manifest records the preview status and 180-day
retention as first-class limits.

### W6 — AI-DLC phase mapping ⏱ 1d

Documentation plus a lookup table. Disproportionate credibility for the cost: it makes Witness
legible to everyone following an AWS-promoted methodology that ships no evidence artifact of its
own.

### W7 — Design-partner pilot ⏱ ongoing

One named partner running W2+W3 on real work for four weeks. Not a launch.

---

## 3. Timeline

**~16 working days of engineering remaining** (W1 + W2 done; W2b added; originally ~22) to a demonstrable product (W0–W4, W6), excluding W5.

W5 is the compliance sale and it is gated on a partner relationship that does not exist yet. Treat
its start date as unknown and **do not sequence anything behind it.**

---

## 4. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | **No named buyer.** Inherited unresolved from Prajna (criterion 14). The tier model is designed for a buyer who has never been interviewed | **critical** | W0 task, not W7: interview three compliance-motivated engineering leaders before W1 freezes the tiers |
| R2 | GitHub extends Agent HQ into evidence and closes the gap | high | Defensible edge is **cross-host normalisation** — GitHub has no incentive to normalise AWS's or Anthropic's events — plus offline verifiability, which a SaaS audit log structurally is not |
| R3 | Agent HQ surfaces are public preview and may move | medium | Adapter manifests version the surface; conformance fixtures pin the shape; `not_yet_available` is a first-class code |
| R4 | Tier C is most of the market and proves the least | medium | §4.5 non-repudiation is the honest value at tier C. Sell it as that, never as verification |
| R5 | Scope drift into a dashboard | medium | `SPEC.md` §2 non-goals are load-bearing; re-read before accepting a feature request |
| R6 | Solo-maintainer bandwidth split with Prajna | high | Prajna's runner is frozen as the tier-A reference. No new Prajna slices until W7 |
| R7 | ~~Private repo defers the licence question until it is expensive to answer~~ | closed | Published under Apache-2.0 (**S12**, **S21**) |
| R8 | Python `verify` needs a runtime on an auditor's machine | medium | Ship as container + `uv tool install`; S11/S12 make a third-party verifier a feature, not a threat |
| R9 | Licence strategy crowds out customer discovery | medium | S12's sub-question is explicitly parked behind R1 |

R1 is the dominating one. The prior effort built a technically sound platform against an
unvalidated buyer for four months; the tier model is a bet on what an auditor will accept, and it
is cheap to test by asking and expensive to discover after W4.

---

## 5. What this plan does NOT authorise

- Building an orchestrator, personas, or a task queue in this repo.
- Forking `journal-event.schema.json`, or copying any `prajna-schemas` file into this repo.
- A dashboard, agent-productivity metrics, or policy evaluation.
- Re-implementing SLSA / in-toto.
- Marketing that describes a git-anchored tier C claim as "verified" (SPEC §4.5).
- Buying a domain before R1 is closed.
