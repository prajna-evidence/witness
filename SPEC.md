# Witness — observation, evidence tiers and verification

**Version:** 1.0.0 · **Status:** normative · **Licence:** Apache-2.0 (S12)
**Distribution:** public (S21).
**Date:** 2026-09-09

This document defines what Witness records about an AI-authored change, how that record is
attributed to its source, and exactly what a reader may and may not conclude from it.

It is written to be sufficient on its own. Witness's implementation may be proprietary; this
document and the schemas beside it are the whole contract — the same relationship `prajna-schemas`
already has to Prajna's private runtime. If you find an ambiguity, that is a defect here and we
want the report (§10).

The key words MUST, MUST NOT, REQUIRED, SHALL, SHOULD, SHOULD NOT, MAY and OPTIONAL are to be
interpreted as in RFC 2119.

---

## 1. What this is, in one paragraph

Witness observes AI coding agents it does not run — GitHub Agent HQ / Copilot, Claude Code,
Codex, Cursor, an AWS AI-DLC workflow, a GitHub Actions job — and assembles, per change, a
committed **evidence bundle** that says what model touched which files, under whose approval,
citing what context, at what cost. The bundle is committed into the user's own repository and
pushed, so the record leaves the machine that produced it.

The hard part is not collection. The hard part is **being honest about how much each claim is
worth**, because a claim collected from an agent's own self-report is not the same kind of thing
as one retrieved from a third party's audit log, and an artifact that flattens the two is worse
than no artifact at all. §4 is therefore the centre of this specification.

---

## 2. Non-goals

Stated first, because the failure mode of this product category is scope drift into a dashboard.

- **Witness does not run agents.** It has no orchestrator, no personas, no task queue, no model
  transport. If it ever needs one to make a demo work, that is a defect in the adapter.
- **Witness does not replace SLSA / in-toto.** Build and artifact provenance is a solved,
  standardised problem. Witness *references* in-toto attestations; it never re-derives them.
- **Witness is not an observability product.** No latency charts, no fleet dashboards, no
  agent-productivity metrics. Those are a different purchase made by a different person.
- **Witness does not judge.** It records that a gate was auto-approved; it does not opine on
  whether that was wise. Policy evaluation is a separate concern and out of scope for 0.x.

---

## 3. The observation record

An **observation** is one normalised record of one thing an agent did.

Observations are a **profile of `journal-event.schema.json`** from `prajna-schemas`
(Apache-2.0, https://github.com/prajna-agent/prajna-schemas). That schema is reused rather than
reinvented: it already carries `phase`, `tokens`, `cost_usd`, `injected_units`, a hash chain, and
it sets `additionalProperties: true`, which is what lets an adapter carry host-native fields
through without loss. Shapes flow one way — Witness consumes that contract and never forks it.

A conforming observation MUST satisfy `journal-event.schema.json` and MUST additionally carry a
`source` object (§3.1).

### 3.1 `source` — mandatory attribution

Every observation MUST record how it was obtained. Without this, tier assignment (§4) is not
computable and the bundle is invalid.

| Field | Type | Meaning |
|---|---|---|
| `source.host` | string | The system observed: `github-agent-hq`, `github-actions`, `claude-code`, `codex`, `cursor`, `aidlc`, `witness-native` |
| `source.channel` | string | The specific surface it came from: `enterprise-audit-log`, `rest-api`, `hook`, `otel`, `transcript`, `attestation`, `workflow-run` |
| `source.tier` | enum | `A`, `B` or `C` per §4. Assigned by the adapter, constrained by §4.4 |
| `source.collected_at` | date-time | When Witness obtained it — distinct from `timestamp`, which is when the event occurred |
| `source.retrievable_from` | string \| null | For tier B only: a stable locator a verifier can re-fetch the claim from. Null at tiers A and C |
| `source.adapter_version` | string | Exact adapter build that produced the record. Names what to re-run |

### 3.2 Absence is recorded, never omitted

If a host cannot supply a field, the adapter MUST emit the field as `null` **and** record the
reason in `payload.unavailable`, a map of field-path to a machine-readable reason code from §3.3.

An adapter MUST NOT omit the field, MUST NOT substitute zero, and MUST NOT infer a value.

This is the single most abused seam in the category. Token counts are the worked example: an
enterprise audit log records that an agent session happened, not what it cost. `tokens: null,
unavailable: {tokens: "host_does_not_emit"}` is a true statement about the limits of the
evidence. `tokens: {input: 0, output: 0}` is a false one, and a reader cannot tell it from a
genuinely free turn. Reporting a nought is how an audit trail becomes worthless — the same
reasoning `provenance.schema.json` already applies to `redaction.scans: 0`.

### 3.3 Reason codes

Closed list. An adapter MUST NOT invent a code; propose additions by PR.

| Code | Means |
|---|---|
| `host_does_not_emit` | The host has no such concept or does not expose it on any surface |
| `host_gated` | The surface exists but requires an entitlement this deployment lacks (e.g. GitHub EMU) |
| `not_yet_available` | The surface is in preview and unstable; revisit |
| `permission_denied` | Credentials present but insufficient |
| `collection_failed` | The surface was reachable but the read errored. MUST carry `payload.error` |
| `out_of_retention` | The event predates the host's retention window |
| `not_applicable` | The field is meaningless for this event kind |

---

## 4. Evidence tiers

The load-bearing section.

### 4.1 The question a tier answers

A tier is not a quality score and not a confidence level. It answers exactly one question:

> **If the party being audited is lying, what catches them?**

### 4.2 The three tiers

**Tier A — attested.** The claim was produced by a runner under Witness's control, written to an
append-only journal whose hash chain head is committed to the user's git and pushed to a remote
the runner does not control.
*Catches:* post-hoc edit of the journal, because forging it requires rewriting the journal **and**
git history **and** force-pushing to every clone.
*Does not catch:* a compromised runner lying at the moment of writing.

**Tier B — host-attested.** The claim is independently retrievable from a third party the audited
subject does not control: a GitHub enterprise audit-log stream, a GitHub Actions in-toto
attestation, a model provider's billing record.
*Catches:* local fabrication of the whole record, since a verifier can re-fetch it.
*Does not catch:* anything, once the host's retention window closes. Tier B claims are perishable,
and a verifier that cannot reach the host degrades the claim to tier C rather than failing —
this MUST be reported, never silently absorbed.

**Tier C — self-reported.** The agent said so about itself, via hooks, transcripts or local
telemetry.
*Catches:* nothing, on its own.
*Worth recording anyway:* it is the only tier that captures intent, prompt context and the
reasoning trail, and it is the tier every non-enterprise deployment will actually have. It is
evidence of *what was claimed*, which is not nothing — see §4.5.

### 4.3 Tiers are per claim, never per bundle

A bundle MUST report a tier for each section independently. A bundle MUST also report
`tier_floor`, the lowest tier of any section a reader would rely on.

A bundle MUST NOT advertise a single aggregate tier. The realistic bundle is mixed — tier B file
hashes from the git tree, tier C model and token data from hooks, tier B gate approvals from the
host's review record — and collapsing that to one number is the precise dishonesty this
specification exists to prevent.

### 4.4 No upgrade by inference

An adapter MUST NOT assign a tier higher than the weakest link in how it obtained the claim.

Specifically: reading a self-reported value from a local hook and then finding a *consistent*
value in a host audit log does **not** make the claim tier B unless the tier-B source carries the
value itself. Corroboration is recorded as `payload.corroborated_by`; it never changes `tier`.

### 4.5 Git anchoring is available at every tier

Committing the bundle to the user's repository and pushing it makes the bundle immutable relative
to that push, at every tier.

Be exact about what this buys, because it is easy to oversell: it proves **what was claimed, and
when**. It does not make a tier C claim true. A tier C claim that is git-anchored is
*non-repudiable* — the subject cannot later produce a different story about the same change —
and that is a materially different and weaker property from *verified*. Documentation, UI copy and
sales material MUST preserve this distinction verbatim.

---

## 5. The evidence bundle

One bundle per change that reaches a pull request. Written to
`<repo>/.witness/evidence/<id>.evidence.json`, committed on the branch, so it is reviewed with
the change it describes.

### 5.1 Relationship to `provenance.schema.json`

The bundle is a **deliberate widening** of Prajna's `provenance.schema.json` v1, not a copy.
v1 is a first-party artifact: four of its required fields are unknowable from outside the runner
that produced them.

| v1 field | v1 constraint | Why a foreign host breaks it | 0.1 resolution |
|---|---|---|---|
| `model_turns[].transport` | enum `api-key \| agent-sdk \| claude-cli` | A Copilot or Codex turn is none of these | Replaced by `{host, transport}`; `transport` becomes open string |
| `model_turns` | `minItems: 1`, `tokens` required | An audit log records a session, not its turns or cost | `minItems: 0` permitted when `tier_floor` is C; `tokens` nullable per §3.2 |
| `redaction` | required object | No foreign host runs Prajna's detector | Nullable; `null` asserts *no redaction was performed by us*, which is itself a finding |
| `pramana.chain_head` | required, sha256 | Requires Prajna's own append-only journal | Present only at tier A; the section is nullable |
| `memory` | required | Requires Smriti; foreign hosts have no unit addresses | Nullable |

Two v1 properties are kept **unchanged and non-negotiable**, because they are what make the
artifact evidence rather than assertion:

1. **File hashes are taken from the git tree object at `commit_sha`, never the working tree.**
   An artifact that verifies only on the day it was made is not evidence.
2. **Whatever anchor exists is committed and pushed**, so it lives outside the store it attests to.

### 5.2 Required sections

`schema_version`, `id`, `generated_at`, `generated_by`, `tier_floor`, `commit_sha`, `repo`,
`sources`, `observations`, `files`, `gates`, `model_turns`, `unavailable`.

`sources` is an array of every `source` (§3.1) that contributed, deduplicated — so a reader can
see the provenance of the provenance without walking every observation.

---

## 6. Verification

`witness verify <bundle>` has two modes, and the distinction MUST be visible in its output.

### 6.1 Offline (default)

Runs with the network disabled. Checks:

1. The bundle validates against its schema.
2. Every `files[].sha256` matches the content of that path in the git tree at `commit_sha`
   (`git cat-file`), on any clone, at any later date. When that commit is unreachable (S15), a
   verifier MAY find the content in a commit after a reachable `anchors.base_commit` (with no
   reachable base it MUST NOT search). Such a hit MUST be reported as `recovered`, never as a
   match: the base is the bundle author's claim, so recovery shows only that the content existed
   after it, not that this change produced it. `recovered` does not fail a bundle.
3. `tier_floor` equals the minimum of the per-section tiers, observations included — i.e. the
   bundle does not overstate itself. Every observation's source MUST also appear in `sources`.
4. Every `null` field has a corresponding `unavailable` reason from the closed list (§3.3).
5. At tier A only: the hash chain is continuous and terminates at the recorded `chain_head`.

Offline verification MUST report tier B claims as **unverified-offline**, never as passing.
A verifier that quietly treats "could not check" as "checked" is the failure this whole design is
organised against.

### 6.2 Online

Additionally re-fetches each tier B claim from `source.retrievable_from` and compares. Output MUST
distinguish four outcomes per claim: `confirmed`, `contradicted`, `unreachable`, `out_of_retention`.

A locator MUST be bound before it is re-fetched, to the repository of the checkout being verified,
read from that clone and never from the bundle, whose author controls it. A locator naming a
different repository is `contradicted`. One that cannot be bound is `unreachable`: the checkout has
no matching remote, the bundle names a different repository than the checkout, or the locator does
not name exactly one repository. Otherwise a third party's record about someone else's repository
would confirm a claim about this one.

`contradicted` is the only finding that fails a bundle. `unreachable` and `out_of_retention`
degrade the claim to tier C and lower `tier_floor` accordingly — a host's retention policy is not
the subject's fault, and treating it as a failure would make bundles rot into false accusations.

---

## 7. Adapters

An adapter maps one host surface to observations. It MUST be pure: input bytes in, observations
out, no network of its own beyond the collection call, no writes.

Adapters ship a manifest declaring the host, the channels, the maximum tier obtainable from each,
and the fields it can never fill (with reason codes). The manifest is what §8's conformance kit
tests, and it is also the honest answer to "what will this actually tell me about my Copilot
fleet" — a question that should be answerable before installation, not after.

See `docs/adapters.md` for the surveyed surfaces and their verified limits.

## 8. Conformance

Adapter correctness is testable and MUST be tested the same way `prajna-schemas` tests Smriti
resolution: a golden corpus of captured host payloads, a set of expected normalised outputs, and a
runner that requires byte-for-byte reproduction.

An adapter is conforming if, for every fixture, it emits exactly the expected observations —
including the `null`s and their reason codes, which are the part that will drift.

## 9. Versioning

Additive-only within a major version. A field may be added; a field may not change type, and an
enum may not lose a member. Reason codes (§3.3) and tier definitions (§4.2) are frozen for the
life of major version 1 — a tier whose meaning drifts retroactively falsifies every bundle already
committed to a customer's git history.

## 10. Ambiguity is our defect

If two competent implementers could read this document and build adapters that disagree, this
document is wrong. Open an issue with the passage and the two readings.

The channel is this repository's issue tracker: https://github.com/prajna-evidence/witness/issues
