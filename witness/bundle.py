"""Bundle assembly. Observations plus a git anchor in, one evidence bundle out.

This is the cold path. `capture` appends raw lines on every tool call and does nothing
else (S10); everything expensive happens here, once, at PR time.

THE ANCHORING PROBLEM THIS FILE EXISTS TO SOLVE
------------------------------------------------
A bundle anchored to a branch `commit_sha` becomes unverifiable the moment the PR is
squash-merged and the branch deleted - the SHA is unreachable and eventually collected.
At month fourteen that reads as evidence decay, which it is not: it is a bug wearing the
costume of the thing the tier model exists to make legible. Worse, it is not fixable
after the fact, because the bytes it pointed at are gone.

Git is content-addressed, so the fix is to anchor per claim rather than per bundle:

    claim                          anchor                        survives
    -------------------------------------------------------------------------------
    these file contents existed    sha256 of the bytes at        rebase, squash,
                                   `commit_sha`, read from the   cherry-pick, re-clone
                                   tree object
    the prior state was X          parent commit's tree sha      rebase onto same base
    this describes change Y        patch-id of the branch diff   rebase only - TIER C
    it landed as commit Z          merge commit sha, recorded    n/a, recorded after
                                   post-merge

`commit_sha` stays in the bundle as a *locator* (S15): useful while it lives, and its
death is reported as a dead locator rather than as a content failure, because the sha256
values are what actually carry the claim.

THREE THINGS THIS FILE MUST NOT DO
-----------------------------------
1. Read the working tree. Every hash comes from `gitrepo.read_at`, which reads the tree
   object at a commit. Hashing the checkout passes exactly once - the tree moves and
   later commits change the bytes - and an artifact that only verifies on the day it was
   made is not evidence. This is the shortcut that arrives under demo pressure.
2. Promote `patch_id`. It is stable across rebase and *not* across a squash of more than
   one commit, so it is a correlation hint recorded at tier C and never an identity.
3. Emit an aggregate grade. `tier_floor` is a floor - "nothing here is better attested
   than X" - computed from the tiers the bundle actually carries (S2, SPEC section 4.3).
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

from witness import __version__, gitrepo, raw, tiers, ulid
from witness.adapters import load

SCHEMA_VERSION = 2

#: Everything under here is this tool's own output, never part of the change being
#: described. Excluding the whole directory rather than just the bundle file is
#: deliberate: a second bundle, or a re-assembly after the first was committed, would
#: otherwise appear as a file the agent wrote. A bundle that hashes itself is the
#: self-reference failure, and it is easiest to reintroduce by narrowing this.
EXCLUDED_PREFIXES = (".witness/",)

COST_DISCLAIMER = (
    "Local estimate from a price table. The provider's invoice is authoritative."
)


class BundleError(RuntimeError):
    """Assembly could not proceed. Never raised to mean 'no observations'."""


def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_excluded(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in EXCLUDED_PREFIXES)


def _dedupe_sources(observations: list[dict]) -> list[dict]:
    """Distinct `source` blocks, in first-seen order.

    Keyed on host + channel + adapter_version rather than the whole block, because
    `collected_at` differs per observation and would defeat the deduplication it is not
    part of.
    """
    seen: dict[tuple, dict] = {}
    for obs in observations:
        source = obs.get("source") or {}
        key = (source.get("host"), source.get("channel"), source.get("adapter_version"))
        if key not in seen:
            seen[key] = dict(source)
    return list(seen.values())


def collect_files(root: Path, base: str, head: str) -> list[dict]:
    """Changed files with the sha256 of their bytes **as stored in the tree**.

    A deleted file is hashed at `base`, where its content still exists; everything else
    at `head`. Paths under `.witness/` are dropped - see EXCLUDED_PREFIXES.
    """
    out: list[dict] = []
    for entry in gitrepo.changed_files(root, base, head):
        path = entry["path"]
        if _is_excluded(path):
            continue
        at = base if entry["action"] == "deleted" else head
        out.append(
            {
                "path": path,
                "sha256": gitrepo.sha256_at(root, at, path),
                "action": entry["action"],
            }
        )
    return out


def _resolve_raw_paths(root: Path, raw_paths: "list[Path] | None") -> list[Path]:
    if raw_paths is not None:
        return raw_paths
    raw_root = raw.raw_dir(root)
    return sorted(raw_root.glob("*.jsonl")) if raw_root.is_dir() else []


def _parse_captured_at(value: "str | None") -> "float | None":
    if not value:
        return None
    try:
        return _dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc).timestamp()
    except ValueError:
        return None


def _has_capture_since(path: Path, since_epoch: float) -> bool:
    for capture in raw.read(path):
        if "_malformed" in capture:
            continue
        ts = _parse_captured_at(capture.get("captured_at"))
        if ts is not None and ts >= since_epoch:
            return True
    return False


def _in_window_raw_paths(
    root: Path, raw_paths: "list[Path] | None", since_epoch: "float | None"
) -> list[Path]:
    """Raw capture files, minus whole sessions with nothing captured at or after
    `since_epoch` (RUN.md section 7, "stale captures are attributed to the wrong
    change"). A session that predates the branch's own base cannot be evidence about
    work built on top of it - `since_epoch` is `base`'s own commit time, which is always
    a safe lower bound for that regardless of how long ago `base` itself was made.

    Filtered at file (session) granularity, not per event: the reproduced defect was a
    whole stale session lingering in `.witness/raw/`, and per-event filtering would have
    to decide what a malformed line's timestamp is, which it does not have.
    """
    paths = _resolve_raw_paths(root, raw_paths)
    if since_epoch is None:
        return paths
    return [p for p in paths if _has_capture_since(p, since_epoch)]


def stale_raw_files(
    root: Path, base: str, raw_paths: "list[Path] | None" = None
) -> list[Path]:
    """Raw capture files `assemble` will exclude as predating `base`, named so a caller
    (the CLI) can say what it dropped rather than let the exclusion happen silently."""
    since_epoch = gitrepo.committed_at(root, base)
    paths = _resolve_raw_paths(root, raw_paths)
    return [p for p in paths if not _has_capture_since(p, since_epoch)]


def read_observations(
    root: Path,
    adapter: str = "claudecode",
    raw_paths: "list[Path] | None" = None,
    since_epoch: "float | None" = None,
) -> dict[str, Any]:
    """Normalise every in-window raw capture file into one adapter result.

    Missing or empty capture files are not an error. A change made without an agent is a
    real thing to have evidence about - the bundle then says, truthfully, that no agent
    activity was observed, which is a stronger statement than refusing to produce one.
    """
    paths = _in_window_raw_paths(root, raw_paths, since_epoch)
    captures: list[dict] = []
    for path in paths:
        captures.extend(raw.read(path))
    return load(adapter).normalize_session(captures)


def collect_attestations(specs: "list[dict]", now: str) -> dict[str, list]:
    """Build-provenance observations and gates (W4), one per attestation spec.

    Each spec is `{"repo": "owner/name", "digest": "<sha256 hex, with or without the
    prefix>", "artifact": <path|oci ref>|None, "bundle_path": <path>|None}`. When an
    artifact or a downloaded bundle is given, `gh attestation verify` runs and its exit
    code becomes the recorded verified/failed outcome (the stronger claim, and a gate);
    otherwise only existence is checked via the REST API (still tier B, no gate - see
    githubactions/normalize.py's module docstring for why the two are not conflated).
    """
    from witness.adapters import githubactions

    observations: list[dict] = []
    gates: list[dict] = []
    for spec in specs:
        if spec.get("artifact") or spec.get("bundle_path"):
            record = githubactions.collect_via_verify(
                spec["repo"], spec["digest"], artifact_or_oci=spec.get("artifact"), bundle_path=spec.get("bundle_path")
            )
        else:
            record = githubactions.collect_via_api(spec["repo"], spec["digest"])
        result = githubactions.normalize_attestation(record, now)
        observations.append(result["observation"])
        if result["gate"] is not None:
            gates.append(result["gate"])
    return {"observations": observations, "gates": gates}


def read_model_turns(
    root: Path,
    adapter_module,
    raw_paths: "list[Path] | None" = None,
    since_epoch: "float | None" = None,
) -> dict[str, Any]:
    """Model turns from the transcript channel (W2b), when the adapter has one.

    Each raw capture file is named by session id (raw.append's convention), so the same
    files that feed the hook channel also name which transcripts to look for - and the
    same `since_epoch` window applies, so a stale session cannot contribute model turns
    just because its transcript file happens to still be reachable. An adapter with no
    `collect_model_turns` - anything but claudecode today - simply contributes none, and
    the bundle's `model_turns` stays `[]`, which is honest for a host that has no
    transcript concept at all.
    """
    collector = getattr(adapter_module, "collect_model_turns", None)
    if collector is None:
        return {"model_turns": [], "sources": []}
    session_ids = [path.stem for path in _in_window_raw_paths(root, raw_paths, since_epoch)]
    return collector(root, session_ids)


def assemble(
    root: "Path | str",
    base: "str | None" = None,
    head: str = "HEAD",
    adapter: str = "claudecode",
    raw_paths: "list[Path] | None" = None,
    pr_url: "str | None" = None,
    bundle_id: "str | None" = None,
    now: "str | None" = None,
    attestations: "list[dict] | None" = None,
) -> dict[str, Any]:
    """Build one evidence bundle. Pure with respect to the filesystem apart from reads."""
    root = Path(root)
    if not gitrepo.is_repo(root):
        raise BundleError(f"not a git repository: {root}")

    head_sha = gitrepo.resolve(root, head)
    base_sha = gitrepo.resolve(root, base) if base else gitrepo.infer_base(root, head_sha)
    if base_sha is None:
        raise BundleError(
            f"cannot determine a base for {head_sha[:12]}: it has no parent and no "
            "default branch shares an ancestor with it. Pass --base explicitly."
        )

    # A capture from before `base` existed cannot be evidence about work built on top of
    # it - see stale_raw_files' docstring and RUN.md section 7. `base_sha` is always a
    # real, already-resolved commit at this point, so this never fails where `assemble`
    # itself would otherwise succeed.
    since_epoch = gitrepo.committed_at(root, base_sha)

    normalized = read_observations(root, adapter=adapter, raw_paths=raw_paths, since_epoch=since_epoch)
    observations = normalized.get("observations") or []
    gates = normalized.get("gates") or []

    turns = read_model_turns(root, load(adapter), raw_paths=raw_paths, since_epoch=since_epoch)
    model_turns = [dict(turn, seq=i) for i, turn in enumerate(turns.get("model_turns") or [])]

    if attestations:
        attested = collect_attestations(attestations, now=now or _utc_now_iso())
        observations = observations + attested["observations"]
        gates = gates + attested["gates"]

    sources = _dedupe_sources(observations)
    # The transcript channel's source(s) are folded in the same deduplicated way as the
    # hook channel's, by (host, channel, adapter_version) - a session with no assistant
    # turns worth reporting contributes no source, per normalize_transcript.
    for extra in turns.get("sources") or []:
        key = (extra.get("host"), extra.get("channel"), extra.get("adapter_version"))
        if not any((s.get("host"), s.get("channel"), s.get("adapter_version")) == key for s in sources):
            sources.append(extra)

    # A bundle with no observations still needs a source: the assembler itself is one,
    # and saying so is how the reader learns that the agent channel was empty rather
    # than omitted. Tier C, because it is this tool reporting on itself.
    if not sources:
        sources = [
            {
                "host": "witness-native",
                "channel": "assembler",
                "tier": tiers.TIER_SELF_REPORTED,
                "collected_at": now or _utc_now_iso(),
                "adapter_version": f"witness/{__version__}",
            }
        ]

    # The floor spans only what carries a declared tier. `files` and `model_turns` have
    # no tier field in the schema, and inventing one for them would assert a claim the
    # bundle does not make.
    floor = tiers.tier_floor(
        [s["tier"] for s in sources if s.get("tier")]
        + [g["tier"] for g in gates if g.get("tier")]
    )

    unavailable: dict[str, str] = {
        "/cost": tiers.HOST_DOES_NOT_EMIT,
        "/redaction": tiers.NOT_APPLICABLE,
        "/memory": tiers.NOT_APPLICABLE,
        "/pramana": tiers.NOT_APPLICABLE,
    }
    unavailable.update(normalized.get("gates_unavailable") or {})

    branch = gitrepo.current_branch(root)
    # No `$schema_under_test` key. That is an `examples/` harness marker read by
    # scripts/validate.py to pick a schema, and the bundle schema is
    # `additionalProperties: false` - a real bundle carrying it is invalid.
    return {
        "schema_version": SCHEMA_VERSION,
        "id": bundle_id or ulid.new(),
        "generated_at": now or _utc_now_iso(),
        "generated_by": f"witness/{__version__}",
        "tier_floor": floor,
        "commit_sha": head_sha,
        "anchors": {
            "base_commit": base_sha,
            "base_tree": gitrepo.tree_of(root, base_sha),
            # Tier C by construction. Recorded, labelled, never used as an identity.
            "patch_id": gitrepo.patch_id(root, base_sha, head_sha),
            # Filled by `reconcile` once the change lands. Null is not an omission.
            "merge_commit": None,
        },
        "repo": {
            "slug": gitrepo.slug(root),
            "branch": branch or "HEAD",
            "remote": gitrepo.remote_url(root),
            "pr_url": pr_url,
        },
        "sources": sources,
        "observations": observations,
        # Populated from the transcript channel where the adapter has one (W2b).
        # Empty whenever no session transcript was found - a real and common case, not
        # a defect - and the schema permits that only when the floor is already C,
        # which stays true because the transcript channel is tier C too (S3).
        "model_turns": model_turns,
        "files": collect_files(root, base_sha, head_sha),
        "gates": gates,
        "cost": None,
        "redaction": None,
        "memory": None,
        "pramana": None,
        "unavailable": unavailable,
    }


def evidence_dir(root: "Path | str") -> Path:
    return Path(root) / ".witness" / "evidence"


def write(bundle: dict, root: "Path | str", out: "Path | None" = None) -> Path:
    """Write the bundle, named by its own id so a directory listing sorts by time."""
    target = out or evidence_dir(root) / f"{bundle['id']}.evidence.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def reconcile(bundle_path: "Path | str", merge_commit: str, root: "Path | str | None" = None) -> dict:
    """Record where the change landed, after the fact.

    THE STEP THAT MAKES THE ANCHOR COMPLETE. At PR time there is no merge commit to
    record, and by the time there is one the bundle has already been committed and
    reviewed. So the merge sha is written afterwards, in its own commit on the target
    branch, rather than being predicted.

    Rewriting a committed file is the hazard here, and it is bounded deliberately: this
    touches `anchors.merge_commit` and nothing else, and refuses when a different value
    is already recorded. Every content claim in the file is unchanged by it, so a
    verifier that saw the pre-reconciliation copy and the post- one reaches the same
    conclusion about the bytes.
    """
    path = Path(bundle_path)
    bundle = json.loads(path.read_text(encoding="utf-8"))
    anchors = bundle.get("anchors")
    if not isinstance(anchors, dict):
        raise BundleError(f"not an evidence bundle: {path}")

    if root is not None:
        merge_commit = gitrepo.resolve(Path(root), merge_commit)

    existing = anchors.get("merge_commit")
    if existing and existing != merge_commit:
        raise BundleError(
            f"{path} already records merge_commit {existing}; refusing to overwrite it "
            f"with {merge_commit}. A bundle records where its change landed once."
        )

    anchors["merge_commit"] = merge_commit
    path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return bundle
