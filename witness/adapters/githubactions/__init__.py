"""GitHub Actions adapter: build-provenance attestations to observations (W4)."""

from .collect import collect_via_api, collect_via_verify, online_verify
from .normalize import MANIFEST, normalize_attestation

__all__ = ["MANIFEST", "normalize_attestation", "collect_via_api", "collect_via_verify", "online_verify"]
