# Witness decisions

Append-only. Supersede entries; never delete them.

---

## S1 — Witness lives in its own org, in one private repository; licence deferred

**Status:** locked, 2026-09-10. **Supersedes** the open form of this entry dated 2026-09-09.

`github.com/prajna-evidence/witness`, private. A **new org**, deliberately not `prajna-agent`:
Witness is a different product with a different buyer, and an org boundary is the cheapest way to
keep that true when the two start sharing vocabulary.

**Licence: deferred**, not chosen. The repository being private makes it a decision we are not yet
forced to take, which is the point.

**The original recommendation was spec-public / assembler-proprietary, and it was not taken.**
Recorded because the reasoning still stands and will resurface: public adapters attract contributed
host coverage, which is the expensive long tail of this product (Codex, Cursor, Gemini, whatever
ships next quarter), and one maintainer cannot cover it alone.

**Why private won anyway:** private → public is a one-click change; public → private is not. The
contribution argument only pays once there are outside adapter authors to attract, which is not
today, and taking an irreversible step early to buy a benefit that is months away is the wrong
order of operations. This mirrors `prajna-schemas`, which was private until the day it needed to
be read by someone outside — then published deliberately, after a pre-publication pass.

**The debt this creates, so it is not discovered later:** `SPEC.md` is written in the voice of a
public contract and §10 invites ambiguity reports. While the repo is private that invitation has no
addressee. The spec now says so in its header. If it is ever published, redo the `prajna-schemas`
pre-publication pass first — that one found ~12 citations pointing into a private workspace.

## S2 — Evidence tiers are per claim, never per bundle

**Status:** locked, 2026-09-09. **Normative in** `SPEC.md` §4.3.

A single aggregate tier is a lie about a mixed-provenance artifact. Every realistic bundle mixes
tier B file hashes with tier C model data. Collapsing that to one number is precisely the
dishonesty this product exists to prevent, and it is the thing a hostile auditor will find first.

## S3 — Corroboration never upgrades a tier

**Status:** locked, 2026-09-09. **Normative in** `SPEC.md` §4.4.

Finding a consistent value in a host audit log does not make a locally-captured value
host-attested. Recorded as `payload.corroborated_by`. This rule will feel wrong the first time it
makes a demo look weaker than it "really" is; that pressure is exactly why it is written down.

## S4 — Absence is recorded, never omitted or zeroed

**Status:** locked, 2026-09-09. **Normative in** `SPEC.md` §3.2.

`tokens: null` + `host_does_not_emit` is true. `tokens: {input: 0, output: 0}` is false and
indistinguishable from a free turn. Extends the reasoning `provenance.schema.json` already applies
to `redaction.scans: 0`.

## S5 — Reuse `journal-event.schema.json`; do not fork it

**Status:** locked, 2026-09-09.

It already carries `phase`, `tokens`, `cost_usd`, `injected_units`, the hash chain, and
`additionalProperties: true` for host-native passthrough. Shapes flow one way, per the workspace
rule. Witness-specific shapes live here until stable, and are promoted by PR if ever shared.

## S6 — Witness does not re-derive build provenance

**Status:** locked, 2026-09-09.

in-toto / SLSA via `actions/attest-build-provenance` is standardised and better than what we would
build. Reference by digest; record the verification outcome. Competing here spends the only scarce
resource — maintainer weeks — on a solved problem.

## S7 — Tier A remains reachable via Prajna's runner, which is frozen as a reference implementation

**Status:** locked, 2026-09-09.

Prajna is not abandoned; it is demoted from product to existence proof, and becomes the upgrade
path for a customer who has outgrown tier C. No new Prajna feature slices until Witness W7.

## S8 — No domain purchase, no product name commitment, until a named buyer exists

**Status:** locked, 2026-09-09.

`witness` is the working directory name and carries no commitment. Any eventual mark must clear
USPTO/EUIPO classes 9 and 42 before money is spent — domain availability is the cheap filter, the
trademark search in the software class is the one that produces letters. Prior candidate
"mySentry" was rejected: SENTRY is registered to Functional Software, Inc. for error-logging
software, which is the same goods class.

## S9 — One repository, not two; the split is drawn as directories so it stays mechanical

**Status:** locked, 2026-09-10.

Spec, schemas, conformance kit, adapters and CLI live in one repo. The Prajna precedent
(`prajna-schemas` public + `prajna-agent` private) is the right end state but the wrong starting
point: through W1–W3 nearly every change touches spec **and** adapter **and** fixture together, and
the workspace rule is explicit that a change spanning two repos is two commits in two repos, never
one. Paying that tax at zero users, solo, buys nothing.

Layout keeps the future seam visible:

```
SPEC.md  schemas/  conformance/    the contract — splits out unchanged if ever needed
witness/cli.py                     CLI entrypoint
witness/adapters/{claudecode,...}/ one package per host, each with its manifest.json
witness/{raw,tiers}.py             hot path + the frozen enums
tests/                             properties the conformance kit cannot express
```

**Layout amended 2026-09-10:** originally written `cmd/` + `internal/`, which is Go
convention. S11 chose Python, so the tree is Python-idiomatic. The seam is unchanged: the
contract directories at the top still split out untouched.

**Revisit when** either (a) an outside party needs to read the contract, or (b) the assembler
becomes something we sell separately from the spec.

## S10 — The CLI is the product; the plugin and the container are packagings of it

**Status:** locked, 2026-09-10.

One binary. A Claude Code plugin is `hooks.json` plus that binary; a GitHub Action is `action.yml`
plus that binary; the enterprise Agent HQ collector is a Docker image of that binary on a schedule.
Nothing forks, and no surface gets its own implementation.

Forced by where the code has to run: a hook fires on every tool use (rules out container startup),
and `verify --offline` has to run on an auditor's laptop with no runtime installed and no network
(rules out anything needing an interpreter, a daemon or a service).

**The load-bearing half of this decision is the hot/cold split.** The hook does exactly one thing:
append the raw event to `.witness/raw/*.jsonl`. No parsing, no normalisation, no git, no schema
validation. All of that happens once, at PR time, in a separate invocation.

**Why it is stated as a decision rather than left to taste:** putting the parser in the latency path
of every tool call is how an observability tool gets uninstalled in week two, and the pressure to
"just do it inline, it's only a few milliseconds" arrives early and sounds reasonable every time.

## S11 — Implementation language: Python

**Status:** locked, 2026-09-10. Unblocks W2.

Python. Reuses Prajna idiom and existing code, keeps one language for one maintainer, and **S10's
hot/cold split is what makes it viable** — the hook appends raw JSONL and never parses, so
interpreter startup is not in the latency path of a tool call.

| | Go | Python (chosen) |
|---|---|---|
| `verify` on an auditor's machine | single static binary | needs a runtime, or a container |
| Hook latency | ~5ms | ~150-300ms, survivable only because of S10 |
| GitHub Action packaging | trivial | workable, uglier |
| Maintainer cost | a second language, solo | none |

**What this costs, stated plainly:** the sentence "one binary, no runtime, no network" is no longer
available. `verify` must ship as a container or a `uv tool install` for the auditor case.

**The mitigation is better than the thing lost.** Under S12 the format is Apache-2.0 and
conformance-tested, so a **third-party verifier written from `SPEC.md` is a feature, not a threat** —
an independent implementation that reproduces our output is the strongest possible evidence that
our evidence is real. A single proprietary binary could never make that claim. If someone writes
the Go verifier, we link to it.

**Note on #64.** Prajna's "one maintained implementation, and it is Python" was scoped to the
Smriti *cascade*, in that repo. This decision agrees with it by coincidence, not by inheritance.

## S12 — Licence is Apache-2.0, and the open/commercial boundary is drawn at the tier line

**Status:** locked, 2026-09-10 for the licence and the boundary. The **revenue mechanism is open** —
see the sub-question below. **Amends** S1's "licence deferred".

Apache-2.0, replacing the MIT file the repo was seeded with. Matches `prajna-schemas`, so an
enterprise legal team reviewing both contracts is not asked why they differ, and it carries the
express patent grant and retaliation clause that MIT lacks.

**A licence on a private repo grants nothing** — it begins operating the day we distribute. So this
costs nothing today and commits nothing except the answer to "what happens when we publish".

### Why open-licensing does not undermine selling this

**A closed verifier is a contradiction in terms for this product.** The pitch is *do not trust the
tool, check the evidence*. If the checker is a black box, the problem has been reproduced one level
up, and the first competent auditor will say so. Apache-2.0 on the spec, the format and the
verifier is not a concession — it is a functional requirement of being believed.

The boundary is therefore drawn **at the tier line, not at a feature line**:

| Open (Apache-2.0) | Commercial |
|---|---|
| `SPEC.md`, schemas, conformance kit | **Tier A** — the attesting runner (Prajna) |
| Adapters and collection | Retention beyond a host's window (GitHub's is 180 days) |
| `verify --offline` | Countersignature by a party the subject does not control |
| The bundle format itself | Framework mapping and audit reporting |

**Why this holds up:** what is sold is not code, so forking the code does not reach it.

- **Tier A is a capability gap.** A fork gets the CLI and still cannot attest, because attestation
  requires a runner the customer does not control. This is S7 already.
- **Retention is an operated service.** Tier B claims are perishable by design (`SPEC.md` §6.2) —
  a bundle whose host attestations have aged out of a 180-day window quietly degrades to tier C.
  Somebody has to archive them. That is recurring, and a fork does not provide it.
- **Countersignature is structurally unforkable.** The value is *being a third party*. A fork of
  our code cannot be someone else. This falls directly out of the tier model and is the strongest
  long-term position on the table.

### Open sub-question — which of the three is the product

Not answerable from here. It depends on what a compliance buyer will actually sign for, and no such
buyer has been interviewed (**R1**). Countersignature looks strongest on paper and is the furthest
from anything built.

**Do not let this decision substitute for R1.** Monetisation strategy is downstream of whether
anyone wants the artifact, it is far more enjoyable to reason about, and that is exactly why it
tends to get worked on first.

## S13 — Upstream schemas are vendored and pinned, never edited

**Status:** locked, 2026-09-10. **Scopes** S5.

`journal-event.schema.json` and `memory-unit.schema.json` are copied verbatim into
`schemas/vendor/` with the upstream commit and per-file sha256 recorded in `PINNED_AT`.

**Vendoring is not forking.** S5 forbids forking; this is the lockfile equivalent, and it is what
makes offline validation possible without fetching `https://schemas.prajnaagent.com/...` at check
time — which matters because `verify --offline` is a product requirement, not a convenience.

Rules: never edit a vendored file; a needed change is an upstream PR then a re-vendor; update
`PINNED_AT` in the same commit so the version move is visible in review. `scripts/validate.sh`
warns when a vendored copy has drifted from an upstream checkout.

## S14 — Commercial material is not committed to this repository

**Status:** locked, 2026-09-10. **Supersedes** an entry of this number that recorded pricing bands;
that entry and its companion document were removed from the repository and from git history.

Pricing, packaging, positioning, marketing copy and competitive analysis do not belong in the
product repository. They live outside it.

**Why, beyond preference:** this repository is the contract. Under S12 the spec, schemas and
verifier are Apache-2.0 and intended to be published; anything committed here should be safe to
publish on the day that happens, and commercial material is not. The `prajna-schemas`
pre-publication pass exists precisely because unpublishable content had accumulated in a repository
that later needed to be read by outsiders — this decision prevents the same cleanup here.

**What stays:** the engineering consequence, stripped of the commercial reasoning. R1 (no named
buyer) remains in the plan's risk table because it gates the roadmap. No numbers.

## S15 — The bundle carries an `anchors` object; `commit_sha` is a locator, not a durable fact

**Status:** locked, 2026-09-18. **Scopes** the `commit_sha` description in
`evidence-bundle.schema.json`, which called it "THE LOAD-BEARING FIELD".

`commit_sha` does not survive the merge strategies most repositories use. A squash merge replaces
the branch commits with a new one; a rebase merge rewrites every sha. Once the branch is deleted the
commit a bundle names is unreferenced and eventually collected. A bundle anchored only to it stops
verifying **for reasons that have nothing to do with retention decay** — which is the one failure
this format exists to make legible. A decayed claim and a broken tool must never look alike.

There is also a self-reference problem: a bundle committed in the pull request cannot hash the
commit that contains it.

### What changes

A new required `anchors` object separates locating a change from verifying its content:

| Field | What it is | Tier | Survives |
|---|---|---|---|
| `base_commit` | Commit the diff was taken against | — | locator only |
| `base_tree` | Tree object of `base_commit` | B | rebase onto an unchanged base |
| `patch_id` | `git patch-id --stable` of the branch diff | **C** | rebase only |
| `merge_commit` | Where the change landed, written post-merge | B when read from the host's merge event | recorded after the fact |

`files[].sha256` was already the durable anchor and does not change. The schema already specifies
sha256 of the file bytes rather than the git blob id, and a content hash is identical in any
repository holding the same bytes — it survives rebase, squash, cherry-pick and re-clone. **The
content claims were never the fragile part. The pointer was.**

### `patch_id` is tier C and stays there

It is stable across rebase, which is why it is recorded. It is **not** stable across a squash of
more than one commit: squashing N commits produces the combined diff, whose patch-id matches none of
the N originals. It is a correlation hint, never an identity, and nothing may use it to decide that
two changes are the same change. A test pins this (`test_patch_id_is_not_stable_across_a_multi_commit_squash`).

This is the half of the proposed fix that was wrong on first review and is recorded here so it is
not re-adopted.

### Verification becomes two questions, not one

`witness verify` asks them separately and reports them separately:

1. **Is the content what the bundle says?** Answerable from `files[].sha256` against any commit that
   holds the path, so it survives a dead `commit_sha`.
2. **Is the commit the bundle names still reachable?** Often no, legitimately. Reported as a
   degraded locator with a reason code — never as a content failure, and never silently repaired by
   rewriting the bundle.

### Why this is a breaking change and why that is acceptable now

`schema_version` goes `1` → `2`, because `additionalProperties: false` means a v1 validator rejects
a bundle carrying `anchors`. Making the field optional would not avoid that and would leave the
locator unrepairable in exactly the bundles that need it.

This is only acceptable because **nothing is released**: version 0.1.0, no PyPI package, no external
consumer, no bundle in anyone's repository. After D1/D2 the additive-only rule in
`schemas/vendor/memory-unit.schema.json` binds here too and a change of this shape becomes a
migration rather than an edit. **This is the last cheap opportunity to take it.**

---

## S16 — Renamed `Smrithi` → `Witness`; the old name collided with a Prajna subsystem

**Status:** locked, 2026-09-20.

**The defect.** `Smrithi` sat one letter from **`Smriti`**, Prajna's long-term memory subsystem
(`prajna-agent/CLAUDE.md`). Two different things, one letter apart, in adjacent repositories that
already share vocabulary. The failure mode is not theoretical — the collision was found because the
author himself conflated them, describing Witness as "an internal layer of Prajna," which is an
accurate description of `Smriti` and a wrong one here. A name that misleads its own author will
mislead every reader after him.

The two are not merely distinct, they are opposites in the dimension that matters:

| | `Smriti` | Witness |
|---|---|---|
| What it is | A subsystem **inside** Prajna | A **separate product** |
| Relationship to the agent | Prajna **runs** the agent; memory is state it owns | Observes agents it **does not run** |
| Why it exists | Recall across tasks | Evidence about work someone else executed |

**Why `Witness`.** It names the stance rather than the artifact, and the stance is the whole product:
a witness observes without participating, and tiers A/B/C ([S2](#s2--evidence-tiers-are-per-claim-never-per-bundle),
[S3](#s3--corroboration-never-upgrades-a-tier)) are exactly how much weight a given piece of
testimony carries. It is also plainly pronounceable, which `Prajna` is not — a lesson already paid
for in Prajna's own decision #77, where the brand
name went under review because a name not everyone can pronounce is a name not everyone can
recommend out loud.

**This does not violate [S8](#s8--no-domain-purchase-no-product-name-commitment-until-a-named-buyer-exists).**
S8 defers a *name commitment* — a domain, a trademark, a launch. This is a collision repair on a
working title, and `Witness` remains a working title under S8's terms. No domain has been bought.

**Why now.** The on-disk convention was `.smrithi/evidence/` — a path that lands in customers'
repositories and is committed alongside their changes. That is a burn-in string of exactly the class
`decisions.md` #77 froze bundle identifiers for. Nothing is released (version 0.1.0, no PyPI
package, no bundle in anyone's repository), so the rename is a `sed`. After the first external
bundle exists it is a migration of other people's git history.

**What changed:** the package dir (`smrithi/` → `witness/`), the distribution and console-script
names in `pyproject.toml`, the `.witness/` on-disk convention, the `witness-native` source value,
and every prose reference. Schemas carry no `$id` URLs, so no contract identifier moved.
60 tests, `scripts/validate.sh`, and the Claude Code conformance suite pass unchanged.

**Outstanding, and not done by this entry:** the GitHub repository is still named `smrithi` at
`github.com/prajna-evidence/smrithi`. [S1](#s1--witness-lives-in-its-own-org-in-one-private-repository-licence-deferred)
above now reads `…/witness` and is aspirational until `gh repo rename` is run. GitHub keeps a
redirect from the old path, so no clone breaks in the interim.

**The standing rule this establishes.** Witness and Prajna will keep accreting shared vocabulary —
that is what [S1](#s1--witness-lives-in-its-own-org-in-one-private-repository-licence-deferred)
anticipated when it chose a separate org. **A name used by either product is spent for both.**
Before taking a new one, check it against Prajna's reserved set — `Sutra`, `Niyama`, `Pramana`,
`Smriti`, `Prajna`, `Agent`, `Binding` — and against the names already spent here. Near-misses count;
`Smrithi`/`Smriti` was a near-miss and it cost a round of confusion.

## S17 — `witness verify` ships (B4); the schema's model-turns floor rule is retired in its favour

**Status:** locked, 2026-09-23. **Amends** `evidence-bundle.schema.json`'s `allOf`, which W1 froze
alongside the rest of the contract.

B4 (`witness verify`), W2b (the Claude Code transcript channel) and W4 (the GitHub Actions
attestation adapter) all landed together. Building W4 immediately exposed a bug in a rule W1 wrote
before either W2b or W4 existed to react against.

**The bug.** `evidence-bundle.schema.json` required `tier_floor: "C"` whenever `model_turns` was
empty, reasoning that a bundle which knows nothing about a model turn cannot honestly claim a floor
above C. That reasoning is correct about model turns and was wrong generalised to the whole bundle:
W4 can contribute a genuine tier B claim (a build-provenance gate and observation) to a bundle with
zero agent activity, and therefore an empty `model_turns`, and such a bundle legitimately has
`tier_floor: B` for that claim. The schema could not tell "no agent ran" apart from "an agent ran
and a foreign host recorded nothing about it" from the shape of `model_turns` alone — which is the
exact S2 mistake (collapsing per-claim tiers into one bundle-wide number) written into the schema
instead of the assembler that S2 was locked to prevent everywhere else.

**The fix.** The rule is removed. `evidence-bundle.schema.json` already documented, in `tier_floor`'s
own description, that this check properly belongs to a verifier and not the schema: *"A schema
cannot check that this equals the minimum of the per-section tiers. `witness verify` does, and a
bundle that overstates itself fails."* That verifier now exists (`witness/verify.py`,
`check_tier_floor`) and does the general version correctly: it recomputes the floor from every
section's own declared tier, independent of which adapter produced it, and fails a bundle that
overstates itself. The narrower, model-turns-specific schema rule was a stopgap for the period
before a verifier existed; that period is over.

**What did not change:** the sibling rule — `pramana` present implies `tier_floor: "A"` — stays in
the schema. It is not a proxy for a general check; it is unconditionally true regardless of which
adapter is in play, so there was nothing wrong with it to retire.

**Collateral:** `examples/invalid/empty-turns-claiming-tier-b.json` was deleted rather than kept
stale — its `$must_fail_because` became false the moment the rule it exercised was removed, and a
fixture asserting a false thing is worse than no fixture. The scenario it demonstrated is still a
real defect (a tier C hook source coexisting with a tier B source does not entitle a bundle to
declare `tier_floor: B` — the C source is still there) and is still caught, now by
`witness verify`'s general check rather than schema validation; the regression lives on as
`tests/test_verify.py::test_a_mixed_hook_and_attestation_bundle_cannot_claim_b_while_a_c_source_remains`.

**Why this is acceptable within `schema_version: 2` rather than forcing a version bump:** it is a
pure loosening. Every bundle that validated under the old, stricter rule still validates; the only
bundles newly accepted are ones the old rule rejected for a reason that no longer holds. The
additive-only rule (`SPEC.md` section 9) constrains what may be added or changed about a field's
shape; it does not forbid retiring a validation rule that was superseded by a verifier doing the
general form of the same check correctly.

**Amended 2026-09-25: `check_tier_floor` itself still had the retired rule.** This entry's own
words - "that verifier now exists ... and does the general version correctly" - were wrong when
written. `witness/verify.py`'s `check_tier_floor` carried an unconditional check, independent of
the general `declared != computed` comparison right below it: `if not model_turns and declared !=
C: fail`. That is the exact rule this entry says it retired, just moved from the schema into the
verifier instead of actually being replaced by the general form. It surfaced building the online
verifier test for S20: a real, legitimate build-only bundle (a github-actions attestation claim,
zero agent activity, `tier_floor: B`, and `computed` correctly agreeing at `B`) failed `witness
verify` anyway, on a note - "model_turns is empty but tier_floor is not C" - that this entry had
already declared invalid reasoning for a bundle in exactly this shape.

The fix removes that check entirely; the general `declared != computed` line was already sufficient
and remains. `tests/test_verify.py::test_empty_model_turns_must_not_claim_above_c` tested this dead
code specifically (asserting the note text contained "model_turns") and is replaced by
`test_empty_model_turns_with_only_a_tier_b_source_is_a_legitimate_floor_b`, which pins the actual
property: this exact bundle shape must report `tier_floor: {"ok": True}`. The negative case this
entry already added - a tier C source coexisting with a tier B claim - was never actually
depending on the removed check (the appended tier-B source in that test's fixture sat alongside a
tier-C source `build()` already produces by default, so `computed` caught it regardless); that
test, `test_a_mixed_hook_and_attestation_bundle_cannot_claim_b_while_a_c_source_remains`, needed no
change and is unaffected.

## S18 — `schemas/` ships as its own installed package, sibling to `witness`, not inside it

**Status:** locked, 2026-09-23. Closes the packaging gap RUN.md and S11 flagged as open.

`pip install witness` did not carry `schemas/` along: `witness verify` (B4) looks for it at
`WITNESS_SCHEMAS_DIR` or next to its own checkout, and a wheel built from `pyproject.toml` as it
stood after B4 packaged only the `witness*` tree — `schemas/` sits one level up, a sibling of
`witness/`, and setuptools does not include a directory it is not told is part of a package. The gap
was real, not theoretical: `pip install .` into a clean venv and running `witness verify` on a real
bundle with no `WITNESS_SCHEMAS_DIR` set failed with "cannot find schemas/", the exact failure
RUN.md's packaging note already predicted.

**The fix is not moving `schemas/` under `witness/`.** That was the obvious move and the wrong one:
**S9** put `SPEC.md`, `schemas/` and `conformance/` at the top level *on purpose*, "the contract —
splits out unchanged if ever needed" if the format is ever read by an outside party or sold
separately from the assembler. Nesting the contract inside the implementation package to solve a
packaging problem would quietly undo that seam.

**What shipped instead:** `pyproject.toml`'s `[tool.setuptools.packages.find]` now includes
`schemas*` alongside `witness*`, with `package-data` entries for `schemas` and `schemas.vendor`.
`schemas/` builds into the wheel as its own top-level distribution package — still a plain
directory in the source tree, still outside `witness/`, but now installed into site-packages next
to (not inside) the `witness` package. `witness/verify.py`'s `_schema_dir()` gained a third lookup,
after `WITNESS_SCHEMAS_DIR` and `ROOT/schemas`: `_installed_schema_dir()` resolves the installed
`schemas` package via `importlib.util.find_spec`, so a machine with nothing but `pip install
witness` and a bundle to check now works with no environment variable and no checkout.

**Amended 2026-09-25: renamed the installed package `schemas` → `witness_schemas`.** A second
review caught what the first pass missed: `schemas` is not a name Witness gets to claim uncontested
— a real, unrelated package is already published on PyPI under exactly that name (confirmed live,
not assumed: `pypi.org/pypi/schemas/json` resolves to "Python library for marshalling and
validation"). Two distributions both installing a top-level `schemas/` into the same environment is
a file collision at install time, not something `_installed_schema_dir()`'s existing guard (it
already checked for `evidence-bundle.schema.json` before trusting a resolved path, so a foreign
`schemas` package lacking that file was never silently trusted) can fully protect against — the
guard covers "resolved to the wrong content," not "pip refuses to install, or silently overwrites,
because two packages own the same site-packages directory."

The fix keeps the source-tree directory named `schemas/` — S9's reasoning is about that directory's
name and position, not about what the installed distribution is called — and renames only the
installed package, via `package-dir = {"witness_schemas" = "schemas"}`. `packages.find`'s glob
can't rename during discovery, so `pyproject.toml` switched from auto-discovery to an explicit
`packages` list for both `witness*` and the renamed `witness_schemas*`; the cost is that a future
new adapter package under `witness/adapters/` needs adding to that list by hand rather than being
picked up automatically. `_installed_schema_dir()` now calls `importlib.util.find_spec
("witness_schemas")`. Re-verified the full clean-venv proof from the original entry against the
renamed package: builds, installs with no leftover `schemas` name in site-packages, `witness
verify` passes with no `WITNESS_SCHEMAS_DIR` set.

**Verified, not asserted:** built the wheel with `python -m build`, installed it into a venv that
had never seen this checkout, and ran `witness verify` on a bundle produced by that same installed
`witness bundle`, against a real git repo, with `WITNESS_SCHEMAS_DIR` unset — schema check passes.
Reinstalled the pre-fix wheel into a second clean venv as a control: same command fails loudly with
the documented "cannot find schemas/" error, not a silent skip. `pytest` (140 tests) and
`scripts/validate.sh` both still pass under an editable install, where `ROOT/schemas` is found
first and the new lookup path is never exercised.

**What did not change:** `WITNESS_SCHEMAS_DIR` stays, for anyone who copies `schemas/` to a location
of their own choosing rather than installing the package — CI does not need it anymore, but the
override is not being removed.

## S19 — Stale raw captures are excluded from a bundle, at session granularity, bounded by `base`'s own commit time

**Status:** locked, 2026-09-25. Closes RUN.md section 7's "stale captures are attributed to the
wrong change" — reproduced there live: a January capture on an already-merged branch got folded
into a bundle for an unrelated same-day change, because `witness bundle` folded in *every* file
under `.witness/raw/*.jsonl` with no bound at all. The documented workaround was "remember to clear
`.witness/raw/` when you start a branch" — a real fix relocated onto the person least likely to
remember it, which is the failure mode this whole product exists to catch, just moved inside the
tool itself.

**The bound:** `bundle.assemble` now computes `since_epoch = gitrepo.committed_at(root, base_sha)`
(`git show -s --format=%ct`, a plain epoch integer - see its docstring for why not an ISO string)
and excludes any raw session file with no capture at or after it, before folding observations or
resolving transcript session ids. This is always a safe lower bound: a capture cannot be evidence
about work built on top of `base` if it predates `base` existing in this repository at all,
regardless of how old `base` itself is.

**Session granularity, not per-event.** The reproduced defect was a whole stale session lingering,
and a raw file is one session (`raw.append`'s own naming convention). Per-event filtering would
have to decide what a malformed line's timestamp is, which it structurally does not have -
`raw.read` returns `{"_malformed": line}` for those, by design, so gap-counting stays honest. Whole
files were the correct granularity for the defect actually reproduced.

**What this does not solve:** two stale sessions on the same real day as legitimate work, on an
unrelated branch, whose base also happens to be recent, is not caught by a pure time bound - closing
that needs session-to-branch attribution this format does not track. Time-bounding closes the
reproduced case and narrows the rest; it does not claim to close every case.

**Transparency, not just correctness:** `bundle.stale_raw_files(root, base)` is exposed separately
so a caller can name what was dropped rather than let it vanish silently - `witness bundle`'s CLI
now prints `note: <path> predates base and was excluded (RUN.md section 7)` to stderr for each one.

**Verified against the exact reproduction, not a proxy:** `tests/test_bundle.py` adds a fixture
capture timestamped `2020-01-01` against a `base` created at real test-run time - the same shape as
RUN.md's live repro - asserting it contributes zero observations and the bundle falls back to the
`witness-native/assembler` self-report, same as no capture at all. A companion test proves a capture
at exactly `base`'s own commit time is included (the boundary is inclusive), a mixed-directory test
proves a fresh session survives alongside an excluded stale one, and a transcript-channel test
proves a stale session id never even reaches `collect_model_turns` (S19 and W2b share the same
window - see `read_model_turns`). Fixed two existing tests whose fixtures constructed a git commit
at real wall-clock time alongside a fixed historical `captured_at` earlier than that: their `git()`
helper now pins `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` so the fixture's fictional clock is internally
consistent, which is what should have been true regardless of this change.

## S20 — `--online` is wired to a real verifier for the GitHub Actions attestation channel

**Status:** locked, 2026-09-25. Closes the gap RUN.md section 4 already documented: `witness verify
--online` re-fetches every tier B source, but `verify.ONLINE_VERIFIERS` shipped empty, so every
online check reported `unreachable` with reason "no online verifier registered" - true by
construction, and identical to what `--offline` already gives for free. `--online` meant nothing for
any real bundle this build could produce.

**What shipped:** `witness/adapters/githubactions/collect.py` gained `online_verify(source, bundle,
*, runner=None)` - the online half of SPEC.md section 6.2 for this channel. It re-fetches
`retrievable_from` (`GET repos/{repo}/attestations/{digest}`, the same call `collect_via_api`
already makes) and compares existence now against what the bundle's own observations claimed at
that url. `witness/verify.py` gained `_register_builtin_online_verifiers()`, called at the top of
`verify_online`, which lazily imports the adapter and registers it - lazily so an offline `witness
verify` never pays for importing subprocess-touching adapter code it will not use, and idempotently
(`setdefault`) so it never clobbers a verifier a caller (or a test) registered itself.

**Existence only, deliberately, per S6.** Re-checking a Sigstore signature online would need the
artifact bytes `collect_via_verify` required locally at collection time, which a later, separate
re-fetch does not have. `retrievable_from` names an existence-check endpoint and never promised
more than that, so `online_verify` does not either - a `build.attestation_verified` claim's
existence is re-confirmable; its Sigstore outcome is not, online, without reimplementing the trust
chain S6 already forbids reimplementing.

**Never guesses `contradicted` from an ambiguous signal.** `collect_via_api` does not distinguish
"GitHub authoritatively says not found" from "the `gh` call itself failed" (network, auth, rate
limit) - both come back as `record["error"]`. `online_verify` treats any such error as
`unreachable`, never `contradicted`. SPEC.md 6.2 is explicit that `unreachable` degrades and
`contradicted` fails the bundle; guessing at the ambiguous case would risk failing a bundle over
this verifier's own inability to reach GitHub; that is a `witness verify` bug wearing the costume of
an author's dishonesty.

**Building the end-to-end test surfaced two unrelated, real bugs already in the shipped W4 adapter**
- neither previously caught, because no existing test ran a real `bundle.assemble(...,
attestations=[...])` output through `verify_offline`/`verify_online`'s `ok` field; the only prior
coverage checked `report["schema"]["ok"]` alone:

1. `check_tier_floor` still carried the exact rule S17 says it retired - see S17's 2026-09-25
   amendment above. Any github-actions-only bundle failed `witness verify` outright until this was
   removed.
2. `witness/adapters/githubactions/normalize.py` recorded its `tokens`/`cost_usd` unavailability
   reasons at `payload.unavailable["/payload/tokens"]` and `["/payload/cost_usd"]` - a path that
   does not match what `witness/verify.py`'s `check_unavailable` looks for
   (`payload.unavailable["/tokens"]`, `["/cost_usd"]`, matching the convention
   `witness/adapters/claudecode/normalize.py` already uses correctly). Every github-actions bundle
   ever produced failed the unavailable-coverage check as a result. Fixed to match the existing,
   correct convention.

Both were genuinely pre-existing defects in a milestone already marked done (W4, 2026-09-23), not
introduced by this change; S20's own test (`test_verify_online_reaches_the_real_github_actions_
verifier_end_to_end`) is what exposed them, by being the first test to actually assert `report["ok"]`
on a real attestation bundle rather than only its schema validity.

**Known, stated limitation, not fixed here:** `verify_online` iterates `bundle["sources"]`, which
`_dedupe_sources` collapses to one entry per (host, channel, adapter_version) - a bundle with
multiple distinct attestation claims (different digests) for the same repo still gets only one
online re-check, for whichever `retrievable_from` survived deduplication. Widening the online path
to per-claim granularity is a real gap, and out of scope for "wire up a working verifier"; it is
named here rather than silently left for someone to discover the way the two bugs above were found.

## S21 — The repository is public; history squashed on publication

**Status:** locked, 2026-10-04. **Supersedes** S1's "private"; **closes** the debt S1 recorded.

`github.com/prajna-evidence/witness` is public under Apache-2.0 (S12). The pre-publication pass S1
required was run: links into private workspaces were removed, `SPEC.md` §10 now names the issue
tracker, and history was squashed to a single commit. The squash was required, not cosmetic: S14
stated that the removed pricing entry was gone from history, and it was not. Rationale from the
squashed commits survives here, which is what this file is for.

## S22 — Three verifier bypasses closed before publication; `repo.slug` widened

**Status:** locked, 2026-10-04. **Amends** S15 (recovery), S17 (floor computation) and S19
(online re-fetch). Normative in `SPEC.md` §6.1 and §6.2.

A security review run before publication found three ways a forged bundle passed `witness verify`.
Each was reproduced against the shipped code, then fixed with a regression test that fails without it:

1. **Floor computed from the summary, not the claims.** `check_tier_floor` read `sources` and
   `gates` only. Dropping tier C entries from `sources` while keeping the tier C observations
   produced a bundle that declared `tier_floor: B` and passed: S2's violation, through the one
   check meant to catch it. Observation tiers now count, and an observation whose source is
   missing from `sources` is reported.
2. **Online re-fetch was not bound to the subject.** `online_verify` re-fetched whatever repository
   `retrievable_from` named. Anyone can attest a digest in a repository they own, so a claim
   pointed there came back `confirmed`. The locator must now name exactly one `owner/name`, which
   must equal the repository from `repo.remote`. A mismatch is `contradicted`, an unbindable
   locator `unreachable`.
3. **Recovery was unbounded.** S15's dead-locator recovery searched all of HEAD's history, so a
   bundle naming a commit that never existed matched any version a file ever had, including
   content from before the change. Recovery now only considers commits after a reachable
   `base_commit`. A squash commit always descends from its base, so S15's case survives.

**Found alongside, and fixed in the same change:** the schema's `repo.slug` pattern
(`^[a-z0-9][a-z0-9-]*$`) rejected the `owner/name` that `gitrepo.slug` writes whenever a repository
has a remote, so every bundle from a real repository failed verification. No test repository had a
remote. The pattern is widened to `^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)?$`. That is additive under
§9: every value the old pattern accepted is still accepted.

