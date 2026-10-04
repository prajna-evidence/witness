# Running Witness

How to install it, drive it end to end against a real repository, check that what it
produced is true, and wire it into a session, a git workflow and CI.

Every command and every number below was executed on 2026-09-21 against a sample
repository and a real (non-simulated) Claude Code session. Where a step has a sharp edge,
it is called out where you would hit it, not in a footnote.

---

## 1. Install

Witness is a Python 3.11+ package whose only runtime dependency is `jsonschema`.

```bash
pipx install /path/to/witness        # preferred: isolated, and puts `witness` on PATH
# or, for development:
python3 -m venv .venv && .venv/bin/pip install -e /path/to/witness
```

**`witness` must be on `PATH`.** The capture hook is installed as the bare string
`witness capture` on purpose — binding it to an absolute interpreter path would tie the
hook to one virtualenv and break silently the moment that virtualenv is rebuilt. `init`
checks and warns rather than repairing it:

```
warning: `witness` is not on PATH, so the hook will not fire.
```

A venv that is active in your shell is not enough: the hook runs in whatever environment
Claude Code hands it. Verify with `command -v witness` from a *new* shell.

---

## 2. The whole loop in six commands

```bash
cd your-repo
witness init                              # 1. install the capture hooks
#   ... run Claude Code normally ...      # 2. capture happens by itself
witness normalize .witness/raw/<id>.jsonl # 3. optional: look at what was captured
witness bundle                            # 4. assemble the evidence bundle
witness view .witness/evidence/<id>.evidence.json   # 5. render it for a human
git add .witness/evidence && git commit -m "evidence: ..."
#   ... PR is reviewed and merged ...
witness reconcile .witness/evidence/<id>.evidence.json --merge-commit <sha>
git commit -am "evidence: reconcile to merge commit"   # 6. and this commit is required
```

Steps 4 and 6 each produce a file you must commit yourself. Neither command commits for
you, and `reconcile` does not say so in its output — see §7.

### 2.1 `witness init`

```console
$ witness init
  added           PostToolUse
  added           PreToolUse
  added           SessionStart
  added           Stop
  added           UserPromptSubmit
wrote /your-repo/.claude/settings.json
```

It writes five hooks into the **project** settings file (`--local` writes
`.claude/settings.local.json` instead), and creates `.witness/.gitignore` holding `raw/`.

Three properties worth knowing:

- **Idempotent.** Run it twice and you get `already-present`, not a second hook. A
  duplicated hook would append every event twice — a false record even though nothing
  was fabricated.
- **Additive.** Hooks you wrote are preserved. `--uninstall` removes only entries whose
  command is exactly `witness capture`, and prunes the file back — tested with a foreign
  `PreToolUse` hook in place, which survived untouched.
- **Committed by default.** That is the auditable choice: a hook in git makes *"capture
  was enabled on this branch from this commit onward"* a fact with a history, not a claim
  about someone's laptop.

### 2.2 Capture happens by itself

Nothing to run. Every tool call appends one line to
`.witness/raw/<session-id>.jsonl`. The hot path does no parsing, no git, no schema work,
and never fails the agent it observes.

**`.witness/raw/` is gitignored and stays on the developer's machine.** This is the single
most important fact for integration planning: *CI cannot assemble a bundle*, because the
observations never leave the laptop. See §6.

### 2.3 `witness normalize` — look at the raw capture

Cold path, read-only, safe to run any time.

```console
$ witness normalize .witness/raw/3797c096-….jsonl > /tmp/norm.json
note: 10 tool call(s) have unknown outcomes; recorded, not dropped
```

Output keys: `observations`, `gates`, `gaps`, `gates_unavailable`, `malformed_lines`.
`normalize` output is **not** a bundle — it has no commit, no anchors and no tier floor —
and `witness view` refuses it by name (§7).

### 2.4 `witness bundle` — assemble

```console
$ witness bundle
/your-repo/.witness/evidence/01M31TW74FJ5X3PAYSY4RE8FA7.evidence.json
```

Useful flags:

| Flag | Effect |
|---|---|
| `--base <rev>` | pin the base; otherwise inferred (`origin/HEAD` → `origin/main`/`master` → first parent) |
| `--head <rev>` | default `HEAD` |
| `--stdout` | print instead of writing — the right way to inspect without touching the repo |
| `--out <path>` | write somewhere other than `.witness/evidence/<id>.evidence.json` |
| `--pr-url <url>` | record the PR this describes |

**Run `witness bundle` on a repo with a real `.gitignore` in place.** It hashes exactly
what `git diff --name-status` reports between base and head, so build artifacts that were
committed by accident appear in `files[]` as things the agent created. In the test run
`__pycache__/*.pyc` entries showed up for precisely this reason. The tool is right and the
repo was wrong, but an auditor reading the bundle does not make that distinction for you.

**Missing observations are not an error.** A change made with no agent produces a valid
bundle with `observations: []` and a single `witness-native / assembler` tier-C source —
saying truthfully that no agent activity was observed, which is a stronger statement than
refusing to produce anything:

```console
$ witness bundle --stdout          # in a repo with a hand-written commit
tier_floor      : C
observations    : 0
sources         : [{"host": "witness-native", "channel": "assembler", "tier": "C", …}]
```

### 2.5 `witness view` — render for a human

```console
$ witness view .witness/evidence/01M31TW74FJ5X3PAYSY4RE8FA7.evidence.json
/your-repo/.witness/evidence/01M31TW74FJ5X3PAYSY4RE8FA7.evidence.html
```

One self-contained HTML file — no external scripts, stylesheets, fonts or images, checked
by grepping the output for `http`. It can be attached to a ticket or opened offline by
someone who does not have the repository.

The page states its own limits at the top: *"Not verified in this view — this page renders
what the bundle asserts. It does not re-check any claim."* It is a renderer, not a
verifier, and does not pretend otherwise.

### 2.6 `witness reconcile` — after the change lands

At PR time there is no merge commit to record; by the time there is one the bundle is
already committed and reviewed. So the merge sha is written afterwards.

```console
$ witness reconcile .witness/evidence/01M31….evidence.json --merge-commit 4d86e21
$ git commit -am "evidence: reconcile bundle to its merge commit"   # REQUIRED
```

It touches `anchors.merge_commit` and nothing else, and refuses a second, different value:

```console
$ witness reconcile … --merge-commit 0000…
error: … already records merge_commit 4d86e21…; refusing to overwrite it with 0000….
       A bundle records where its change landed once.
```

---

## 3. What the bundle actually claims

From the test run, trimmed:

```json
{
  "schema_version": 2,
  "id": "01M31TW74FJ5X3PAYSY4RE8FA7",
  "tier_floor": "C",
  "commit_sha": "269a31ac…",                 // a LOCATOR, not the claim
  "anchors": {
    "base_commit": "59ee47f0…",
    "base_tree":   "4d895113…",
    "patch_id":    "acf18b9e…",              // tier C, correlation hint only
    "merge_commit": "4d86e212…"              // null until reconcile
  },
  "sources":      [ { "host": "claude-code", "channel": "hook", "tier": "C" } ],
  "observations": [ 33 records ],
  "gates":        [ { "gate": "tool-permission", "decision": "auto_approved",
                      "reason": "claude-code permission_mode=acceptEdits", "tier": "C" } ],
  "files":        [ 7 × { path, sha256, action } ],
  "model_turns":  [],                        // empty until the transcript channel (W2b)
  "cost": null, "redaction": null, "memory": null, "pramana": null,
  "unavailable": { "/cost": "host_does_not_emit", "/redaction": "not_applicable", … }
}
```

Read it as three separable claims:

| Claim | Carried by | Tier | Survives |
|---|---|---|---|
| these bytes existed | `files[].sha256`, computed from the git **tree object** | B | rebase, squash, cherry-pick, re-clone |
| the prior state was X | `anchors.base_tree` | B | rebase onto the same base |
| this is the same change | `anchors.patch_id` | **C** | rebase only — never an identity |
| the agent did these things | `observations[]`, `gates[]` | C | it is the agent reporting on itself |

`tier_floor` is a **floor** — *"nothing here is better attested than C"* — computed across
source and gate tiers only. It is never an aggregate grade, and `files[]` and
`model_turns[]` carry no per-row tier by design.

### Denials and dropped records look the same

The real session produced 11 `PreToolUse` Bash events and 1 `PostToolUse` — ten tool calls
were denied by the permission system, which fires no `PostToolUse`. Witness records each
as an honest observation rather than dropping it:

```json
{ "event": "tool.outcome_unknown",
  "payload": { "tool_name": "Bash",
               "error": "PreToolUse captured with no matching PostToolUse; the outcome of
                         this tool call is unknown to us",
               "unavailable": { "/payload/tool_response": "collection_failed" } } }
```

That is the correct shape, but note what it cannot say: *denied by a human* and *our
capture lost the record* both land as `collection_failed`. Expect an auditor to ask.

---

## 4. Verifying a bundle

`witness verify <bundle> [--root <repo>] [--online] [--json]` (milestone **B4**, SPEC.md §6).
Offline by default: schema validation, per-file content re-derivation from the git tree,
`tier_floor` honesty, `unavailable` coverage, and (tier A only) hash-chain continuity. Exit
code is 0 on pass, 1 on fail, 2 if the file is not a bundle at all.

```console
$ witness verify .witness/evidence/01M31TW74FJ5X3PAYSY4RE8FA7.evidence.json
mode: offline
  schema        ok
  locator commit_sha    reachable  919bc6a9de28437309f5116671ed58d6a6f9b193
  locator base_commit   reachable  91f13928317186ed17b0288688ab6152c7b28beb
  content       1/1 file claims re-verified
  tier_floor    declared=C computed=C ok
  unavailable   ok
  chain (tier A) not applicable

PASS
```

### The proof this exists for

Run against a bundle whose branch was then squash-merged, deleted, reflog-expired and
`git gc --prune=now`'d — reproduced live while building this command:

```console
$ witness verify .witness/evidence/….evidence.json --root /path/to/repo
mode: offline
  schema        ok
  locator commit_sha    DEAD (expected after a squash/rebase + delete)  b509256fee77…
  locator base_commit   reachable  59cc405fb030…
  content       1/1 file claims re-verified
  tier_floor    declared=C computed=C ok
  unavailable   ok
  chain (tier A) not applicable

PASS
```

The locator died; the content claim recovered from history (`gitrepo.find_containing_commit`)
and still matched; the bundle still passes. **A dead locator must never surface as a content
failure** — `witness/verify.py`'s test suite pins this directly
(`test_a_dead_locator_never_surfaces_as_a_content_failure`).

### `--online`

Additionally re-fetches every tier B source that carries `retrievable_from` and reports
`confirmed`, `contradicted`, `unreachable` or `out_of_retention` per SPEC.md §6.2. Only
`contradicted` fails the bundle; the other two degrade the claim rather than failing it — a
host's retention window closing is not the subject's fault. `verify.ONLINE_VERIFIERS` is a
registry a caller populates; a tier B source reports `unreachable` with the reason "no online
verifier registered for `<host>:<channel>`" whenever nothing is registered for its host and
channel. This is honest by construction: SPEC.md §6.1 is explicit that "could not check" must
never be silently folded into a pass.

**Resolved by S20**, landed 2026-09-25, for the GitHub Actions attestation channel: `witness
verify` now registers a real `online_verify` (in `witness/adapters/githubactions/collect.py`)
the first time `--online` runs, so a real attestation bundle gets `confirmed` or `contradicted`
rather than `unreachable` by default. It re-fetches existence only, never a Sigstore signature
(S6), and treats any `gh` failure as `unreachable` rather than guessing at `contradicted` from
an ambiguous signal. No other channel has an online verifier yet — the Claude Code hook and
transcript channels are tier C with no `retrievable_from` at all, so `--online` has nothing to
re-check for them by construction, not by omission.

### Schema validation

Folded into `witness verify` now — it validates against `evidence-bundle.schema.json` using
the same registry-building logic `scripts/validate.py` uses for `examples/`, so there is no
longer a separate hand-rolled path for checking a bundle you produced yourself.

---

## 5. Running the project's own tests

```bash
python3 -m pytest -q                 # 137 passed in ~30s
bash scripts/validate.sh             # schemas, examples, rejected-example corpus, vendored pin
bash conformance/claudecode/check.sh # byte-for-byte fixture reproduction
```

`scripts/validate.sh` also checks that the vendored `prajna-schemas` copies still match
upstream, so it needs the sibling checkout present.

---

## 6. Integration

Three layers, and only one of them can be automated on a server.

### 6.1 Session layer — Claude Code hooks (`witness init`)

Already covered. This is the only layer that can observe anything; everything downstream
reads what it wrote. Two constraints to plan around:

- **`witness` must be on `PATH` for the account running the agent.** Prefer `pipx`.
- **The raw file is per session id**, so one branch worked on across several sessions
  produces several files. `witness bundle` reads *all* of `.witness/raw/*.jsonl` and merges
  them with no filter on time or branch — so captures from an unrelated earlier branch are
  attributed to today's change. This is a correctness problem, not an ergonomic one; see §7.
  Until it is fixed, **clear `.witness/raw/` at the start of every branch**:

  ```bash
  git checkout -b feat/x && rm -f .witness/raw/*.jsonl
  ```

### 6.2 Git layer — assemble before the push

The bundle describes a commit range and must then itself be committed, so it is
necessarily a **separate commit on the branch**, made deliberately. A `pre-push` hook is
the right shape: it reminds, it does not block, and it never fails a push.

`.git/hooks/pre-push` (tested):

```bash
#!/usr/bin/env bash
set -euo pipefail
command -v witness >/dev/null || { echo "witness not on PATH; skipping evidence" >&2; exit 0; }
branch=$(git rev-parse --abbrev-ref HEAD)
[ "$branch" = "main" ] && exit 0
if compgen -G ".witness/evidence/*.evidence.json" >/dev/null; then
  echo "witness: bundle already present for this branch" >&2; exit 0
fi
out=$(witness bundle) || { echo "witness: assembly failed; push continues" >&2; exit 0; }
echo "witness: wrote $out — commit it before opening the PR" >&2
exit 0
```

```console
$ git push
witness: wrote /your-repo/.witness/evidence/01M31V0RYTAP2TAZENQD8WFD19.evidence.json
        — commit it before opening the PR
```

The awkwardness is real and inherent: you commit the bundle and push again. The
alternative — generating the bundle after the fact in CI — cannot work, for the reason in
§6.3. Teams that dislike the double push should call `witness bundle` explicitly as the
last step of the branch instead, and keep the hook only as a safety net.

Distribute hooks with `git config core.hooksPath .githooks` and commit `.githooks/pre-push`,
since `.git/hooks/` is not cloned.

### 6.3 CI layer — validate, never assemble

**CI cannot produce a bundle.** `.witness/raw/` is gitignored and never leaves the
developer's machine, so a CI run of `witness bundle` yields a bundle with zero
observations and a `witness-native / assembler` source — technically valid, and evidence of
nothing. CI's job is to check that the developer did the work:

```yaml
# .github/workflows/evidence.yml
name: evidence
on: pull_request
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }          # needed: the bundle anchors to the base commit
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install /path/to/witness
      - name: a bundle exists for this PR
        run: compgen -G '.witness/evidence/*.evidence.json' > /dev/null
      - name: every file hash re-derives from the PR head
        run: |
          for b in .witness/evidence/*.evidence.json; do
            witness verify "$b" || exit 1
          done                                # §4
```

**Packaging note.** `pip install witness` carries `schemas/` with it — not inside the `witness`
package, but as its own top-level `witness_schemas` distribution package (named that rather than
the generic `schemas` because a real, unrelated package already owns that name on PyPI), because S9
keeps the contract directories (`SPEC.md`, `schemas/`, `conformance/`) separate from the
implementation on purpose. `witness verify` looks for, in order: `WITNESS_SCHEMAS_DIR` if set, a
`schemas/` directory next to its own checkout, then the installed `witness_schemas` package
(decisions.md **S18**) — so the CI step
above needs no `WITNESS_SCHEMAS_DIR`, and neither does an auditor's machine with only `pip install
witness` and a copy of the bundle, no checkout at all. Set `WITNESS_SCHEMAS_DIR` explicitly only to
override with a `schemas/` copy of your own choosing; if none of the three is found, `witness
verify` fails loudly rather than silently skipping the check.

Post-merge reconciliation is the one thing CI *can* do end to end, because it needs only
the merge sha:

```yaml
# .github/workflows/reconcile.yml
name: reconcile
on:
  push: { branches: [main] }
jobs:
  reconcile:
    runs-on: ubuntu-latest
    permissions: { contents: write }
    steps:
      - uses: actions/checkout@v4
      - run: pip install /path/to/witness
      - run: |
          for b in .witness/evidence/*.evidence.json; do
            python3 -c "import json,sys; sys.exit(0 if json.load(open('$b'))['anchors']['merge_commit'] is None else 1)" \
              && witness reconcile "$b" --merge-commit "${{ github.sha }}"
          done
          git diff --quiet || {
            git config user.name  witness-bot
            git config user.email witness-bot@users.noreply.github.com
            git commit -am "evidence: reconcile to ${{ github.sha }}"
            git push
          }
```

Note this reconciles *every* unreconciled bundle to the current sha, which is correct only
if one PR lands at a time. Match it to your merge queue before using it.

---

## 7. Sharp edges found while testing

| | |
|---|---|
| **Stale captures are attributed to the wrong change.** | `witness bundle` folds in *every* `.witness/raw/*.jsonl` with no filter on time, branch or commit range. Reproduced: a capture from a January session on an already-merged branch was attributed to a hand-written `b.txt` change made today, in a bundle whose `files[]` correctly listed only `b.txt`. The bundle then asserts agent activity that did not produce the change it describes — the one class of error this format exists to prevent. **Resolved by S19**, landed 2026-09-25: `bundle.assemble` excludes any raw session file with no capture at or after `base`'s own commit time, at session (whole-file) granularity, and `witness bundle` now prints a stderr note naming what it excluded rather than dropping it silently. Time-bounding closes the reproduced case; it does not claim to catch two stale sessions on the same day as legitimate but unrelated work — see S19 for the stated limit. |
| **`reconcile` does not commit, and does not say so.** | It prints only the path. An unreconciled-then-forgotten bundle lands on `main` with `merge_commit: null`, and the anchor that survives squash is exactly the one that is missing. This was hit on the first attempt at the §4 proof. **Resolved 2026-09-25**: `reconcile` still does not commit — RUN.md §6.3's own CI recipe deliberately batches several bundles into one commit itself — but `witness reconcile` now prints a stderr reminder every time that the file was modified and needs a commit, so the "does not say so" half of this edge is closed even though the non-committing behaviour is by design. |
| **`witness bundle` is ~26 ms per changed file.** | `sha256_at` spawns one `git cat-file` per file. A 300-file change took **8.0 s**; a 5-file change, 0.43 s. A `git cat-file --batch` fed from stdin would make this one process, with no change to the "never read the working tree" invariant. |
| **`witness capture` costs ~60 ms per hook event.** | ~35 ms is interpreter startup; the other ~20 ms is `witness.cli` eagerly importing `bundle` → `gitrepo` (and `view`, `install`) just to append a line. Two events per tool call means ~120 ms of added latency per call. Lazy-importing the subcommand modules would cut a third of it. |
| **Everything under `.witness/` is excluded from `files[]`.** | Deliberate — a bundle that hashes itself is a self-reference failure — but it also means `.witness/.gitignore` is invisible in the record. |
| **`view` refuses non-bundles, correctly.** | Feeding it `normalize` output exits 2, writes no file, and names the confusion: *"Normalised observations are an input to a bundle, not a bundle … Assembling them into one is `witness bundle`."* |
| **`model_turns` was always `[]` at the time of this run.** | The hook channel records that tools ran, never what the model was asked; model id and token counts needed the transcript channel, which had not landed yet. **Resolved by W2b**, landed 2026-09-23: `witness bundle` now also reads each session's transcript (`~/.claude/projects/<cwd>/<session-id>.jsonl`) and populates `model_turns` with model id, token counts and effort when a transcript is found. Still tier C — the transcript is a second self-report from the same host, not a third party (S3) — and still `[]`, honestly, for a session whose transcript is missing. |

---

## 8. Measured, 2026-09-21

Sample repository: a 4-file Python service, one real Claude Code session
(`claude -p …`, `--permission-mode acceptEdits`), macOS, Python 3.13.

| | |
|---|---|
| Agent session wall time | 72 s |
| Hook events captured | 23 (1 SessionStart, 1 UserPromptSubmit, 15 Pre, 5 Post, 1 Stop) |
| Raw capture size | 26,453 bytes — 296 bytes/event at the bench |
| `witness capture` | median **59.8 ms**, p95 64.9 ms, max 112 ms (n=30, cold process) |
| Capture overhead over the session | ~1.4 s on 72 s ≈ **2%** |
| `witness normalize` | 0.08 s → 33 observations, 1 gate, 10 gaps |
| `witness bundle` (7 files) | 0.77 s → 41,414 bytes |
| `witness bundle` (5 files, this repo) | 0.43 s → 1,913 bytes |
| `witness bundle` (300 files) | **7.97 s** → 47,448 bytes |
| `witness view` | 0.08 s → 41,611 bytes HTML, 0 external references |
| Schema validation of the generated bundle | valid against `evidence-bundle.schema.json` |
| Re-verification after squash-merge + branch delete + `gc --prune=now` | **7/7** file hashes matched |
| Project test suite | 90 passed, 21.3 s |
