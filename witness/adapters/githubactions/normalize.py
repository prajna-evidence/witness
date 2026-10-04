"""Turn one attestation collection record (collect.py) into an observation and,
when a verification outcome is actually known, a gate.

Pure: record in, observation/gate out - no subprocess, no network, matching every other
normaliser in this package. The distinction this file exists to preserve: an
`collect_via_api` record only knows the attestation EXISTS and is retrievable (still
tier B - SPEC.md section 4.2 asks only "can a verifier re-fetch it", not "did we
personally check the signature"); a `collect_via_verify` record additionally knows
whether it verified, and only that case gets a gate, because a gate decision Witness
did not actually observe would be exactly the fabrication SPEC.md section 3.2 forbids.
"""

from __future__ import annotations

import json
import pathlib
import uuid
from typing import Any

from witness import tiers

MANIFEST = json.loads((pathlib.Path(__file__).parent / "manifest.json").read_text())
ADAPTER_VERSION = f"{MANIFEST['adapter']}/{MANIFEST['version']}"
HOST = MANIFEST["host"]

NAMESPACE = uuid.UUID("2a6f3b8e-5c91-4a02-8e7d-1f9b6c3a04d5")


def _retrievable_from(repo: str, digest: str) -> str:
    return f"https://api.github.com/repos/{repo}/attestations/{digest}"


def _source(repo: str, digest: str, collected_at: str) -> dict[str, Any]:
    return {
        "host": HOST,
        "channel": "attestation",
        "tier": tiers.TIER_HOST_ATTESTED,
        "collected_at": collected_at,
        "retrievable_from": _retrievable_from(repo, digest),
        "adapter_version": ADAPTER_VERSION,
    }


def normalize_attestation(record: dict[str, Any], collected_at: str) -> dict[str, Any]:
    """One collection record (from either `collect_via_api` or `collect_via_verify`) to
    `{"observation": {...}, "gate": {...} | None}`.

    Every branch produces an observation, including "no attestation exists for this
    digest" - GitHub's API authoritatively answering that question is itself a tier B
    finding, re-fetchable by a verifier, and recording it is what lets a bundle say "we
    checked and it was not there" rather than being silent about having checked at all.
    `bundle.assemble` folds the observation into the bundle's main `observations` list,
    and its own `source` field is picked up into `sources` by the existing
    deduplication - no separate source-merging path needed, unlike `model_turns`, which
    is the one section with no per-item `source` of its own.
    """
    repo = record["repo"]
    digest = record["digest"]
    audit_id = str(uuid.uuid5(NAMESPACE, f"{repo}|{digest}|{collected_at}"))

    if "verified" in record:
        return _from_verify_record(record, repo, digest, audit_id, collected_at)
    return _from_api_record(record, repo, digest, audit_id, collected_at)


def _from_api_record(record: dict, repo: str, digest: str, audit_id: str, collected_at: str) -> dict[str, Any]:
    exists = record.get("exists", False)
    unavailable: dict[str, str] = {
        "/tokens": tiers.NOT_APPLICABLE,
        "/cost_usd": tiers.NOT_APPLICABLE,
    }
    payload: dict[str, Any] = {"repo": repo, "digest": digest, "exists": exists, "unavailable": unavailable}

    if not exists:
        code = tiers.COLLECTION_FAILED if record.get("error") else tiers.HOST_DOES_NOT_EMIT
        unavailable["/payload/predicate_types"] = code
        if record.get("error"):
            payload["error"] = record["error"]
        return {
            "observation": _observation(audit_id, collected_at, "build.attestation_absent", payload, repo, digest),
            "gate": None,
        }

    payload["predicate_types"] = record.get("predicate_types") or []
    payload["count"] = record.get("count", 0)
    return {
        "observation": _observation(audit_id, collected_at, "build.attestation_found", payload, repo, digest),
        # Existence alone is not a verification outcome - no gate. See module docstring.
        "gate": None,
    }


def _from_verify_record(record: dict, repo: str, digest: str, audit_id: str, collected_at: str) -> dict[str, Any]:
    verified = bool(record.get("verified"))
    payload: dict[str, Any] = {
        "repo": repo,
        "digest": digest,
        "verified": verified,
        "predicate_types": record.get("predicate_types") or [],
        "unavailable": {
            "/payload/tokens": tiers.NOT_APPLICABLE,
            "/payload/cost_usd": tiers.NOT_APPLICABLE,
        },
    }
    if record.get("workflow"):
        payload["workflow"] = record["workflow"]
    if not verified and record.get("error"):
        payload["error"] = record["error"]
        payload["unavailable"]["/payload/workflow"] = tiers.COLLECTION_FAILED

    return {
        "observation": _observation(audit_id, collected_at, "build.attestation_verified", payload, repo, digest),
        "gate": {
            "gate": "build-provenance",
            "decision": "approved" if verified else "denied",
            "actor": None,
            "at": collected_at,
            "reason": f"gh attestation verify against {repo}@{digest}",
            "tier": tiers.TIER_HOST_ATTESTED,
        },
    }


def _observation(audit_id: str, collected_at: str, event: str, payload: dict, repo: str, digest: str) -> dict[str, Any]:
    return {
        "audit_id": audit_id,
        # No session concept on this host; the repo+digest pair is the correlation key.
        "session_id": str(uuid.uuid5(NAMESPACE, f"{repo}|{digest}")),
        "timestamp": collected_at,
        "event": event,
        "actor": "host:github-actions",
        "trace_id": f"{repo}@{digest}",
        "task_id": None,
        "repo_id": None,  # journal-event requires a UUID here; the slug lives in payload["repo"]
        "phase": "build",
        "tokens": None,
        "cost_usd": None,
        "injected_units": None,
        "prev_hash": None,
        "entry_hash": None,
        "payload": payload,
        # Tier B even for an "absent" finding: GitHub's API authoritatively answering
        # "no attestation for this digest" is itself a re-fetchable third-party claim.
        "source": _source(repo, digest, collected_at),
    }
