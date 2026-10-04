"""`witness verify` — re-derive what a bundle claims, with the network disabled by default.

SPEC.md section 6. This is the check that matters: everything else in a bundle is
assertion, and this file is what a reader who does not trust the tool runs instead of
trusting it. RUN.md section 4 shipped a fifteen-line version of the content check ahead
of this file existing (milestone B4); this supersedes it with the full offline contract
and adds `--online`.

THE RULE THIS FILE EXISTS TO ENFORCE: a claim that could not be checked is reported as
such, never silently folded into a pass. `unverified-offline`, `unreachable` and
`out_of_retention` are outcomes, not degraded passes - SPEC.md section 6.1 says this
explicitly, because a verifier that treats "could not check" as "checked" is the
failure this whole design is organised against.

FIVE OFFLINE CHECKS (SPEC.md 6.1):
  1. schema        - the bundle validates against evidence-bundle.schema.json
  2. content       - every files[].sha256 matches the tree at a reachable anchor,
                      with locator death (S15) reported separately from a content
                      mismatch - they are different failures with different causes
  3. tier_floor    - equals the minimum of the per-section tiers; a bundle does not
                      get to overstate itself, and the schema's own allOf rules
                      (empty model_turns -> C, pramana present -> A) are re-checked
                      here because a schema cannot compute a minimum
  4. unavailable   - every null field this file knows to expect a reason for has one
                      from the closed list
  5. hash chain    - tier A only: prev_hash/entry_hash form one continuous chain
                      terminating at pramana.chain_head

ONLINE (SPEC.md 6.2) additionally re-fetches each tier B claim that carries a
`retrievable_from` locator and reports one of confirmed / contradicted / unreachable /
out_of_retention. Only `contradicted` fails a bundle - the other two degrade the claim
to tier C rather than failing it, because a host's retention policy is not the
subject's fault (SPEC.md 6.2).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import subprocess
from typing import Any, Callable

from witness import gitrepo, tiers

ROOT = pathlib.Path(__file__).resolve().parent.parent


class VerifyError(RuntimeError):
    """The bundle could not be read or is not shaped like a bundle at all.

    Distinct from a verification FAILURE: a malformed-JSON file or a document with no
    `anchors` object cannot even be checked, which is a different thing from being
    checked and found wanting.
    """


# ---- schema ------------------------------------------------------------------------


def _installed_schema_dir() -> pathlib.Path | None:
    """`schemas/` ships as its own top-level distribution package, installed under the
    name `witness_schemas` (pyproject.toml's `packages`/`package-dir`/`package-data`) -
    deliberately not moved under `witness/`, since S9 keeps the contract directories
    (`SPEC.md`, `schemas/`, `conformance/`) separate from the implementation so they can
    split out unchanged later. It is installed as `witness_schemas` rather than the
    generic `schemas` (decisions.md S18's amendment) because a real, unrelated `schemas`
    package already exists on PyPI - installing under that name risks colliding with it
    in a user's environment, silently or via a broken install, neither of which this
    file's own rule about failing loudly can protect against once the wrong package has
    already won `import schemas`. `witness_schemas` is not a plausible name for anyone
    else to have chosen. This is why `pip install witness` carries `schemas/` into
    site-packages as a sibling `witness_schemas` package rather than inside the
    `witness` package, and why it is found via import machinery rather than a path
    relative to this file.
    """
    spec = importlib.util.find_spec("witness_schemas")
    if spec is None or not spec.submodule_search_locations:
        return None
    for location in spec.submodule_search_locations:
        candidate = pathlib.Path(location)
        if (candidate / "evidence-bundle.schema.json").is_file():
            return candidate
    return None


def _schema_dir() -> pathlib.Path:
    """Locate schemas/, honouring WITNESS_SCHEMAS_DIR first for anyone who copied the
    directory somewhere of their own choosing, then a repo checkout (`ROOT/schemas`),
    then the installed `witness_schemas` package (decisions.md S18). Failing loudly
    here, rather than degrading to "schema check skipped", is deliberate: a verifier
    that silently drops a check is exactly the failure this file exists to prevent.
    """
    override = os.environ.get("WITNESS_SCHEMAS_DIR")
    if override:
        return pathlib.Path(override)
    candidate = ROOT / "schemas"
    if candidate.is_dir():
        return candidate
    installed = _installed_schema_dir()
    if installed is not None:
        return installed
    raise VerifyError(
        "cannot find schemas/ - set WITNESS_SCHEMAS_DIR to the directory containing "
        "evidence-bundle.schema.json"
    )


def _load_registry():
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    schema_dir = _schema_dir()
    registry = Registry()
    contents: dict[str, dict] = {}
    for path in sorted(schema_dir.rglob("*.schema.json")):
        rel = path.relative_to(schema_dir).as_posix()
        doc = json.loads(path.read_text(encoding="utf-8"))
        contents[rel] = doc
        resource = Resource.from_contents(doc, default_specification=DRAFT202012)
        registry = registry.with_resource(rel, resource)
        declared = doc.get("$id", "")
        if declared.startswith("http"):
            registry = registry.with_resource(declared, resource)
    return Draft202012Validator, registry, contents


def check_schema(bundle: dict) -> dict[str, Any]:
    Draft202012Validator, registry, contents = _load_registry()
    validator = Draft202012Validator(
        contents["evidence-bundle.schema.json"],
        registry=registry,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    errors = sorted(validator.iter_errors(bundle), key=lambda e: list(e.path))
    return {
        "ok": not errors,
        "errors": [
            {"path": "/".join(str(p) for p in e.path) or "(root)", "message": e.message}
            for e in errors
        ],
    }


# ---- locators (S15) ------------------------------------------------------------------


def check_locators(bundle: dict, root: pathlib.Path) -> dict[str, Any]:
    """Reachability of every named commit, reported separately from content (S15).

    A dead locator is the normal, expected shape of an old bundle after a squash merge
    and branch deletion - it is not a content failure and must never be reported as one.
    """
    anchors = bundle.get("anchors") or {}
    out: dict[str, Any] = {}
    for key, sha in (
        ("commit_sha", bundle.get("commit_sha")),
        ("base_commit", anchors.get("base_commit")),
        ("merge_commit", anchors.get("merge_commit")),
    ):
        if not sha:
            out[key] = None
            continue
        out[key] = {"sha": sha, "reachable": gitrepo.exists(root, sha)}
    return out


# ---- content (SPEC 6.1.2, S15) ------------------------------------------------------


def _check_file(root: pathlib.Path, entry: dict, commit_sha: str, base_commit: "str | None", merge_commit: "str | None") -> dict[str, Any]:
    path = entry["path"]
    expected = entry["sha256"]
    action = entry["action"]

    if action == "deleted":
        direct_anchor, anchor_kind = base_commit, "base_commit"
    else:
        direct_anchor, anchor_kind = (merge_commit, "merge_commit") if merge_commit else (commit_sha, "commit_sha")

    if direct_anchor and gitrepo.exists(root, direct_anchor):
        try:
            actual = gitrepo.sha256_at(root, direct_anchor, path)
        except gitrepo.GitError:
            actual = None
        if actual is not None:
            # A reachable, disagreeing anchor is a genuine content failure. Falling back
            # to history search here would let an altered file hide behind an unrelated
            # older commit that happens to match - recovery is only for a DEAD locator,
            # never for a live one that disagrees.
            outcome = "match" if actual == expected else "mismatch"
            return {"path": path, "action": action, "outcome": outcome, "checked_at": anchor_kind, "commit": direct_anchor}

    # The direct anchor is dead or does not hold this path. Recovery: the content may
    # still be reachable from HEAD under a different commit (gitrepo.find_containing_commit),
    # which is exactly the case a squash-merge-then-delete produces. Not attempted for
    # `deleted` files: their content only ever lived at the base, and searching HEAD's
    # history for a path that was removed is not the same question.
    #
    # Bounded to commits after a reachable base_commit. Unbounded, a bundle could name
    # a commit that never existed and have any historical version of a file "match" -
    # including content from before the change it describes. A squash commit is always
    # a descendant of the base it was taken against, so the legitimate case survives.
    # No reachable base (null, or itself dead) means no bound, so no recovery.
    if action != "deleted" and base_commit and gitrepo.exists(root, base_commit):
        recovered = gitrepo.find_containing_commit(root, path, expected, after=base_commit)
        if recovered:
            return {"path": path, "action": action, "outcome": "match", "checked_at": "recovered", "commit": recovered}

    return {"path": path, "action": action, "outcome": "absent", "checked_at": anchor_kind, "commit": direct_anchor}


def check_content(bundle: dict, root: pathlib.Path) -> dict[str, Any]:
    anchors = bundle.get("anchors") or {}
    results = [
        _check_file(root, entry, bundle["commit_sha"], anchors.get("base_commit"), anchors.get("merge_commit"))
        for entry in bundle.get("files") or []
    ]
    matched = sum(1 for r in results if r["outcome"] == "match")
    return {
        "results": results,
        "matched": matched,
        "total": len(results),
        "ok": matched == len(results),
    }


# ---- tier_floor honesty (SPEC 6.1.3, S2) --------------------------------------------


def check_tier_floor(bundle: dict) -> dict[str, Any]:
    declared = bundle.get("tier_floor")
    sources = bundle.get("sources") or []
    observation_sources = [o.get("source") or {} for o in bundle.get("observations") or []]
    # Observations are where each claim's tier actually lives; `sources` is only their
    # deduplicated summary. Computing the floor from the summary alone let a bundle drop
    # its tier C entries from `sources` while keeping the tier C observations, and pass
    # with an overstated floor - the S2 violation this check exists to catch.
    section_tiers = (
        [s["tier"] for s in sources if s.get("tier")]
        + [g["tier"] for g in bundle.get("gates") or [] if g.get("tier")]
        + [s["tier"] for s in observation_sources if s.get("tier")]
    )
    computed = tiers.tier_floor(section_tiers)

    notes: list[str] = []
    listed = {(s.get("host"), s.get("channel"), s.get("tier")) for s in sources}
    unlisted = sorted(
        {(s.get("host"), s.get("channel"), s.get("tier")) for s in observation_sources} - listed,
        key=str,
    )
    for host, channel, tier in unlisted:
        notes.append(f"observation source {host}:{channel} (tier {tier}) is missing from sources")
    # `pramana` present -> A is the one schema-level allOf rule that survived S17: it is
    # unconditionally true regardless of adapter, not a proxy for a general check, so it
    # is re-checked here too. Its sibling - empty model_turns -> C - is deliberately
    # NOT re-checked here: S17 retired it because it is wrong in general (a build-only
    # tier B bundle can legitimately have zero agent activity and empty model_turns),
    # and the `declared != computed` check below already catches the real defect that
    # rule was chasing - a tier C source coexisting with a tier B claim - without the
    # false positive. Re-adding a model_turns-specific check here would be the exact
    # regression S17 fixed, just moved from the schema into this function.
    if bundle.get("pramana") is not None and declared != tiers.TIER_ATTESTED:
        notes.append("pramana is present but tier_floor is not A")
    if declared != computed:
        notes.append(f"declared tier_floor {declared!r} does not equal the computed floor {computed!r}")

    return {"declared": declared, "computed": computed, "ok": not notes, "notes": notes}


# ---- unavailable coverage (SPEC 3.2, 6.1.4) -----------------------------------------

#: Bundle-level fields that are legitimately null on every non-tier-A bundle, and MUST
#: therefore carry a reason at the bundle's top-level `unavailable` map when null.
_BUNDLE_NULLABLE_FIELDS = ("cost", "redaction", "memory", "pramana")

#: Observation-payload fields the claudecode adapter (and any adapter at tier C) is
#: known to null routinely. Scoped to what SPEC.md section 3.2's worked example and the
#: shipped adapters actually null, rather than walking the schema generically - a
#: generic walk would have to know which nulls are "a reader would otherwise expect
#: populated" and which are optional, and the schema does not say.
_OBSERVATION_NULLABLE_FIELDS = ("tokens", "cost_usd", "phase")


def check_unavailable(bundle: dict) -> dict[str, Any]:
    top = bundle.get("unavailable") or {}
    missing: list[str] = []

    for field in _BUNDLE_NULLABLE_FIELDS:
        if bundle.get(field) is None and f"/{field}" not in top:
            missing.append(f"/{field}")

    for obs in bundle.get("observations") or []:
        payload = obs.get("payload") or {}
        local = payload.get("unavailable") or {}
        audit_id = obs.get("audit_id", "?")
        for field in _OBSERVATION_NULLABLE_FIELDS:
            if obs.get(field) is None and f"/{field}" not in local:
                missing.append(f"observations[{audit_id}]/{field}")

    bad_codes = [
        (path, code)
        for path, code in top.items()
        if code not in tiers.REASON_CODES
    ]

    return {"ok": not missing and not bad_codes, "missing": missing, "bad_codes": bad_codes}


# ---- tier A hash chain (SPEC 6.1.5) --------------------------------------------------


def _canonical_row(observation: dict) -> str:
    row = {k: v for k, v in observation.items() if k not in ("prev_hash", "entry_hash")}
    return json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _entry_hash(observation: dict) -> str:
    """sha256(audit_id || prev_hash || canonical_json(row)), per
    schemas/vendor/journal-event.schema.json's `entry_hash` description."""
    prev = observation.get("prev_hash") or ""
    material = f"{observation['audit_id']}{prev}{_canonical_row(observation)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def check_chain(bundle: dict) -> dict[str, Any]:
    pramana = bundle.get("pramana")
    tier_a = [o for o in bundle.get("observations") or [] if (o.get("source") or {}).get("tier") == tiers.TIER_ATTESTED]

    if pramana is None and not tier_a:
        return {"applicable": False, "ok": True}

    if pramana is None or not tier_a:
        # One half of tier A present without the other is a bundle that is either
        # under- or over-claiming, and it is this check's job to say which.
        return {
            "applicable": True,
            "ok": False,
            "detail": "pramana section and tier-A observations must both be present or both absent",
        }

    ordered = sorted(tier_a, key=lambda o: o["audit_id"])
    prev = None
    broken: "str | None" = None
    for obs in ordered:
        if obs.get("prev_hash") != prev:
            broken = obs["audit_id"]
            break
        computed = _entry_hash(obs)
        if obs.get("entry_hash") != computed:
            broken = obs["audit_id"]
            break
        prev = computed

    terminates = broken is None and prev == pramana.get("chain_head")
    return {
        "applicable": True,
        "ok": terminates,
        "broken_at": broken,
        "terminates_at_chain_head": terminates,
    }


# ---- tier B claim labelling (SPEC 6.1: "MUST report tier B claims as unverified-offline,
# never as passing") -------------------------------------------------------------------


def _tier_b_claims(bundle: dict) -> "list[dict[str, Any]]":
    claims: list[dict[str, Any]] = []
    for s in bundle.get("sources") or []:
        if s.get("tier") == tiers.TIER_HOST_ATTESTED:
            claims.append({"kind": "source", "host": s.get("host"), "channel": s.get("channel"), "retrievable_from": s.get("retrievable_from")})
    for i, g in enumerate(bundle.get("gates") or []):
        if g.get("tier") == tiers.TIER_HOST_ATTESTED:
            claims.append({"kind": "gate", "gate": g.get("gate"), "index": i})
    return claims


def check_tier_b_claims(bundle: dict) -> "list[dict[str, Any]]":
    """Every tier B claim, unconditionally labelled `unverified-offline`.

    This exists so the report is explicit about what offline mode did NOT check, not
    just silent about it - SPEC.md section 6.1 is explicit that a verifier which treats
    "could not check" as "checked" is the failure this whole design is organised
    against. `verify_online` overwrites these with a real outcome per claim.
    """
    return [{**claim, "outcome": "unverified-offline"} for claim in _tier_b_claims(bundle)]


# ---- offline entry point ------------------------------------------------------------


def load_bundle(path: "str | pathlib.Path") -> dict:
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerifyError(f"cannot read {path}: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("anchors"), dict):
        raise VerifyError(f"not an evidence bundle: {path}")
    return doc


def verify_offline(bundle: dict, root: "pathlib.Path | str") -> dict[str, Any]:
    root = pathlib.Path(root)
    schema = check_schema(bundle)
    locators = check_locators(bundle, root)
    content = check_content(bundle, root)
    floor = check_tier_floor(bundle)
    unavailable = check_unavailable(bundle)
    chain = check_chain(bundle)
    tier_b_claims = check_tier_b_claims(bundle)

    return {
        "mode": "offline",
        "schema": schema,
        "locators": locators,
        "content": content,
        "tier_floor": floor,
        "unavailable": unavailable,
        "chain": chain,
        "tier_b_claims": tier_b_claims,
        "ok": schema["ok"] and content["ok"] and floor["ok"] and unavailable["ok"] and chain["ok"],
    }


# ---- online (SPEC 6.2) ---------------------------------------------------------------

#: One entry per (host, channel) this build knows how to re-fetch. Deliberately a
#: closed, explicit table rather than a generic "GET retrievable_from and diff" -
#: what "confirmed" means is specific to the claim shape of each source, and guessing
#: at that generically is how a verifier starts reporting false confirmations.
OnlineVerifier = Callable[[dict, dict], dict]
ONLINE_VERIFIERS: "dict[tuple[str, str], OnlineVerifier]" = {}


def register_online_verifier(host: str, channel: str, fn: OnlineVerifier) -> None:
    ONLINE_VERIFIERS[(host, channel)] = fn


def _register_builtin_online_verifiers() -> None:
    """Registers the online verifiers this build ships (decisions.md S19), lazily: an
    eager import at module load would pull the GitHub Actions adapter's subprocess-
    touching `collect.py` into every offline `witness verify`, for a registration that
    invocation would never use. Idempotent - re-registering the same (host, channel)
    just overwrites it with an equal function - so calling this on every `--online` run
    is not a "only once" hazard, and it does not shell out to `gh` by itself; only
    actually calling the registered function does.
    """
    from witness.adapters.githubactions import online_verify as _github_actions_online_verify

    ONLINE_VERIFIERS.setdefault(("github-actions", "attestation"), _github_actions_online_verify)


def _online_check_source(source: dict, bundle: dict) -> dict[str, Any]:
    if source.get("tier") != tiers.TIER_HOST_ATTESTED:
        return {"skipped": "not tier B"}
    if not source.get("retrievable_from"):
        return {"outcome": "unreachable", "reason": "tier B source carries no retrievable_from locator"}
    key = (source.get("host"), source.get("channel"))
    verifier = ONLINE_VERIFIERS.get(key)
    if verifier is None:
        return {"outcome": "unreachable", "reason": f"no online verifier registered for {key[0]}:{key[1]}"}
    try:
        return verifier(source, bundle)
    except Exception as exc:  # noqa: BLE001 - a re-fetch failing must degrade, never crash verify
        return {"outcome": "unreachable", "reason": f"re-fetch failed: {exc}"}


def verify_online(bundle: dict, root: "pathlib.Path | str") -> dict[str, Any]:
    """Offline report, plus a re-fetch attempt for every tier B source.

    `contradicted` is the only online outcome that fails the bundle (SPEC 6.2).
    `unreachable` and `out_of_retention` degrade the claim, they do not fail it - a
    host's retention window closing is not evidence the subject lied.
    """
    _register_builtin_online_verifiers()
    report = verify_offline(bundle, root)
    online = [
        {"source": {"host": s.get("host"), "channel": s.get("channel")}, **_online_check_source(s, bundle)}
        for s in bundle.get("sources") or []
        if s.get("tier") == tiers.TIER_HOST_ATTESTED
    ]
    contradicted = [o for o in online if o.get("outcome") == "contradicted"]

    # Sources get their `unverified-offline` placeholder replaced by the real outcome
    # just computed. Gates keep it: there is no per-gate online re-verification path
    # today (ONLINE_VERIFIERS is keyed by source host:channel), and that limit is
    # reported rather than papered over - the whole point of this label.
    by_key = {(o["source"]["host"], o["source"]["channel"]): o for o in online}
    for claim in report["tier_b_claims"]:
        if claim["kind"] == "source":
            match = by_key.get((claim["host"], claim["channel"]))
            if match:
                claim["outcome"] = match.get("outcome", match.get("skipped", "unreachable"))

    report["mode"] = "online"
    report["online"] = online
    report["ok"] = report["ok"] and not contradicted
    return report


def verify_file(path: "str | pathlib.Path", root: "pathlib.Path | str", online: bool = False) -> dict[str, Any]:
    bundle = load_bundle(path)
    return verify_online(bundle, root) if online else verify_offline(bundle, root)
