"""GitHub Actions attestation adapter (W4).

Per decision S6, Witness does not re-derive build provenance or reimplement Sigstore -
it shells out to `gh` and treats its exit code / API response as the verification
outcome. These tests never touch a real `gh` or the network: `runner` is injected with
a fake `subprocess.CompletedProcess`-shaped result built from a realistic fixture.
"""

from __future__ import annotations

import base64
import json
import subprocess

import pytest

from witness import bundle, tiers
from witness.adapters import githubactions
from witness.adapters.githubactions.collect import collect_via_api, collect_via_verify
from witness.adapters.githubactions.normalize import normalize_attestation

DIGEST = "sha256:" + "a" * 64
REPO = "octo/example"


def _proc(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr)


def _dsse_payload(predicate_type: str) -> str:
    return base64.b64encode(json.dumps({"predicateType": predicate_type, "subject": []}).encode()).decode()


# ---- collect_via_api ------------------------------------------------------------------


def test_collect_via_api_reports_existence_and_predicate_type() -> None:
    body = json.dumps(
        {"attestations": [{"bundle": {"dsseEnvelope": {"payload": _dsse_payload("https://slsa.dev/provenance/v1")}}}]}
    )
    record = collect_via_api(REPO, DIGEST, runner=lambda args: _proc(0, stdout=body))
    assert record["exists"] is True
    assert record["predicate_types"] == ["https://slsa.dev/provenance/v1"]
    assert record["repo"] == REPO


def test_collect_via_api_normalizes_a_bare_digest() -> None:
    seen = {}

    def runner(args):
        seen["args"] = args
        return _proc(0, stdout='{"attestations": []}')

    collect_via_api(REPO, "a" * 64, runner=runner)
    assert seen["args"][-1].endswith(f"attestations/sha256:{'a' * 64}")


def test_collect_via_api_reports_absence_without_error() -> None:
    record = collect_via_api(REPO, DIGEST, runner=lambda args: _proc(0, stdout='{"attestations": []}'))
    assert record["exists"] is False
    assert record["error"] is None


def test_collect_via_api_reports_a_failed_call_distinctly_from_absence() -> None:
    record = collect_via_api(REPO, DIGEST, runner=lambda args: _proc(1, stderr="HTTP 404: Not Found"))
    assert record["exists"] is False
    assert record["error"]


def test_collect_via_api_degrades_on_an_unexpected_bundle_shape_rather_than_crashing() -> None:
    body = json.dumps({"attestations": [{"bundle": {"surprising": "shape"}}]})
    record = collect_via_api(REPO, DIGEST, runner=lambda args: _proc(0, stdout=body))
    assert record["exists"] is True
    assert record["predicate_types"] == []


# ---- collect_via_verify ----------------------------------------------------------------


def test_collect_via_verify_records_the_exit_code_as_the_verified_signal() -> None:
    record = collect_via_verify(REPO, DIGEST, artifact_or_oci="dist/app.bin", runner=lambda args: _proc(0, stdout="[]"))
    assert record["verified"] is True


def test_collect_via_verify_records_failure_and_captures_stderr() -> None:
    record = collect_via_verify(
        REPO, DIGEST, artifact_or_oci="dist/app.bin", runner=lambda args: _proc(1, stderr="no matching attestations")
    )
    assert record["verified"] is False
    assert "no matching attestations" in record["error"]


def test_collect_via_verify_requires_an_artifact_or_a_bundle() -> None:
    with pytest.raises(ValueError):
        collect_via_verify(REPO, DIGEST)


# ---- normalize_attestation --------------------------------------------------------------


def test_existence_only_produces_an_observation_and_no_gate() -> None:
    record = {"repo": REPO, "digest": DIGEST, "exists": True, "predicate_types": ["x"], "count": 1, "error": None}
    result = normalize_attestation(record, "2026-09-23T00:00:00Z")
    assert result["gate"] is None
    assert result["observation"]["event"] == "build.attestation_found"
    assert result["observation"]["source"]["tier"] == tiers.TIER_HOST_ATTESTED
    assert result["observation"]["source"]["retrievable_from"]


def test_absence_still_produces_an_honest_tier_b_observation() -> None:
    record = {"repo": REPO, "digest": DIGEST, "exists": False, "error": None}
    result = normalize_attestation(record, "2026-09-23T00:00:00Z")
    assert result["gate"] is None
    assert result["observation"]["event"] == "build.attestation_absent"
    assert result["observation"]["payload"]["exists"] is False


def test_a_verified_record_produces_an_approved_gate() -> None:
    record = {"repo": REPO, "digest": DIGEST, "verified": True, "predicate_types": [], "workflow": None, "error": None}
    result = normalize_attestation(record, "2026-09-23T00:00:00Z")
    assert result["gate"]["decision"] == "approved"
    assert result["gate"]["tier"] == tiers.TIER_HOST_ATTESTED


def test_a_failed_verification_produces_a_denied_gate_not_a_silent_pass() -> None:
    record = {"repo": REPO, "digest": DIGEST, "verified": False, "predicate_types": [], "workflow": None, "error": "boom"}
    result = normalize_attestation(record, "2026-09-23T00:00:00Z")
    assert result["gate"]["decision"] == "denied"
    assert result["observation"]["payload"]["error"] == "boom"


def test_every_observation_validates_against_the_schema() -> None:
    from jsonschema import Draft202012Validator

    import sys
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    from validate import build_registry  # noqa: E402

    registry, contents = build_registry()
    validator = Draft202012Validator(
        contents["observation.schema.json"], registry=registry, format_checker=Draft202012Validator.FORMAT_CHECKER
    )

    for record in (
        {"repo": REPO, "digest": DIGEST, "exists": True, "predicate_types": ["p"], "count": 1, "error": None},
        {"repo": REPO, "digest": DIGEST, "exists": False, "error": None},
        {"repo": REPO, "digest": DIGEST, "verified": True, "predicate_types": [], "workflow": None, "error": None},
        {"repo": REPO, "digest": DIGEST, "verified": False, "predicate_types": [], "workflow": None, "error": "x"},
    ):
        obs = normalize_attestation(record, "2026-09-23T00:00:00Z")["observation"]
        errors = sorted(validator.iter_errors(obs), key=lambda e: list(e.path))
        assert not errors, [e.message for e in errors]


# ---- wired into bundle.assemble --------------------------------------------------------


def test_bundle_assemble_folds_in_an_attestation(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import subprocess as _subprocess

    # Patched at the package-level name `collect_attestations` actually calls
    # (`githubactions.collect_via_api`), not on the global `subprocess` module - the
    # global module is shared with every other subprocess call in this test, git
    # included, and patching it there silently breaks unrelated git commands too.
    monkeypatch.setattr(
        githubactions,
        "collect_via_api",
        lambda repo, digest, **kw: {
            "repo": repo,
            "digest": digest,
            "exists": True,
            "predicate_types": ["https://slsa.dev/provenance/v1"],
            "count": 1,
            "error": None,
        },
    )

    r = tmp_path / "repo"
    r.mkdir()
    _git = lambda *a: _subprocess.run(
        ["git", "-C", str(r), *a], check=True, capture_output=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.com", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@e.com", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
             "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(r)},
    )
    _git("init", "-q", "-b", "main")
    (r / "f.txt").write_text("1\n")
    _git("add", "-A")
    _git("commit", "-qm", "base")
    _git("checkout", "-q", "-b", "feature")
    (r / "f.txt").write_text("2\n")
    _git("add", "-A")
    _git("commit", "-qm", "change")

    from witness import gitrepo

    doc = bundle.assemble(
        r, base=gitrepo.resolve(r, "main"), now="2026-09-23T00:00:00Z",
        attestations=[{"repo": REPO, "digest": DIGEST}],
    )

    assert any(s["host"] == "github-actions" for s in doc["sources"])
    assert any(o["event"] == "build.attestation_found" for o in doc["observations"])

    from witness import verify

    report = verify.verify_offline(doc, r)
    assert report["schema"]["ok"], report["schema"]["errors"]


# ---- online_verify (S19: wiring `--online` to something real for this channel) --------


def _bundle_with(observation: dict) -> dict:
    return {"observations": [observation]}


def test_online_verify_confirms_existence_that_still_matches() -> None:
    record = {"repo": REPO, "digest": DIGEST, "exists": True, "predicate_types": ["x"], "count": 1, "error": None}
    observation = normalize_attestation(record, "2026-09-23T00:00:00Z")["observation"]
    body = json.dumps({"attestations": [{"bundle": {"dsseEnvelope": {"payload": _dsse_payload("x")}}}]})

    outcome = githubactions.online_verify(
        observation["source"], _bundle_with(observation), runner=lambda args: _proc(0, stdout=body)
    )
    assert outcome == {"outcome": "confirmed"}


def test_online_verify_confirms_a_claimed_absence_that_is_still_absent() -> None:
    record = {"repo": REPO, "digest": DIGEST, "exists": False, "error": None}
    observation = normalize_attestation(record, "2026-09-23T00:00:00Z")["observation"]

    outcome = githubactions.online_verify(
        observation["source"], _bundle_with(observation), runner=lambda args: _proc(0, stdout='{"attestations": []}')
    )
    assert outcome == {"outcome": "confirmed"}


def test_online_verify_reports_contradicted_when_existence_now_disagrees() -> None:
    record = {"repo": REPO, "digest": DIGEST, "exists": True, "predicate_types": ["x"], "count": 1, "error": None}
    observation = normalize_attestation(record, "2026-09-23T00:00:00Z")["observation"]

    outcome = githubactions.online_verify(
        observation["source"], _bundle_with(observation), runner=lambda args: _proc(0, stdout='{"attestations": []}')
    )
    assert outcome["outcome"] == "contradicted"


def test_online_verify_degrades_rather_than_guesses_when_the_refetch_itself_fails() -> None:
    """collect_via_api cannot tell 'GitHub says no' from 'gh itself failed' - this file
    must not gamble that a failure means the attestation was revoked."""
    record = {"repo": REPO, "digest": DIGEST, "exists": True, "predicate_types": ["x"], "count": 1, "error": None}
    observation = normalize_attestation(record, "2026-09-23T00:00:00Z")["observation"]

    outcome = githubactions.online_verify(
        observation["source"], _bundle_with(observation), runner=lambda args: _proc(1, stderr="HTTP 500")
    )
    assert outcome == {"outcome": "unreachable", "reason": "HTTP 500"}


def test_online_verify_is_unreachable_with_no_matching_observation_in_the_bundle() -> None:
    source = {"retrievable_from": f"https://api.github.com/repos/{REPO}/attestations/{DIGEST}"}
    outcome = githubactions.online_verify(source, {"observations": []})
    assert outcome["outcome"] == "unreachable"


def test_online_verify_is_unreachable_for_a_locator_it_does_not_recognise() -> None:
    outcome = githubactions.online_verify({"retrievable_from": "https://example.com/nope"}, {"observations": []})
    assert outcome["outcome"] == "unreachable"


def test_verify_online_reaches_the_real_github_actions_verifier_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The actual fix, not just the unit: before S19, `witness verify --online` on a
    real github-actions bundle reported "no online verifier registered" forever, because
    nothing ever called `register_online_verifier` for this host/channel. This builds a
    real bundle via `bundle.assemble` and runs it through `verify.verify_online` with no
    manual registration - the registration must happen on its own."""
    import subprocess as _subprocess

    from witness import gitrepo, verify
    from witness.adapters.githubactions import collect as collect_mod

    fake_record = {
        "repo": REPO, "digest": DIGEST, "exists": True,
        "predicate_types": ["x"], "count": 1, "error": None,
    }
    # Two call sites, two bindings: bundle.assemble calls the package-level re-export;
    # online_verify (inside collect.py) calls its own module-local name. Both need it.
    monkeypatch.setattr(githubactions, "collect_via_api", lambda repo, digest, **kw: fake_record)
    monkeypatch.setattr(collect_mod, "collect_via_api", lambda repo, digest, **kw: fake_record)

    r = tmp_path / "repo"
    r.mkdir()
    _git = lambda *a: _subprocess.run(
        ["git", "-C", str(r), *a], check=True, capture_output=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.com", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@e.com", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
             "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(r)},
    )
    _git("init", "-q", "-b", "main")
    (r / "f.txt").write_text("1\n")
    _git("add", "-A")
    _git("commit", "-qm", "base")
    _git("checkout", "-q", "-b", "feature")
    (r / "f.txt").write_text("2\n")
    _git("add", "-A")
    _git("commit", "-qm", "change")

    doc = bundle.assemble(
        r, base=gitrepo.resolve(r, "main"), now="2026-09-23T00:00:00Z",
        attestations=[{"repo": REPO, "digest": DIGEST}],
    )

    verify.ONLINE_VERIFIERS.pop(("github-actions", "attestation"), None)
    report = verify.verify_online(doc, r)

    assert report["online"] == [
        {"source": {"host": "github-actions", "channel": "attestation"}, "outcome": "confirmed"}
    ]
    assert report["ok"]
