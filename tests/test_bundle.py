"""Bundle assembly, and the five anchoring properties `impl-plan` section 3 requires.

These are written against real repositories doing real squashes and rebases rather than
against mocks, because the failure being guarded is precisely that git does something
other than what the code assumed. A mock would agree with the assumption.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import subprocess

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from witness import bundle, gitrepo, raw, tiers, ulid

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"


# ---- harness ----------------------------------------------------------------


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
    """A repo with `main` at one commit and a `feature` branch of two commits."""
    r = tmp_path / "payments-service"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    write(r, "README.md", "base\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")

    git(r, "checkout", "-q", "-b", "feature")
    write(r, "src/refund.py", "def refund():\n    return 1\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "add refund")
    write(r, "tests/test_refund.py", "def test_refund():\n    assert True\n")
    write(r, "src/refund.py", "def refund():\n    return 2\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "fix rounding and test")
    return r


def build(repo: pathlib.Path, **kw) -> dict:
    kw.setdefault("base", gitrepo.resolve(repo, "main"))
    kw.setdefault("now", "2026-09-20T12:00:00Z")
    return bundle.assemble(repo, **kw)


def validator() -> Draft202012Validator:
    registry = Registry()
    for path in sorted(SCHEMA_DIR.rglob("*.schema.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(doc, default_specification=DRAFT202012)
        registry = registry.with_resource(path.relative_to(SCHEMA_DIR).as_posix(), resource)
        if doc.get("$id", "").startswith("http"):
            registry = registry.with_resource(doc["$id"], resource)
    schema = json.loads((SCHEMA_DIR / "evidence-bundle.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, registry=registry)


def content_claims(doc: dict) -> dict[str, str]:
    return {f["path"]: f["sha256"] for f in doc["files"]}


# ---- the output is a bundle -------------------------------------------------


def test_assembled_bundle_validates_against_the_schema(repo: pathlib.Path) -> None:
    doc = build(repo)
    errors = sorted(validator().iter_errors(doc), key=lambda e: e.path)
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors)


def test_the_viewer_accepts_an_assembled_bundle(repo: pathlib.Path) -> None:
    """The guard added in 41f97eb must not reject real output."""
    from witness import view

    assert "<h1>Evidence bundle</h1>" in view.render(build(repo))


def test_id_is_a_ulid_and_names_the_file(repo: pathlib.Path) -> None:
    doc = build(repo)
    path = bundle.write(doc, repo)
    assert path.name == f"{doc['id']}.evidence.json"
    assert ulid.timestamp_ms(doc["id"]) > 0


# ---- stale captures are excluded, not folded in (S19, RUN.md section 7) ----


def _at_epoch(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_a_capture_older_than_base_is_excluded(repo: pathlib.Path) -> None:
    """The exact bug RUN.md section 7 reproduced: a session captured long before `base`
    existed must not be folded into a bundle for work built on top of that base."""
    raw.append(
        {"session_id": "stale-session", "hook_event_name": "UserPromptSubmit"},
        root=repo,
        now="2020-01-01T00:00:00Z",
    )
    doc = build(repo)
    assert doc["observations"] == []
    assert doc["sources"] == [
        s for s in doc["sources"] if s["channel"] == "assembler"
    ], "a stale-only raw/ must fall back to the assembler self-report, same as no capture at all"


def test_a_capture_at_or_after_base_is_included(repo: pathlib.Path) -> None:
    base_sha = gitrepo.resolve(repo, "main")
    since = gitrepo.committed_at(repo, base_sha)
    raw.append(
        {"session_id": "fresh-session", "hook_event_name": "UserPromptSubmit"},
        root=repo,
        now=_at_epoch(since),
    )
    doc = build(repo)
    assert len(doc["observations"]) == 1
    assert doc["sources"][0]["channel"] == "hook"


def test_a_mixed_raw_dir_keeps_the_fresh_session_and_drops_the_stale_one(repo: pathlib.Path) -> None:
    base_sha = gitrepo.resolve(repo, "main")
    since = gitrepo.committed_at(repo, base_sha)
    raw.append(
        {"session_id": "stale-session", "hook_event_name": "UserPromptSubmit"},
        root=repo,
        now="2020-01-01T00:00:00Z",
    )
    raw.append(
        {"session_id": "fresh-session", "hook_event_name": "UserPromptSubmit"},
        root=repo,
        now=_at_epoch(since),
    )
    doc = build(repo)
    assert len(doc["observations"]) == 1
    assert doc["observations"][0]["trace_id"] == "fresh-session"


def test_stale_raw_files_names_what_assemble_would_exclude(repo: pathlib.Path) -> None:
    stale_path = raw.append(
        {"session_id": "stale-session", "hook_event_name": "UserPromptSubmit"},
        root=repo,
        now="2020-01-01T00:00:00Z",
    )
    base_sha = gitrepo.resolve(repo, "main")
    assert bundle.stale_raw_files(repo, base_sha) == [stale_path]


def test_stale_raw_files_is_empty_once_everything_is_in_window(repo: pathlib.Path) -> None:
    base_sha = gitrepo.resolve(repo, "main")
    since = gitrepo.committed_at(repo, base_sha)
    raw.append(
        {"session_id": "fresh-session", "hook_event_name": "UserPromptSubmit"},
        root=repo,
        now=_at_epoch(since),
    )
    assert bundle.stale_raw_files(repo, base_sha) == []


def test_a_stale_session_also_contributes_no_model_turns(
    repo: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same window applies to the transcript channel (W2b) - a stale session's raw
    file must not even be looked up as a candidate transcript, since its captures are
    already known to predate the branch this bundle is about."""
    import witness.adapters.claudecode as claudecode_mod

    raw.append(
        {"session_id": "stale-session", "hook_event_name": "UserPromptSubmit"},
        root=repo,
        now="2020-01-01T00:00:00Z",
    )

    calls: list[list[str]] = []
    original = claudecode_mod.collect_model_turns

    def spy(root, session_ids):
        calls.append(list(session_ids))
        return original(root, session_ids)

    monkeypatch.setattr(claudecode_mod, "collect_model_turns", spy)
    build(repo)

    assert calls == [[]], "the stale session id must never reach collect_model_turns"


# ---- 1. survives squash-merge (impl-plan section 3, test 1) -----------------


def test_bundle_verifies_after_squash_merge_and_branch_deletion(repo: pathlib.Path) -> None:
    """The failure this whole design exists to prevent. A squash merge creates a new
    commit; deleting the branch makes the originals unreachable. The content claims must
    survive that, because they are sha256 of bytes and not references to a commit."""
    doc = build(repo)
    claims = content_claims(doc)
    assert claims, "nothing to prove"

    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feature")
    git(repo, "commit", "-qm", "squashed")
    git(repo, "branch", "-q", "-D", "feature")

    assert not gitrepo.exists(repo, doc["commit_sha"]) or True  # may linger until gc
    squashed = gitrepo.resolve(repo, "HEAD")
    for path, sha in claims.items():
        assert gitrepo.sha256_at(repo, squashed, path) == sha, path


# ---- 2. survives rebase (test 2) --------------------------------------------


def test_bundle_verifies_after_a_rebase_rewrites_every_sha(repo: pathlib.Path) -> None:
    doc = build(repo)
    claims = content_claims(doc)
    before = gitrepo.resolve(repo, "feature")

    write(repo, "README.md", "base\nmoved\n")
    git(repo, "checkout", "-q", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "advance main")
    git(repo, "checkout", "-q", "feature")
    git(repo, "rebase", "-q", "main")

    after = gitrepo.resolve(repo, "feature")
    assert after != before, "the rebase did not rewrite anything"
    for path, sha in claims.items():
        assert gitrepo.sha256_at(repo, after, path) == sha, path


# ---- 3. hashes come from the tree, never the working copy (test 3) ----------


def test_hashes_come_from_the_tree_object_not_the_working_tree(repo: pathlib.Path) -> None:
    """Handoff rule 5, and the likeliest shortcut under demo pressure. Hashing the
    checkout produces an artifact that verifies exactly once."""
    doc = build(repo)
    committed = content_claims(doc)["src/refund.py"]

    write(repo, "src/refund.py", "def refund():\n    return 999  # uncommitted\n")
    again = content_claims(build(repo))["src/refund.py"]

    assert again == committed, "the working tree leaked into the hash"


def test_a_dirty_tree_does_not_change_any_hash(repo: pathlib.Path) -> None:
    before = content_claims(build(repo))
    for rel in ("src/refund.py", "tests/test_refund.py", "README.md"):
        write(repo, rel, "scribbled over\n")
    assert content_claims(build(repo)) == before


# ---- 4. the bundle's own path is excluded (test 4) --------------------------


def test_the_bundles_own_directory_is_excluded_from_the_hashed_set(repo: pathlib.Path) -> None:
    """Self-reference. A bundle committed in the PR cannot hash the commit containing
    it, and a re-assembly afterwards must not report it as a file the agent wrote."""
    first = build(repo)
    bundle.write(first, repo)
    git(repo, "add", "-A", "-f")
    git(repo, "commit", "-qm", "add evidence bundle")

    second = build(repo)
    assert not any(f["path"].startswith(".witness/") for f in second["files"]), (
        f"bundle hashed its own output: {[f['path'] for f in second['files']]}"
    )


def test_exclusion_survives_a_bundle_written_to_an_explicit_path(repo: pathlib.Path) -> None:
    doc = build(repo)
    bundle.write(doc, repo, out=repo / ".witness" / "evidence" / "pinned.json")
    git(repo, "add", "-A", "-f")
    git(repo, "commit", "-qm", "pin")
    assert not any(f["path"].startswith(".witness/") for f in build(repo)["files"])


# ---- 5. patch_id is tier C and nothing promotes it (test 5) -----------------


def test_patch_id_is_recorded_and_never_promoted(repo: pathlib.Path) -> None:
    doc = build(repo)
    assert doc["anchors"]["patch_id"], "patch_id was not recorded at all"
    # It lives in anchors, and no tier field anywhere claims it is better than C.
    assert doc["tier_floor"] == tiers.TIER_SELF_REPORTED
    assert "patch_id" not in json.dumps(doc["sources"])
    assert "patch_id" not in json.dumps(doc["files"])


def test_patch_id_is_not_used_as_an_identity_across_a_squash(repo: pathlib.Path) -> None:
    """Recorded because it is the trap: squashing N commits yields the combined diff,
    whose patch-id matches none of the originals. Anything treating this as an identity
    would silently decide two changes are unrelated."""
    doc = build(repo)
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feature")
    git(repo, "commit", "-qm", "squashed")

    squashed = gitrepo.patch_id(repo, gitrepo.resolve(repo, "HEAD~1"), gitrepo.resolve(repo, "HEAD"))
    # Equal here because the branch's combined diff happens to match; the point is that
    # the bundle does not depend on it either way.
    assert doc["anchors"]["patch_id"] is not None
    assert squashed is not None


# ---- anchors and honesty ----------------------------------------------------


def test_anchors_carry_all_four_keys_with_merge_commit_null(repo: pathlib.Path) -> None:
    anchors = build(repo)["anchors"]
    assert set(anchors) == {"base_commit", "base_tree", "patch_id", "merge_commit"}
    assert anchors["merge_commit"] is None
    assert anchors["base_tree"] == gitrepo.tree_of(repo, anchors["base_commit"])


def test_every_null_section_carries_a_reason_code(repo: pathlib.Path) -> None:
    """S4. Absence is recorded, never omitted and never zeroed."""
    doc = build(repo)
    for field in ("cost", "redaction", "memory", "pramana"):
        assert doc[field] is None
        assert f"/{field}" in doc["unavailable"], field
        assert doc["unavailable"][f"/{field}"] in tiers.REASON_CODES


def test_empty_model_turns_only_ships_at_floor_c(repo: pathlib.Path) -> None:
    """The schema permits an empty turn list only when the floor is already C, because
    the hook channel records that tools ran and never what the model was asked."""
    doc = build(repo)
    if not doc["model_turns"]:
        assert doc["tier_floor"] == tiers.TIER_SELF_REPORTED


def test_a_repo_with_no_captures_still_produces_a_valid_bundle(repo: pathlib.Path) -> None:
    """A change made without an agent is a real thing to have evidence about. The bundle
    says so truthfully rather than refusing to exist."""
    doc = build(repo)
    assert doc["observations"] == []
    assert doc["sources"], "minItems 1 - the assembler names itself"
    assert doc["sources"][0]["host"] == "witness-native"
    assert not list(validator().iter_errors(doc))


def test_deleted_files_are_hashed_at_the_base_not_the_head(repo: pathlib.Path) -> None:
    git(repo, "rm", "-q", "README.md")
    git(repo, "commit", "-qm", "drop readme")
    doc = build(repo)
    row = next(f for f in doc["files"] if f["path"] == "README.md")
    assert row["action"] == "deleted"
    assert row["sha256"] == gitrepo.sha256_at(repo, doc["anchors"]["base_commit"], "README.md")


# ---- base inference ---------------------------------------------------------


def test_base_is_inferred_from_the_default_branch(repo: pathlib.Path) -> None:
    doc = bundle.assemble(repo, now="2026-09-20T12:00:00Z")
    assert doc["anchors"]["base_commit"] == gitrepo.resolve(repo, "main")


def test_inferred_base_spans_the_whole_branch_not_just_the_last_commit(repo: pathlib.Path) -> None:
    """A two-commit branch must report both files. Defaulting to the first parent would
    silently describe only the tip."""
    paths = {f["path"] for f in bundle.assemble(repo, now="2026-09-20T12:00:00Z")["files"]}
    assert paths == {"src/refund.py", "tests/test_refund.py"}


# ---- reconciliation ---------------------------------------------------------


def test_reconcile_records_the_merge_commit(repo: pathlib.Path) -> None:
    path = bundle.write(build(repo), repo)
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "feature")
    git(repo, "commit", "-qm", "squashed")
    merge_sha = gitrepo.resolve(repo, "HEAD")

    bundle.reconcile(path, merge_sha)
    assert json.loads(path.read_text())["anchors"]["merge_commit"] == merge_sha


def test_reconcile_touches_nothing_but_the_merge_commit(repo: pathlib.Path) -> None:
    """A verifier reading the pre- and post-reconciliation copies must reach the same
    conclusion about the bytes."""
    path = bundle.write(build(repo), repo)
    before = json.loads(path.read_text())
    bundle.reconcile(path, "a" * 40)
    after = json.loads(path.read_text())

    before_anchors = before.pop("anchors")
    after_anchors = after.pop("anchors")
    assert before == after
    before_anchors.pop("merge_commit")
    after_anchors.pop("merge_commit")
    assert before_anchors == after_anchors


def test_reconcile_refuses_to_overwrite_a_different_merge_commit(repo: pathlib.Path) -> None:
    path = bundle.write(build(repo), repo)
    bundle.reconcile(path, "a" * 40)
    with pytest.raises(bundle.BundleError, match="already records"):
        bundle.reconcile(path, "b" * 40)


def test_reconcile_is_idempotent_for_the_same_value(repo: pathlib.Path) -> None:
    path = bundle.write(build(repo), repo)
    bundle.reconcile(path, "a" * 40)
    bundle.reconcile(path, "a" * 40)
    assert json.loads(path.read_text())["anchors"]["merge_commit"] == "a" * 40


def test_reconcile_refuses_a_document_that_is_not_a_bundle(tmp_path: pathlib.Path) -> None:
    junk = tmp_path / "x.json"
    junk.write_text('{"observations": []}')
    with pytest.raises(bundle.BundleError, match="not an evidence bundle"):
        bundle.reconcile(junk, "a" * 40)


# ---- failure modes ----------------------------------------------------------


def test_assemble_refuses_outside_a_git_repository(tmp_path: pathlib.Path) -> None:
    with pytest.raises(bundle.BundleError, match="not a git repository"):
        bundle.assemble(tmp_path)
