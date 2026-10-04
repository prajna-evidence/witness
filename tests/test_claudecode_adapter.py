"""Adapter behaviour that the conformance kit cannot express.

check.sh pins the exact bytes of known inputs. These tests pin the properties that
must hold for inputs nobody has written a fixture for yet.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from witness import raw, tiers  # noqa: E402
from witness.adapters.claudecode import MANIFEST, normalize_session  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "conformance" / "claudecode" / "fixtures"

sys.path.insert(0, str(ROOT / "scripts"))
from validate import build_registry  # noqa: E402


def _validator(schema_name: str) -> Draft202012Validator:
    registry, contents = build_registry()
    return Draft202012Validator(
        contents[schema_name], registry=registry, format_checker=Draft202012Validator.FORMAT_CHECKER
    )


def _normalize(name: str) -> dict:
    return normalize_session(raw.read(FIXTURES / f"{name}.jsonl"))


# --- the contract ---------------------------------------------------------------


@pytest.mark.parametrize("fixture", [p.stem for p in sorted(FIXTURES.glob("*.jsonl"))])
def test_every_observation_validates(fixture: str) -> None:
    validator = _validator("observation.schema.json")
    for obs in _normalize(fixture)["observations"]:
        errors = sorted(validator.iter_errors(obs), key=lambda e: list(e.path))
        assert not errors, f"{fixture}: {[e.message for e in errors]}"


def test_manifest_validates() -> None:
    validator = _validator("adapter-manifest.schema.json")
    assert not list(validator.iter_errors(MANIFEST))


def test_constants_match_schema() -> None:
    """The frozen enums live in two places; this is what keeps them one thing."""
    common = json.loads((ROOT / "schemas" / "common.schema.json").read_text())
    assert tuple(common["$defs"]["tier"]["enum"]) == tiers.TIERS
    assert tuple(common["$defs"]["reasonCode"]["enum"]) == tiers.REASON_CODES


# --- the properties the product depends on ---------------------------------------


def test_a_missing_outcome_is_recorded_not_dropped() -> None:
    result = _normalize("gap-missing-posttooluse")
    gap = [o for o in result["observations"] if o["event"] == "tool.outcome_unknown"]
    assert len(gap) == 1, "an unmatched PreToolUse must survive as a hole in the record"
    assert gap[0]["payload"]["unavailable"]["/payload/tool_response"] == tiers.COLLECTION_FAILED
    assert gap[0]["payload"]["error"], "collection_failed must carry an error string"
    assert result["gaps"] == ["toolu_01CCC"]


def test_phase_is_never_inferred_from_a_shell_command() -> None:
    """`terraform apply` is obviously a deploy. We still do not say so: the host did
    not tell us, and a guess promoted into evidence is the whole failure mode."""
    result = _normalize("gap-missing-posttooluse")
    bash = [o for o in result["observations"] if o["payload"].get("tool_name") == "Bash"]
    assert bash, "fixture should contain a Bash tool call"
    for obs in bash:
        assert obs["phase"] is None
        assert obs["payload"]["unavailable"]["/phase"] == tiers.HOST_DOES_NOT_EMIT


def test_interactive_mode_does_not_manufacture_an_approval() -> None:
    result = _normalize("happy-path")
    assert result["gates"] == []
    assert result["gates_unavailable"] == {"/gates": tiers.HOST_DOES_NOT_EMIT}


def test_unattended_mode_is_a_positive_finding() -> None:
    result = _normalize("unattended-bypass")
    assert len(result["gates"]) == 1
    gate = result["gates"][0]
    assert gate["decision"] == "auto_approved"
    assert gate["actor"] is None, "auto_approved means no human acted; naming one would be false"
    assert "bypassPermissions" in gate["reason"]


def test_everything_is_tier_c_and_carries_no_locator() -> None:
    for fixture in (p.stem for p in FIXTURES.glob("*.jsonl")):
        for obs in _normalize(fixture)["observations"]:
            assert obs["source"]["tier"] == tiers.TIER_SELF_REPORTED
            assert obs["source"]["retrievable_from"] is None


def test_tokens_and_cost_are_null_with_a_reason_never_zero() -> None:
    for obs in _normalize("happy-path")["observations"]:
        assert obs["tokens"] is None
        assert obs["cost_usd"] is None
        assert obs["payload"]["unavailable"]["/tokens"] == tiers.HOST_DOES_NOT_EMIT


def test_malformed_lines_are_counted_not_swallowed() -> None:
    result = _normalize("malformed-line")
    assert result["malformed_lines"] == 1


def test_normalisation_is_deterministic() -> None:
    """Conformance demands byte-for-byte reproduction, which requires no clock and no
    randomness anywhere in the path."""
    first = json.dumps(_normalize("happy-path"), sort_keys=True)
    second = json.dumps(_normalize("happy-path"), sort_keys=True)
    assert first == second


# --- the hot path -----------------------------------------------------------------


def test_capture_never_raises_on_garbage(tmp_path: pathlib.Path) -> None:
    """A capture that throws would break the agent it observes. Nothing here may raise."""
    assert raw.append({"session_id": "../../etc/passwd"}, root=tmp_path, now="2026-01-01T00:00:00Z")
    assert raw.append({}, root=tmp_path, now="2026-01-01T00:00:00Z")
    written = list((tmp_path / "for-test").glob("*")) if False else list((tmp_path / ".witness" / "raw").glob("*.jsonl"))
    assert written
    assert not any(".." in p.name or "/" in p.name for p in written), "session id must not escape the raw dir"


def test_capture_cli_swallows_malformed_stdin(tmp_path: pathlib.Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "witness.cli", "capture", "--root", str(tmp_path)],
        input="not json at all",
        text=True,
        capture_output=True,
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, "a bad payload must never fail the hook"
