"""Git anchoring.

These tests exist because the failure they guard against is invisible. A bundle that
hashes the working tree looks correct on the day it is written and every test that builds
a repo and immediately reads it passes. It breaks silently on a fresh clone, months later,
in front of the one reader it was written for.

The squash and rebase cases are here for the same reason: both rewrite SHAs, both are the
default on a large number of repositories, and a bundle anchored only to a branch commit
stops verifying for reasons that have nothing to do with the retention decay the tier
model is designed to explain. A decayed claim and a broken tool must never look alike.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from witness import gitrepo


def git(root: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {proc.stderr}")
    return proc.stdout


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def commit(root: Path, message: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return gitrepo.resolve(root, "HEAD")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    git(root, "config", "commit.gpgsign", "false")
    write(root, "refund.py", "def refund():\n    return round(1.005, 2)\n")
    commit(root, "base")
    return root


# ---- the tree object, never the working tree -------------------------------


def test_sha256_reads_the_tree_object_not_the_working_tree(repo: Path) -> None:
    """Handoff rule 5. The single most likely thing to be got wrong under demo pressure."""
    head = gitrepo.resolve(repo, "HEAD")
    recorded = gitrepo.sha256_at(repo, head, "refund.py")

    # Someone edits the file after the bundle was written. Nothing about the commit changed.
    write(repo, "refund.py", "totally different content\n")

    assert gitrepo.sha256_at(repo, head, "refund.py") == recorded


def test_sha256_is_stable_across_a_fresh_clone(repo: Path, tmp_path: Path) -> None:
    head = gitrepo.resolve(repo, "HEAD")
    expected = gitrepo.sha256_at(repo, head, "refund.py")

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(repo), str(clone)], check=True)

    assert gitrepo.sha256_at(clone, head, "refund.py") == expected


def test_read_at_returns_bytes_from_the_named_commit(repo: Path) -> None:
    first = gitrepo.resolve(repo, "HEAD")
    write(repo, "refund.py", "second version\n")
    second = commit(repo, "change")

    assert b"round(1.005, 2)" in gitrepo.read_at(repo, first, "refund.py")
    assert gitrepo.read_at(repo, second, "refund.py") == b"second version\n"


# ---- survival across squash and rebase -------------------------------------


def test_content_survives_squash_merge_and_branch_delete(repo: Path) -> None:
    """The headline case. The branch commit is gone; the content claim still verifies."""
    base = gitrepo.resolve(repo, "HEAD")
    git(repo, "checkout", "-q", "-b", "fix")
    write(repo, "refund.py", "def refund():\n    return decimal_round(1.005, 2)\n")
    branch_sha = commit(repo, "fix rounding")
    recorded = gitrepo.sha256_at(repo, branch_sha, "refund.py")

    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "fix")
    commit(repo, "fix rounding (squashed)")
    git(repo, "branch", "-q", "-D", "fix")

    # The commit the bundle names is unreachable - an ordinary answer, not an error.
    assert gitrepo.exists(repo, branch_sha) is True  # still in the object db, just unreferenced
    recovered = gitrepo.find_containing_commit(repo, "refund.py", recorded)

    assert recovered is not None
    assert recovered != branch_sha
    assert gitrepo.sha256_at(repo, recovered, "refund.py") == recorded


def test_content_survives_a_rebase_that_rewrites_every_sha(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "fix")
    write(repo, "refund.py", "rebased content\n")
    before = commit(repo, "fix")
    recorded = gitrepo.sha256_at(repo, before, "refund.py")

    git(repo, "checkout", "-q", "main")
    write(repo, "unrelated.py", "x = 1\n")
    commit(repo, "unrelated work on main")

    git(repo, "checkout", "-q", "fix")
    git(repo, "rebase", "-q", "main")
    after = gitrepo.resolve(repo, "HEAD")

    assert after != before, "rebase should have rewritten the sha"
    assert gitrepo.sha256_at(repo, after, "refund.py") == recorded


def test_missing_object_reports_false_rather_than_raising(repo: Path) -> None:
    assert gitrepo.exists(repo, "0" * 40) is False


def test_find_containing_commit_returns_none_when_content_never_existed(repo: Path) -> None:
    assert gitrepo.find_containing_commit(repo, "refund.py", "f" * 64) is None


# ---- patch-id: recorded, labelled, never trusted as identity ---------------


def test_patch_id_is_stable_across_rebase(repo: Path) -> None:
    """The reason it is recorded at all."""
    base = gitrepo.resolve(repo, "HEAD")
    git(repo, "checkout", "-q", "-b", "fix")
    write(repo, "refund.py", "patched\n")
    head = commit(repo, "fix")
    before = gitrepo.patch_id(repo, base, head)

    git(repo, "checkout", "-q", "main")
    write(repo, "unrelated.py", "x = 1\n")
    new_base = commit(repo, "unrelated")

    git(repo, "checkout", "-q", "fix")
    git(repo, "rebase", "-q", "main")
    after = gitrepo.patch_id(repo, new_base, gitrepo.resolve(repo, "HEAD"))

    assert before is not None and before == after


def test_patch_id_is_not_stable_across_a_multi_commit_squash(repo: Path) -> None:
    """Pinned because it is the trap.

    Squashing N commits produces the combined diff, whose patch-id matches none of the N
    originals. Anything that treats patch-id as an identity would silently fail to
    correlate exactly the bundles it most needs to - the ones from multi-commit PRs.
    """
    base = gitrepo.resolve(repo, "HEAD")
    git(repo, "checkout", "-q", "-b", "fix")
    write(repo, "refund.py", "step one\n")
    first = commit(repo, "one")
    write(repo, "refund.py", "step two\n")
    second = commit(repo, "two")

    first_id = gitrepo.patch_id(repo, base, first)
    combined_id = gitrepo.patch_id(repo, base, second)

    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--squash", "fix")
    squashed = commit(repo, "squashed")
    squashed_id = gitrepo.patch_id(repo, base, squashed)

    assert squashed_id == combined_id
    assert squashed_id != first_id


def test_patch_id_is_none_for_an_empty_diff(repo: Path) -> None:
    head = gitrepo.resolve(repo, "HEAD")
    assert gitrepo.patch_id(repo, head, head) is None


# ---- change enumeration ----------------------------------------------------


def test_changed_files_reports_add_modify_delete(repo: Path) -> None:
    write(repo, "gone.py", "x\n")
    base = commit(repo, "setup")

    write(repo, "added.py", "new\n")
    write(repo, "refund.py", "changed\n")
    (repo / "gone.py").unlink()
    head = commit(repo, "change set")

    actions = {f["path"]: f["action"] for f in gitrepo.changed_files(repo, base, head)}

    assert actions == {
        "added.py": gitrepo.CREATED,
        "refund.py": gitrepo.MODIFIED,
        "gone.py": gitrepo.DELETED,
    }


def test_changed_files_records_a_deletion(repo: Path) -> None:
    base = gitrepo.resolve(repo, "HEAD")
    (repo / "refund.py").unlink()
    head = commit(repo, "delete it")

    changed = gitrepo.changed_files(repo, base, head)

    assert changed == [{"path": "refund.py", "action": gitrepo.DELETED}]
    # The pre-deletion content is still hashable from the base tree, which is what the
    # schema asks for on a deleted file.
    assert gitrepo.sha256_at(repo, base, "refund.py")


def test_changed_files_is_sorted_for_determinism(repo: Path) -> None:
    base = gitrepo.resolve(repo, "HEAD")
    for name in ("z.py", "a.py", "m.py"):
        write(repo, name, "x\n")
    head = commit(repo, "many")

    paths = [f["path"] for f in gitrepo.changed_files(repo, base, head)]

    assert paths == sorted(paths)


def test_renames_are_decomposed_into_delete_and_add(repo: Path) -> None:
    """A rename is a claim about intent; two content facts are a claim about bytes."""
    base = gitrepo.resolve(repo, "HEAD")
    git(repo, "mv", "refund.py", "refunds.py")
    head = commit(repo, "rename")

    actions = {f["path"]: f["action"] for f in gitrepo.changed_files(repo, base, head)}

    assert actions == {"refund.py": gitrepo.DELETED, "refunds.py": gitrepo.CREATED}


# ---- repo identity ---------------------------------------------------------


def test_remote_is_none_on_a_local_only_repo(repo: Path) -> None:
    """Null is a first-class case per the schema, not degraded mode."""
    assert gitrepo.remote_url(repo) is None
    assert gitrepo.slug(repo) == "repo"


def test_slug_comes_from_the_remote_when_there_is_one(repo: Path) -> None:
    git(repo, "remote", "add", "origin", "git@github.com:acme/payments-service.git")

    assert gitrepo.slug(repo) == "acme/payments-service"


def test_branch_is_none_in_detached_head(repo: Path) -> None:
    assert gitrepo.current_branch(repo) == "main"
    git(repo, "checkout", "-q", "--detach")
    assert gitrepo.current_branch(repo) is None


def test_parent_of_root_commit_is_none(repo: Path) -> None:
    assert gitrepo.parent_of(repo, gitrepo.resolve(repo, "HEAD")) is None


def test_is_repo_false_outside_a_repository(tmp_path: Path) -> None:
    assert gitrepo.is_repo(tmp_path / "nowhere") is False
