"""GitHub Actions attestation collection - the one place in this adapter allowed to
touch a subprocess or the network (SPEC.md section 7: an adapter's collection call is
the one permitted exception to "no network of its own").

Per decision S6, Witness does not re-derive build provenance or reimplement Sigstore's
trust chain. Both functions here are thin wrappers around a tool GitHub already ships
(the `gh` CLI) whose own exit code or API response IS the verification outcome - this
file's job is to shell out, parse defensively, and never invent a field `gh` did not
actually give us.

`runner` is injectable everywhere a subprocess would otherwise run, so tests exercise
the real parsing logic against fixture output without a network or a `gh` install.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
from typing import Any, Callable

from witness.gitrepo import github_repo

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _default_runner(args: list[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _normalize_digest(digest: str) -> str:
    return digest if digest.startswith("sha256:") else f"sha256:{digest}"


def collect_via_api(repo: str, digest: str, *, runner: "Runner | None" = None) -> dict[str, Any]:
    """Existence-only collection: does GitHub's attestations API know this digest.

    This alone is a tier B claim - a third party the subject does not control holds the
    record and a verifier can re-fetch it (`retrievable_from`) - even though it does not
    by itself assert the Sigstore signature was checked. `collect_via_verify` is the
    stronger claim, when the artifact bytes are available to check against.
    """
    digest = _normalize_digest(digest)
    run = runner or _default_runner
    proc = run(["gh", "api", f"repos/{repo}/attestations/{digest}"])

    if proc.returncode != 0:
        return {
            "repo": repo,
            "digest": digest,
            "exists": False,
            "error": (proc.stderr or proc.stdout or "gh api failed").strip(),
        }

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"repo": repo, "digest": digest, "exists": False, "error": f"unparsable response: {exc}"}

    attestations = payload.get("attestations") if isinstance(payload, dict) else None
    if not isinstance(attestations, list) or not attestations:
        return {"repo": repo, "digest": digest, "exists": False, "error": None}

    predicate_types: list[str] = []
    for entry in attestations:
        # Defensive: GitHub's exact nesting of the DSSE statement inside `bundle` is
        # not something this file asserts confident knowledge of. A surprise here
        # degrades to "unknown predicate type", never a crash. The DSSE envelope's
        # `payload` is base64 of the in-toto statement JSON, per the DSSE spec - not
        # raw JSON itself.
        try:
            raw_payload = base64.b64decode(entry["bundle"]["dsseEnvelope"]["payload"])
            statement = json.loads(raw_payload)
            predicate_types.append(statement.get("predicateType", ""))
        except Exception:  # noqa: BLE001
            continue

    return {
        "repo": repo,
        "digest": digest,
        "exists": True,
        "count": len(attestations),
        "predicate_types": [p for p in predicate_types if p],
        "error": None,
    }


def collect_via_verify(
    repo: str,
    digest: str,
    *,
    artifact_or_oci: "str | None" = None,
    bundle_path: "str | None" = None,
    runner: "Runner | None" = None,
) -> dict[str, Any]:
    """Run `gh attestation verify` and record its exit code as the verified/failed
    signal - the authoritative one, since gh performs the Sigstore trust-chain check we
    deliberately do not reimplement (S6). Requires either a local artifact/OCI
    reference or a downloaded bundle to verify against; a bare digest is not enough for
    `gh` to compute a digest of its own to compare."""
    if not artifact_or_oci and not bundle_path:
        raise ValueError("collect_via_verify needs artifact_or_oci or bundle_path")

    digest = _normalize_digest(digest)
    run = runner or _default_runner
    args = ["gh", "attestation", "verify", artifact_or_oci or "--", "--repo", repo, "--format", "json"]
    if bundle_path:
        args = ["gh", "attestation", "verify", artifact_or_oci or "-", "--repo", repo, "--bundle", bundle_path, "--format", "json"]
    proc = run(args)

    verified = proc.returncode == 0
    workflow = None
    predicate_types: list[str] = []
    try:
        results = json.loads(proc.stdout)
        for entry in results if isinstance(results, list) else []:
            statement = (entry or {}).get("verificationResult", {}).get("statement", {})
            ptype = statement.get("predicateType")
            if ptype:
                predicate_types.append(ptype)
            cert = (entry or {}).get("verificationResult", {}).get("signature", {}).get("certificate", {})
            workflow = workflow or cert.get("sourceRepositoryURI")
    except Exception:  # noqa: BLE001 - best-effort enrichment only; the exit code already carries the verdict
        pass

    return {
        "repo": repo,
        "digest": digest,
        "verified": verified,
        "predicate_types": predicate_types,
        "workflow": workflow,
        "error": None if verified else (proc.stderr or proc.stdout or "verification failed").strip(),
    }


#: Exactly `owner/name` (no extra path segments or query), so the repo compared against
#: the bundle is the repo the API call actually reaches. Dot-segments are rejected in
#: `_locator`, since a path like `a/..` would be normalised to somewhere else.
_RETRIEVABLE_FROM_RE = re.compile(
    r"^https://api\.github\.com/repos/(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
    r"/attestations/(?P<digest>sha256:[0-9a-f]+)$"
)


def _locator(url: str) -> "re.Match[str] | None":
    match = _RETRIEVABLE_FROM_RE.match(url)
    if match and any(part in (".", "..") for part in match["repo"].split("/")):
        return None
    return match



def _claimed_existence(bundle: dict, url: str) -> "bool | None":
    """What this bundle originally claimed at `url`, from its own observations.

    Existence, not verification: `build.attestation_verified` implies existence (`gh
    attestation verify` cannot succeed against nothing), but says nothing re-fetchable
    here about whether its Sigstore check would still pass - see `online_verify`.
    """
    for obs in bundle.get("observations") or []:
        source = obs.get("source") or {}
        if source.get("retrievable_from") != url:
            continue
        event = obs.get("event")
        if event == "build.attestation_absent":
            return False
        if event in ("build.attestation_found", "build.attestation_verified"):
            return True
    return None


def online_verify(
    source: dict, bundle: dict, subject_repo: "str | None", *, runner: "Runner | None" = None
) -> dict[str, Any]:
    """The online half of SPEC.md section 6.2 for this channel (decisions.md S19): the
    piece `verify.ONLINE_VERIFIERS` needed wired up before `--online` did anything for a
    real bundle from this adapter, registered lazily by `witness/verify.py`.

    Re-fetches `retrievable_from` - `GET repos/{repo}/attestations/{digest}`, the same
    call `collect_via_api` already makes - and compares existence now against what the
    bundle claimed. Existence only: re-checking a Sigstore signature would need the
    artifact bytes `collect_via_verify` required locally at collection time, which a
    later, separate re-fetch does not have, and `retrievable_from` never promised more
    than the API endpoint it names (S6 - Witness does not reimplement Sigstore).

    `collect_via_api` does not distinguish "GitHub authoritatively says not found" from
    "the `gh` call itself failed" (network, auth, rate limit) - both surface as
    `record["error"]`. Rather than guess, any error here degrades to `unreachable`
    instead of risking a false `contradicted`; the one outcome SPEC.md 6.2 requires this
    file get right is that `contradicted` never fires on an inconclusive signal.
    """
    url = source.get("retrievable_from") or ""
    match = _locator(url)
    if not match:
        return {"outcome": "unreachable", "reason": f"cannot parse retrievable_from: {url!r}"}

    # Anyone can attest a digest in a repository they own, so the locator is bound to
    # `subject_repo`: the repository of the checkout being verified, which the verifier
    # reads from its own clone. Never the bundle's `repo.remote` - the bundle's author
    # writes that, and would simply name their own repository there too.
    # GitHub owner and repository names are case-insensitive.
    if subject_repo is None:
        return {"outcome": "unreachable", "reason": "the checkout has no github.com remote to bind the locator to"}
    claimed_repo = github_repo((bundle.get("repo") or {}).get("remote"))
    if claimed_repo is not None and claimed_repo.lower() != subject_repo.lower():
        # A fork or mirror clone is a legitimate way to get here, so this is not
        # evidence of a lie - but nothing can be confirmed about a repository the
        # verifier is not looking at.
        return {
            "outcome": "unreachable",
            "reason": f"bundle is for {claimed_repo!r} but the checkout is {subject_repo!r}",
        }
    if match["repo"].lower() != subject_repo.lower():
        return {
            "outcome": "contradicted",
            "reason": f"locator names repository {match['repo']!r}, but the subject is {subject_repo!r}",
        }

    claimed = _claimed_existence(bundle, url)
    if claimed is None:
        return {"outcome": "unreachable", "reason": f"no observation in this bundle matches {url}"}

    record = collect_via_api(match["repo"], match["digest"], runner=runner)
    if record.get("error"):
        return {"outcome": "unreachable", "reason": record["error"]}

    if record["exists"] == claimed:
        return {"outcome": "confirmed"}
    return {
        "outcome": "contradicted",
        "reason": f"bundle claims exists={claimed}, re-fetch now says exists={record['exists']}",
    }
