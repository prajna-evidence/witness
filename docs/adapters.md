# Adapter surfaces — what each host will actually give you

**Status:** survey, 2026-09-09. Verify before building; preview surfaces move.

This file is the evidence base for `SPEC.md` §7. Each section records the surface, the maximum
evidence tier obtainable from it, and — more importantly — the fields it can *never* fill, because
those become `unavailable` reason codes rather than bugs discovered in month three.

The ordering is deliberate: build in the order the table at the end gives, not this one.

---

## 1. GitHub Agent HQ / Copilot coding agent

**Surfaces**

- **Agentic audit log events** — GitHub documents a dedicated event set for agents
  (`docs.github.com/en/copilot/reference/agentic-audit-log-events`).
- **Enterprise audit log streaming** — agent session activity can be streamed to the same
  destination as other enterprise audit events. Compressed JSON. Public preview.
- **`actor:Copilot` filter** — agentic activity over a 180-day window in the enterprise audit log.
- **Audit log REST API**, plus JSON/CSV export for offline access.

**Maximum tier: B.** This is a third-party record the audited subject does not control and can be
re-fetched by a verifier. It is the highest-value adapter in the set and the reason the compliance
buyer is reachable at all.

**Hard limits, all of which become reason codes**

| Limit | Code |
|---|---|
| Requires Enterprise Cloud with Enterprise Managed Users, or GHEC with data residency | `host_gated` |
| Public preview — shape may change without notice | `not_yet_available` |
| 180-day window on the `actor:Copilot` filter | `out_of_retention` |
| No token counts, no cost, no prompt context — it records that a session occurred | `host_does_not_emit` |

**The consequence to internalise:** this adapter alone produces a bundle that knows *who ran what
against which repo under whose approval* and knows **nothing** about model, cost or context.
That is a genuinely useful compliance artifact and a poor engineering one. Do not paper the gap;
pair it with the Claude Code adapter, which is the mirror image.

---

## 2. Claude Code

**Surfaces**

- **Hooks** — `PreToolUse`, `PostToolUse`, `SessionStart`, `Stop` and siblings, fired locally with
  structured payloads. This is the richest surface in the survey.
- **OpenTelemetry export** — designed for enterprise monitoring; the natural path for teams that
  already have a collector.
- **Transcript JSONL** — the full turn record on disk, including model id and token usage.

**Maximum tier: C**, and this is not a defect to engineer around — it is what self-reporting is
worth. Git-anchoring the bundle (SPEC §4.5) makes those claims non-repudiable, which is the honest
ceiling.

**Corrected 2026-09-10, on building it.** The survey above assumed one surface. There are two, and
they differ enough that conflating them would have overstated the adapter:

| | hook channel | transcript channel |
|---|---|---|
| Tool calls, targets, `permission_mode`, `effort` | yes | — |
| Event timestamp | **no** | yes |
| Model id, token accounting, cost | **no** | yes |

Three consequences, all now in `witness/adapters/claudecode/manifest.json`:

1. **Hook payloads carry no timestamp.** `timestamp` is our capture clock, and the lag between the
   event and our capture is unmeasurable from here. Recorded as such rather than presented as the
   event time.
2. **Model and token data are not on the hook path at all.** They live in the transcript, which is
   a separate read. **Shipped 2026-09-23 (W2b):** `bundle.assemble` now also reads each session's
   transcript (`~/.claude/projects/<cwd>/<session-id>.jsonl`, keyed by the same session id the hook
   channel already carries) and populates `model_turns` with model id, token counts and effort. A
   session whose transcript cannot be found still produces a valid bundle with `model_turns: []` —
   real and common, not a defect. `cost_usd` is out of scope for W2b and stays null on every turn:
   Witness has no price table yet, which is a Witness limitation, not a host one.
3. **`permission_mode` is the governance signal**, and the useful half is the unattended modes
   (`bypassPermissions`, `acceptEdits`, `auto`, `dontAsk`). A session run under one of those is a
   positive finding and maps to `auto_approved` with a null actor. An interactive mode is *not* its
   mirror image: it says a prompt regime was in force, not that any prompt was shown or answered,
   so it produces **no gate** and a `host_does_not_emit` reason. Manufacturing an approval out of a
   configuration value is precisely the failure this format exists to prevent.

**Limits**

| Limit | Code |
|---|---|
| Entirely local; a subject who wants to lie can edit the capture before commit | *inherent to tier C* |
| Hooks fire only where installed — silent gaps are invisible unless session ids are reconciled | `collection_failed` |

**Build this first.** No entitlement, no preview gating, no enterprise contract needed to test it,
and it is the surface a design partner can install in an afternoon.

---

## 3. GitHub Actions

**Surfaces**

- `workflow_run` events and job logs via REST.
- **Native build-provenance attestations** — `actions/attest-build-provenance`, producing in-toto
  statements on the SLSA track.

**Maximum tier: B**, and for the attestation path specifically, the trust story is already
standardised and better than anything Witness would invent.

**The rule that follows: do not re-derive build provenance.** Reference the attestation by digest,
record that it verified, and move on. The build half of the SDLC is solved; competing with it wastes
the only scarce resource here, which is a solo maintainer's weeks.

**Shipped 2026-09-23 (W4).** `witness/adapters/githubactions/` follows the rule literally: it shells
out to `gh` and treats `gh`'s own output as the verification outcome rather than reimplementing
Sigstore. Two collection paths, deliberately not conflated (see the adapter's `normalize.py`
docstring): `collect_via_api` hits `GET /repos/{repo}/attestations/{digest}` and records only
*existence* — still tier B on its own, since a verifier can re-fetch it, but with no gate, because
existence is not a verification outcome; `collect_via_verify` runs `gh attestation verify` against
a local artifact or OCI reference and records its exit code as the authoritative verified/failed
signal, which becomes a `build-provenance` gate. `workflow_run` correlation was not built — nothing
in the adapter needed it yet, and it is deferred rather than guessed at.

---

## 4. AWS AI-DLC

**What it actually is:** an open-source *methodology* — adaptive workflow steering rules
(`github.com/awslabs/aidlc-workflows`) structuring work into three phases, **Inception →
Construction → Operations**, with human verification before execution proceeds. It runs on any
agent that reads rule files: Kiro, Amazon Q, Cursor, Claude Code, Copilot.

**It has no runtime and emits no telemetry of its own.** There is no AI-DLC adapter in the
collection sense. What there is instead is a **phase mapping**, and it is valuable out of
proportion to its cost:

| AI-DLC phase | `journal-event.phase` |
|---|---|
| Inception | `intent`, `plan` |
| Construction | `code`, `build`, `review` |
| Operations | `deploy`, `monitor` |

`journal-event.schema.json` already carries `phase` as a free-form string with exactly that
conventional vocabulary. The mapping is a lookup table, not an integration.

**Why this matters strategically:** AI-DLC defines *where the approval gates belong* and ships **no
evidence artifact to prove a gate was honoured**. That is the gap Witness fills, on a methodology
AWS is actively promoting and that runs on every major agent. It is the cheapest credibility in the
plan — a page of documentation, not a milestone.

---

## 5. Codex / Cursor / others

Deferred. Both are reachable in principle (Cursor at $2B ARR is not a small population) but neither
has a documented, stable agent-audit surface worth building against in 0.x. Revisit when a design
partner asks by name — not before.

---

## Build order

| # | Adapter | Tier | Fills | Why this position |
|---|---|---|---|---|
| 1 | Claude Code hooks | C | model, tokens, cost, context, files | No gating; testable today; richest payload |
| 2 | GitHub Actions attestation | B | build provenance, commit, artifacts | Standard exists; cheap; raises `tier_floor` |
| 3 | GitHub Agent HQ audit log | B | actor, session, repo, approvals | The compliance sale, but needs an EMU-entitled partner to test |
| 4 | AI-DLC phase map | n/a | `phase` on every observation | Documentation, ~a day, disproportionate credibility |

The gating fact that shapes the whole plan: **adapter 3 cannot be built without access to an
enterprise with EMU.** That is a design-partner dependency, not an engineering one, and it is on
the critical path to the only tier-B claim that a compliance buyer cares about.
