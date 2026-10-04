"""`witness verify` - SPEC.md section 6.

Mirrors test_bundle.py's harness: real repositories doing real squashes and rebases,
because the property under test is precisely that git did something other than what a
naive verifier assumed.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess

import pytest

from witness import bundle, gitrepo, tiers, verify

ROOT = pathlib.Path(__file__).resolve().parents[1]


def git(repo: pathlib.Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@e.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@e.com",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(repo),
        },
    )
    return proc.stdout.decode()


def write(repo: pathlib.Path, rel: str, text: str) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


@pytest.fixture()
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    r = tmp_path / "payments"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    write(r, "README.md", "base\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")

    git(r, "checkout", "-q", "-b", "feature")
    write(r, "src/refund.py", "def refund():\n    return 1\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "add refund")
    return r


def build(repo: pathlib.Path, **kw) -> dict:
    kw.setdefault("base", gitrepo.resolve(repo, "main"))
    kw.setdefault("now", "2026-09-20T12:00:00Z")
    return bundle.assemble(repo, **kw)


# ---- locating schemas/ (decisions.md S18) -------------------------------------------


def test_schema_dir_prefers_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    monkeypatch.setenv("WITNESS_SCHEMAS_DIR", str(tmp_path))
    assert verify._schema_dir() == tmp_path


def test_schema_dir_falls_back_to_repo_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WITNESS_SCHEMAS_DIR", raising=False)
    assert verify._schema_dir() == ROOT / "schemas"


def test_schema_dir_falls_back_to_the_installed_witness_schemas_package_when_no_checkout_is_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """The scenario S18 fixes: `pip install witness` on a machine with no checkout of
    this repo. `ROOT/schemas` won't exist there, so `_schema_dir` must fall through to
    the installed `witness_schemas` package rather than failing."""
    installed = tmp_path / "site-packages" / "witness_schemas"
    installed.mkdir(parents=True)
    (installed / "evidence-bundle.schema.json").write_text("{}", encoding="utf-8")

    monkeypatch.delenv("WITNESS_SCHEMAS_DIR", raising=False)
    monkeypatch.setattr(verify, "ROOT", tmp_path / "no-checkout-here")
    monkeypatch.setattr(verify, "_installed_schema_dir", lambda: installed)

    assert verify._schema_dir() == installed


def test_schema_dir_fails_loudly_when_nothing_is_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    monkeypatch.delenv("WITNESS_SCHEMAS_DIR", raising=False)
    monkeypatch.setattr(verify, "ROOT", tmp_path / "no-checkout-here")
    monkeypatch.setattr(verify, "_installed_schema_dir", lambda: None)

    with pytest.raises(verify.VerifyError, match="cannot find schemas/"):
        verify._schema_dir()


def test_installed_schema_dir_uses_the_witness_schemas_import_name_not_the_generic_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rename this test pins: `witness_schemas`, not the generic `schemas`, which a
    real unrelated package on PyPI already uses - installing under that name would risk
    `import schemas` resolving to someone else's package in a user's environment."""
    seen: list[str] = []

    def fake_find_spec(name: str):
        seen.append(name)
        return None

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    assert verify._installed_schema_dir() is None
    assert seen == ["witness_schemas"]


# ---- a real bundle passes offline ---------------------------------------------------


def test_a_freshly_assembled_bundle_passes_offline(repo: pathlib.Path) -> None:
    report = verify.verify_offline(build(repo), repo)
    assert report["ok"], report
    assert report["schema"]["ok"]
    assert report["content"]["matched"] == report["content"]["total"] == 1
    assert report["tier_floor"] == {"declared": "C", "computed": "C", "ok": True, "notes": []}
    assert report["locators"]["commit_sha"]["reachable"] is True


def test_verify_file_reads_from_disk(repo: pathlib.Path) -> None:
    path = bundle.write(build(repo), repo)
    report = verify.verify_file(path, root=repo)
    assert report["ok"]


def test_verify_refuses_a_document_that_is_not_a_bundle(tmp_path: pathlib.Path) -> None:
    junk = tmp_path / "x.json"
    junk.write_text('{"observations": []}')
    with pytest.raises(verify.VerifyError, match="not an evidence bundle"):
        verify.verify_file(junk, root=tmp_path)


def test_verify_refuses_unparseable_json(tmp_path: pathlib.Path) -> None:
    junk = tmp_path / "x.json"
    junk.write_text("{not json")
    with pytest.raises(verify.VerifyError):
        verify.verify_file(junk, root=tmp_path)


# ---- the proof this file exists for: dead locator, live content ---------------------


def test_content_reverifies_after_squash_merge_branch_delete_and_gc(repo: pathlib.Path) -> None:
    doc = build(repo)
    assert doc["commit_sha"] and gitrepo.exists(repo, doc["commit_sha"])

    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feature")
    git(repo, "commit", "-qm", "squashed")
    git(repo, "branch", "-q", "-D", "feature")
    git(repo, "reflog", "expire", "--expire=now", "--all")
    git(repo, "gc", "-q", "--prune=now")

    report = verify.verify_offline(doc, repo)

    assert report["locators"]["commit_sha"]["reachable"] is False, "the point of the test: it must actually be dead"
    assert report["content"]["recovered"] == report["content"]["total"] == 1
    assert report["content"]["matched"] == 0, "recovered from history is not the same claim as matched at an anchor"
    assert all(r["outcome"] == "recovered" for r in report["content"]["results"])
    assert report["ok"], "a dead locator must not fail a bundle whose content still holds"


def test_a_dead_locator_never_surfaces_as_a_content_failure(repo: pathlib.Path) -> None:
    doc = build(repo)
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feature")
    git(repo, "commit", "-qm", "squashed")
    git(repo, "branch", "-q", "-D", "feature")

    report = verify.verify_offline(doc, repo)
    for row in report["content"]["results"]:
        assert row["outcome"] != "mismatch"


def test_content_reverifies_after_a_rebase(repo: pathlib.Path) -> None:
    doc = build(repo)
    write(repo, "README.md", "base\nmoved\n")
    git(repo, "checkout", "-q", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "advance main")
    git(repo, "checkout", "-q", "feature")
    git(repo, "rebase", "-q", "main")

    report = verify.verify_offline(doc, repo)
    assert report["ok"]
    assert report["content"]["matched"] == report["content"]["total"]


def test_reconciled_bundle_is_checked_against_the_merge_commit(repo: pathlib.Path) -> None:
    path = bundle.write(build(repo), repo)
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feature")
    git(repo, "commit", "-qm", "squashed")
    merge_sha = gitrepo.resolve(repo, "HEAD")
    bundle.reconcile(path, merge_sha)

    report = verify.verify_file(path, root=repo)
    assert report["ok"]
    assert all(r["checked_at"] == "merge_commit" for r in report["content"]["results"])


# ---- genuine content failures must fail, not degrade --------------------------------


def test_a_genuinely_altered_file_at_a_live_anchor_is_a_mismatch(repo: pathlib.Path) -> None:
    doc = build(repo)
    doc["files"][0]["sha256"] = "0" * 64  # tamper with the claim, anchor stays live and reachable

    report = verify.verify_offline(doc, repo)
    assert not report["ok"]
    mismatches = [r for r in report["content"]["results"] if r["outcome"] == "mismatch"]
    assert mismatches and mismatches[0]["path"] == doc["files"][0]["path"]


def test_a_claim_for_a_path_that_never_existed_is_absent(repo: pathlib.Path) -> None:
    doc = build(repo)
    doc["files"].append({"path": "nope/never.py", "sha256": "1" * 64, "action": "created"})

    report = verify.verify_offline(doc, repo)
    assert not report["ok"]
    absent = [r for r in report["content"]["results"] if r["path"] == "nope/never.py"]
    assert absent and absent[0]["outcome"] == "absent"


# ---- schema -------------------------------------------------------------------------


def test_schema_check_rejects_a_tampered_tier_floor(repo: pathlib.Path) -> None:
    doc = build(repo)
    doc["tier_floor"] = "not-a-tier"
    report = verify.verify_offline(doc, repo)
    assert not report["schema"]["ok"]
    assert not report["ok"]


# ---- tier_floor honesty --------------------------------------------------------------


def test_tier_floor_overstatement_fails(repo: pathlib.Path) -> None:
    doc = build(repo)
    doc["tier_floor"] = tiers.TIER_ATTESTED  # claims A with only tier C sources
    report = verify.verify_offline(doc, repo)
    assert not report["tier_floor"]["ok"]
    assert not report["ok"]


def test_a_mixed_hook_and_attestation_bundle_cannot_claim_b_while_a_c_source_remains(repo: pathlib.Path) -> None:
    """Ported from the deleted examples/invalid/empty-turns-claiming-tier-b.json: a
    schema-level rule used to reject this shape outright (any bundle with empty
    model_turns had to declare tier_floor C). That rule was removed because it also
    rejected a legitimate case W4 introduced - a build-only bundle with a real tier B
    attestation and no agent activity at all. The dishonesty in *this* bundle was never
    about model_turns being empty; it is that a tier C hook source is still present
    alongside the tier B one, so the true floor is C regardless. That is exactly what
    `witness verify`'s general floor computation catches, with no model_turns special
    case needed."""
    doc = build(repo)
    doc["sources"].append(
        {
            "host": "github-actions",
            "channel": "attestation",
            "tier": "B",
            "collected_at": "2026-09-20T12:00:00Z",
            "retrievable_from": "https://api.github.com/repos/acme/payments-service/attestations/sha256:9c1d",
            "adapter_version": "githubactions/0.1.0",
        }
    )
    doc["gates"].append(
        {"gate": "pr-review", "decision": "approved", "actor": "user:priya", "at": "2026-09-20T12:00:00Z", "reason": None, "tier": "B"}
    )
    doc["tier_floor"] = "B"  # overstates itself: the hook source is still tier C

    report = verify.verify_offline(doc, repo)
    assert not report["tier_floor"]["ok"]
    assert report["tier_floor"]["computed"] == tiers.TIER_SELF_REPORTED
    assert not report["ok"]


def test_empty_model_turns_with_only_a_tier_b_source_is_a_legitimate_floor_b(repo: pathlib.Path) -> None:
    """The regression S17's amendment (decisions.md) fixes: `check_tier_floor` used to
    carry its own leftover copy of the exact special case S17 retired from the schema -
    empty model_turns forces tier_floor C - which rejected a build-only bundle with a
    real tier B claim and zero agent activity. There is no tier C source here at all,
    so the general `declared == computed` check is the only thing that should fire, and
    it must not."""
    doc = build(repo)
    doc["model_turns"] = []
    doc["sources"] = [
        {
            "host": "github-actions",
            "channel": "attestation",
            "tier": "B",
            "collected_at": "2026-09-20T12:00:00Z",
            "retrievable_from": "https://example.invalid/attestations/1",
            "adapter_version": "githubactions/0.1.0",
        }
    ]
    doc["tier_floor"] = tiers.TIER_HOST_ATTESTED

    report = verify.verify_offline(doc, repo)
    assert report["tier_floor"] == {"declared": "B", "computed": "B", "ok": True, "notes": []}
    assert report["ok"]


# ---- unavailable coverage -------------------------------------------------------------


def test_a_null_field_with_no_reason_fails_coverage(repo: pathlib.Path) -> None:
    doc = build(repo)
    del doc["unavailable"]["/cost"]
    report = verify.verify_offline(doc, repo)
    assert not report["unavailable"]["ok"]
    assert "/cost" in report["unavailable"]["missing"]
    assert not report["ok"]


def test_an_invented_reason_code_fails_coverage(repo: pathlib.Path) -> None:
    doc = build(repo)
    doc["unavailable"]["/cost"] = "made_up_code"
    report = verify.verify_offline(doc, repo)
    assert not report["unavailable"]["ok"]
    assert ("/cost", "made_up_code") in report["unavailable"]["bad_codes"]


# ---- tier A chain ---------------------------------------------------------------------


def test_chain_not_applicable_without_tier_a(repo: pathlib.Path) -> None:
    report = verify.verify_offline(build(repo), repo)
    assert report["chain"] == {"applicable": False, "ok": True}


def test_chain_verifies_a_genuine_tier_a_sequence(repo: pathlib.Path) -> None:
    doc = build(repo)
    src = {
        "host": "witness-native",
        "channel": "runner",
        "tier": "A",
        "collected_at": "2026-09-20T12:00:00Z",
        "retrievable_from": None,
        "adapter_version": "pramana/0.1.0",
    }
    obs1 = {
        "audit_id": "0d1f8a3e-1c4b-4a77-9f2e-6b5c0a9d4e11",
        "session_id": "7c9a2b10-5d3e-4f81-b6a2-1e0c8d7f3a52",
        "timestamp": "2026-09-20T12:00:00Z",
        "event": "tool.write",
        "actor": "agent:pramana",
        "trace_id": "t1",
        "phase": "code",
        "tokens": None,
        "cost_usd": None,
        "prev_hash": None,
        "payload": {"unavailable": {"/tokens": "not_applicable", "/cost_usd": "not_applicable", "/phase": "not_applicable"}},
        "source": src,
    }
    obs1["phase"] = None
    obs1["entry_hash"] = verify._entry_hash(obs1)

    obs2 = dict(obs1)
    obs2["audit_id"] = "1d1f8a3e-1c4b-4a77-9f2e-6b5c0a9d4e12"
    obs2["prev_hash"] = obs1["entry_hash"]
    obs2.pop("entry_hash", None)
    obs2["entry_hash"] = verify._entry_hash(obs2)

    doc["observations"] = [obs1, obs2]
    doc["sources"] = [src]
    doc["tier_floor"] = "A"
    doc["pramana"] = {
        "first_audit_id": obs1["audit_id"],
        "last_audit_id": obs2["audit_id"],
        "event_count": 2,
        "chain_head": obs2["entry_hash"],
    }

    report = verify.verify_offline(doc, repo)
    assert report["chain"] == {"applicable": True, "ok": True, "broken_at": None, "terminates_at_chain_head": True}


def test_chain_detects_a_tampered_row(repo: pathlib.Path) -> None:
    doc = build(repo)
    src = {
        "host": "witness-native", "channel": "runner", "tier": "A",
        "collected_at": "2026-09-20T12:00:00Z", "retrievable_from": None,
        "adapter_version": "pramana/0.1.0",
    }
    obs = {
        "audit_id": "0d1f8a3e-1c4b-4a77-9f2e-6b5c0a9d4e11",
        "session_id": "7c9a2b10-5d3e-4f81-b6a2-1e0c8d7f3a52",
        "timestamp": "2026-09-20T12:00:00Z",
        "event": "tool.write",
        "actor": "agent:pramana",
        "trace_id": "t1",
        "phase": None,
        "tokens": None,
        "cost_usd": None,
        "prev_hash": None,
        "payload": {"unavailable": {}},
        "source": src,
    }
    obs["entry_hash"] = verify._entry_hash(obs)
    obs["event"] = "tool.write.TAMPERED"  # mutate after hashing

    doc["observations"] = [obs]
    doc["sources"] = [src]
    doc["tier_floor"] = "A"
    doc["pramana"] = {
        "first_audit_id": obs["audit_id"], "last_audit_id": obs["audit_id"],
        "event_count": 1, "chain_head": obs["entry_hash"],
    }

    report = verify.verify_offline(doc, repo)
    assert report["chain"]["applicable"] is True
    assert not report["chain"]["ok"]
    assert report["chain"]["broken_at"] == obs["audit_id"]


# ---- tier B claim labelling (SPEC 6.1: never silently "pass" a check not performed) ---


def test_offline_mode_labels_every_tier_b_source_as_unverified(repo: pathlib.Path) -> None:
    doc = build(repo)
    doc["sources"].append(
        {
            "host": "github-actions", "channel": "attestation", "tier": "B",
            "collected_at": "2026-09-20T12:00:00Z",
            "retrievable_from": "https://api.github.com/repos/o/r/attestations/sha256:aa",
            "adapter_version": "githubactions/0.1.0",
        }
    )
    report = verify.verify_offline(doc, repo)
    claims = [c for c in report["tier_b_claims"] if c["kind"] == "source"]
    assert claims and all(c["outcome"] == "unverified-offline" for c in claims)


def test_offline_mode_never_reports_a_tier_c_only_bundle_as_having_tier_b_claims(repo: pathlib.Path) -> None:
    report = verify.verify_offline(build(repo), repo)
    assert report["tier_b_claims"] == []


def test_a_tier_b_gate_is_also_labelled_unverified_offline(repo: pathlib.Path) -> None:
    doc = build(repo)
    doc["gates"].append({"gate": "pr-review", "decision": "approved", "actor": "user:x", "at": "2026-09-20T12:00:00Z", "reason": None, "tier": "B"})
    report = verify.verify_offline(doc, repo)
    gate_claims = [c for c in report["tier_b_claims"] if c["kind"] == "gate"]
    assert gate_claims == [{"kind": "gate", "gate": "pr-review", "index": 0, "outcome": "unverified-offline"}]


# ---- online -------------------------------------------------------------------------


def test_online_reports_unreachable_when_no_verifier_is_registered(repo: pathlib.Path) -> None:
    doc = build(repo)
    doc["sources"].append(
        {
            "host": "github-actions",
            "channel": "attestation",
            "tier": "B",
            "collected_at": "2026-09-20T12:00:00Z",
            "retrievable_from": "https://api.github.com/repos/o/r/attestations/sha256:aa",
            "adapter_version": "githubactions/0.1.0",
        }
    )
    doc["model_turns"] = []
    doc["tier_floor"] = tiers.TIER_SELF_REPORTED  # unchanged: B source alone never raises the floor (S2)

    report = verify.verify_online(doc, repo)
    assert report["mode"] == "online"
    assert len(report["online"]) == 1
    assert report["online"][0]["outcome"] == "unreachable"
    # unreachable degrades, it does not fail the bundle (SPEC 6.2)
    assert report["ok"]


def test_online_a_contradicted_claim_fails_the_bundle(repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc = build(repo)
    source = {
        "host": "github-actions",
        "channel": "attestation",
        "tier": "B",
        "collected_at": "2026-09-20T12:00:00Z",
        "retrievable_from": "https://api.github.com/repos/o/r/attestations/sha256:aa",
        "adapter_version": "githubactions/0.1.0",
    }
    doc["sources"].append(source)

    def _fake_contradicts(src: dict, bundle_doc: dict, subject_repo: "str | None") -> dict:
        return {"outcome": "contradicted", "detail": "digest mismatch"}

    verify.register_online_verifier("github-actions", "attestation", _fake_contradicts)
    try:
        report = verify.verify_online(doc, repo)
    finally:
        verify.ONLINE_VERIFIERS.pop(("github-actions", "attestation"), None)

    assert not report["ok"]
    assert report["online"][0]["outcome"] == "contradicted"
    source_claims = [c for c in report["tier_b_claims"] if c["kind"] == "source"]
    assert source_claims[0]["outcome"] == "contradicted"  # placeholder was overwritten


def test_a_verifier_that_raises_degrades_rather_than_crashing(repo: pathlib.Path) -> None:
    doc = build(repo)
    source = {
        "host": "flaky", "channel": "chan", "tier": "B",
        "collected_at": "2026-09-20T12:00:00Z",
        "retrievable_from": "https://example.invalid/x",
        "adapter_version": "flaky/0.0.1",
    }
    doc["sources"].append(source)

    def _boom(src: dict, bundle_doc: dict, subject_repo: "str | None") -> dict:
        raise RuntimeError("network is down")

    verify.register_online_verifier("flaky", "chan", _boom)
    try:
        report = verify.verify_online(doc, repo)
    finally:
        verify.ONLINE_VERIFIERS.pop(("flaky", "chan"), None)

    assert report["online"][0]["outcome"] == "unreachable"
    assert report["ok"]


# ---- forged-bundle regressions ------------------------------------------------------
# Each of these passed verification before the fix named in its docstring.


def _old_content_hash(repo: pathlib.Path) -> str:
    """Hash of src/refund.py as first committed, then advance it so HEAD differs."""
    old = gitrepo.sha256_at(repo, "HEAD", "src/refund.py")
    write(repo, "src/refund.py", "def refund():\n    return 2\n")
    git(repo, "commit", "-qam", "change refund")
    return old


def test_a_fabricated_commit_cannot_recover_content_from_before_the_base(repo: pathlib.Path) -> None:
    """Recovery used to search all of HEAD's history, so a bundle naming a commit that
    never existed matched any version of a file the repository ever held."""
    doc = build(repo)
    doc["commit_sha"] = "f" * 40
    doc["anchors"]["base_commit"] = gitrepo.resolve(repo, "HEAD")  # old content predates it
    doc["files"] = [{"path": "src/refund.py", "sha256": _old_content_hash(repo), "action": "modified"}]

    report = verify.verify_offline(doc, repo)
    assert report["content"]["results"][0]["outcome"] == "absent"
    assert not report["ok"]


def test_no_recovery_without_a_reachable_base(repo: pathlib.Path) -> None:
    """With no base to bound the search, recovery could match anything, so it is not attempted."""
    doc = build(repo)
    doc["commit_sha"] = "f" * 40
    doc["anchors"]["base_commit"] = None
    doc["files"] = [{"path": "src/refund.py", "sha256": _old_content_hash(repo), "action": "modified"}]

    report = verify.verify_offline(doc, repo)
    assert report["content"]["results"][0]["outcome"] == "absent"


def test_a_forged_base_can_recover_old_content_but_never_as_a_match(repo: pathlib.Path) -> None:
    """base_commit is the bundle author's claim, so the recovery bound alone is beatable:
    pointing base at an early commit admits old content again. The defence is that such a
    hit is reported as `recovered`, never counted as matched at an anchor."""
    doc = build(repo)
    doc["commit_sha"] = "f" * 40
    old = _old_content_hash(repo)
    doc["anchors"]["base_commit"] = git(repo, "rev-list", "--max-parents=0", "HEAD").strip()
    doc["files"] = [{"path": "src/refund.py", "sha256": old, "action": "modified"}]

    content = verify.verify_offline(doc, repo)["content"]
    assert content["results"][0]["outcome"] == "recovered"
    assert content["matched"] == 0


def test_online_binding_comes_from_the_checkout_not_the_bundle(repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A forged bundle naming the attacker's repository as both its remote and its tier B
    locator was confirmed by the first binding fix. The checkout's own remote decides."""
    from witness.adapters.githubactions import collect

    git(repo, "remote", "add", "origin", "git@github.com:acme/payments-service.git")
    doc = build(repo)
    evil = "https://api.github.com/repos/attacker/anything/attestations/sha256:" + "a" * 64
    source = {"host": "github-actions", "channel": "attestation", "tier": "B",
              "collected_at": "2026-09-20T12:00:00Z", "retrievable_from": evil,
              "adapter_version": "githubactions/0.1.0"}
    doc["repo"]["remote"] = "git@github.com:attacker/anything.git"
    doc["sources"].append(source)
    doc["observations"].append({"audit_id": "x", "event": "build.attestation_found", "source": source})
    fetched: list = []
    monkeypatch.setattr(collect, "collect_via_api", lambda r, d, **kw: fetched.append(r) or {"exists": True, "error": None})
    verify.ONLINE_VERIFIERS.pop(("github-actions", "attestation"), None)

    online = verify.verify_online(doc, repo)["online"]
    assert [o["outcome"] for o in online] == ["unreachable"]
    assert fetched == []


def test_tier_floor_counts_observation_tiers_not_just_the_sources_summary(repo: pathlib.Path) -> None:
    """The floor used to be computed from `sources` and `gates` only, so dropping the
    tier C entry from `sources` while keeping tier C observations overstated the floor."""
    doc = build(repo)
    doc["observations"].append(
        {**(doc["observations"][0] if doc["observations"] else {}),
         "source": {"host": "claude-code", "channel": "hook", "tier": "C",
                    "collected_at": "2026-09-20T12:00:00Z", "retrievable_from": None,
                    "adapter_version": "claudecode/0.1.0"}}
    )
    doc["sources"] = [
        {"host": "github-actions", "channel": "attestation", "tier": "B",
         "collected_at": "2026-09-20T12:00:00Z",
         "retrievable_from": "https://api.github.com/repos/o/r/attestations/sha256:aa",
         "adapter_version": "githubactions/0.1.0"}
    ]
    doc["gates"] = []
    doc["tier_floor"] = "B"

    floor = verify.check_tier_floor(doc)
    assert floor["computed"] == tiers.TIER_SELF_REPORTED
    assert not floor["ok"]
    assert any("claude-code:hook (tier C) is missing from sources" in n for n in floor["notes"])


def test_a_bundle_from_a_repo_with_a_remote_passes_the_schema(repo: pathlib.Path) -> None:
    """`repo.slug` is `owner/name` whenever there is a remote; the schema used to reject it."""
    git(repo, "remote", "add", "origin", "git@github.com:Acme/payments-service.git")
    doc = build(repo)
    assert doc["repo"]["slug"] == "Acme/payments-service"
    assert verify.check_schema(doc)["ok"], verify.check_schema(doc)["errors"]
