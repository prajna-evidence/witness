"""Tier and reason-code constants, mirrored from schemas/common.schema.json.

Both enums are frozen for major version 1. A tier whose meaning drifts retroactively
falsifies every bundle already committed to a customer's git history, and there is no
recovery path from that, so `test_constants_match_schema` asserts these stay in step
with the schema rather than trusting anyone to remember.
"""

from __future__ import annotations

from typing import Final

TIER_ATTESTED: Final = "A"
TIER_HOST_ATTESTED: Final = "B"
TIER_SELF_REPORTED: Final = "C"

TIERS: Final = (TIER_ATTESTED, TIER_HOST_ATTESTED, TIER_SELF_REPORTED)

#: Worst-first, so `min(..., key=TIER_ORDER.index)` yields a floor.
TIER_ORDER: Final = (TIER_SELF_REPORTED, TIER_HOST_ATTESTED, TIER_ATTESTED)

HOST_DOES_NOT_EMIT: Final = "host_does_not_emit"
HOST_GATED: Final = "host_gated"
NOT_YET_AVAILABLE: Final = "not_yet_available"
PERMISSION_DENIED: Final = "permission_denied"
COLLECTION_FAILED: Final = "collection_failed"
OUT_OF_RETENTION: Final = "out_of_retention"
NOT_APPLICABLE: Final = "not_applicable"

REASON_CODES: Final = (
    HOST_DOES_NOT_EMIT,
    HOST_GATED,
    NOT_YET_AVAILABLE,
    PERMISSION_DENIED,
    COLLECTION_FAILED,
    OUT_OF_RETENTION,
    NOT_APPLICABLE,
)


def tier_floor(tiers: "list[str] | tuple[str, ...]") -> str:
    """Lowest tier present. Empty input is C: a bundle that observed nothing
    cannot claim to have attested anything."""
    if not tiers:
        return TIER_SELF_REPORTED
    return min(tiers, key=TIER_ORDER.index)
