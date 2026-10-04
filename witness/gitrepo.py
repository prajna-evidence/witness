"""Git plumbing, read-only.

Every read here goes through a tree object, never the working tree. That is decision S?
in spirit and handoff rule 5 in practice, and it is the single thing most likely to be
got wrong under demo pressure, because hashing the working tree is easier and produces an
identical-looking bundle on the day it is made. It stops being identical the moment
anyone checks out a different branch, and an artifact that verifies only on the day it
was written is not evidence.

Plumbing commands only (`cat-file`, `ls-tree`, `diff-tree`, `rev-parse`). Porcelain
output is explicitly not a stable interface and changes between git versions; a
normaliser that silently mis-parses it would produce a bundle that is wrong rather than
absent, which is the worse failure for this product.

No third-party dependency. The package ships with one (`jsonschema`) and the install
story is part of the wedge.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
-----------------------------------------
It does not treat `commit_sha` as durable. A branch commit does not survive a squash
merge, and after the branch is deleted it is unreachable and eventually collected. The
content hashes recorded from its tree do survive, because sha256 of file bytes is
content-addressed and independent of which commit happens to contain it. Locating and
verifying are therefore separate operations with separate failure modes, and callers are
expected to keep them separate too.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

# Actions recorded per file. Mirrors the `files[].action` enum in the bundle schema.
# Verbs come from the bundle schema's files[].action enum, which says "created",
# not "added". git's own status letter is "A"; the contract wins.
CREATED = "created"
MODIFIED = "modified"
DELETED = "deleted"

_STATUS_TO_ACTION = {"A": CREATED, "M": MODIFIED, "D": DELETED}


class GitError(RuntimeError):
    """A git command failed. Raised rather than swallowed: the cold path may fail loudly."""


def _run(root: Path, *args: str, binary: bool = False) -> "str | bytes":
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed ({proc.returncode}): "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout if binary else proc.stdout.decode("utf-8")


def is_repo(root: Path) -> bool:
    try:
        return _run(root, "rev-parse", "--is-inside-work-tree").strip() == "true"
    except GitError:
        return False


def resolve(root: Path, rev: str) -> str:
    """Full 40-char sha for a revision."""
    return _run(root, "rev-parse", "--verify", f"{rev}^{{commit}}").strip()


def exists(root: Path, sha: str) -> bool:
    """True if the object is present in this clone.

    False is an ordinary answer, not an error: after a squash merge and branch delete,
    the original commit is legitimately gone. Callers report that; they do not fail on it.
    """
    try:
        _run(root, "cat-file", "-e", f"{sha}^{{commit}}")
        return True
    except GitError:
        return False


def tree_of(root: Path, commit: str) -> str:
    """Tree object sha of a commit."""
    return _run(root, "rev-parse", f"{commit}^{{tree}}").strip()


def committed_at(root: Path, commit: str) -> int:
    """Committer-date unix timestamp (`%ct`) of a commit.

    A plain epoch integer, not an ISO string: it sidesteps any timezone-format mismatch
    when `bundle.py` compares it against `raw.append`'s `captured_at`, which is always
    UTC. Committer date, not author date - the committer clock is the one that cannot
    predate the commit actually existing in this repository, which is the property the
    comparison depends on.
    """
    return int(_run(root, "show", "-s", "--format=%ct", commit).strip())


def parent_of(root: Path, commit: str) -> "str | None":
    """First parent, or None for a root commit."""
    out = _run(root, "rev-list", "--parents", "-n", "1", commit).split()
    return out[1] if len(out) > 1 else None


def read_at(root: Path, commit: str, path: str) -> bytes:
    """File bytes as stored in the tree at `commit`.

    Never reads the working tree. If this function is ever "optimised" to open the file
    from disk, every claim the bundle makes about file content becomes a claim about
    whatever happens to be checked out at verification time.
    """
    return _run(root, "cat-file", "blob", f"{commit}:{path}", binary=True)  # type: ignore[return-value]


def sha256_at(root: Path, commit: str, path: str) -> str:
    """sha256 of the file bytes at `commit`.

    sha256 of content, not the git blob id - the blob id prefixes a header, and the
    bundle schema is explicit that it wants the bare content hash. The practical
    consequence is the useful one: this value is identical in any repository that holds
    the same bytes, so it survives rebase, squash, cherry-pick and re-clone. It is the
    durable half of the anchor.
    """
    return hashlib.sha256(read_at(root, commit, path)).hexdigest()


def changed_files(root: Path, base: str, head: str) -> list[dict]:
    """Files changed between two commits, as `{path, action}`, sorted by path.

    Renames are decomposed into a delete and an add rather than recorded as a rename.
    A rename is a claim about intent; two content facts are a claim about bytes, and only
    the second is verifiable from the tree alone.
    """
    raw = _run(root, "diff-tree", "--no-commit-id", "--name-status", "-r", "--no-renames", base, head)
    out: list[dict] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        status, _, path = line.partition("\t")
        action = _STATUS_TO_ACTION.get(status.strip()[:1])
        if action is None:  # copies, type changes, unmerged - not silently coerced
            continue
        out.append({"path": path.strip(), "action": action})
    return sorted(out, key=lambda f: f["path"])


def patch_id(root: Path, base: str, head: str) -> "str | None":
    """Stable id for the *diff* between two commits, or None if there is no diff.

    TIER C, AND IT STAYS THERE. This is a correlation hint, never an identity:

    - It is stable across rebase, which is why it is recorded at all.
    - It is NOT stable across a squash of more than one commit. Squashing N commits
      produces the combined diff, whose patch-id matches none of the N originals.

    Treating it as an identity would reintroduce exactly the silent failure this module
    exists to avoid, so it is recorded, labelled, and never used to decide that two
    changes are the same change.
    """
    diff = subprocess.run(
        ["git", "-C", str(root), "diff-tree", "-p", base, head],
        capture_output=True,
        check=False,
    )
    if diff.returncode != 0:
        raise GitError("git diff-tree failed")
    if not diff.stdout.strip():
        return None
    proc = subprocess.run(
        ["git", "-C", str(root), "patch-id", "--stable"],
        input=diff.stdout,
        capture_output=True,
        check=False,
    )
    out = proc.stdout.decode("utf-8").split()
    return out[0] if out else None


def merge_base(root: Path, a: str, b: str) -> "str | None":
    """Common ancestor of two revisions, or None when they share none."""
    try:
        return _run(root, "merge-base", a, b).strip() or None
    except GitError:
        return None


#: Tried in order when no base is given. `origin/HEAD` is first because it names the
#: remote's real default rather than guessing at it; the rest are the guesses.
DEFAULT_BRANCH_CANDIDATES: "tuple[str, ...]" = (
    "origin/HEAD",
    "origin/main",
    "origin/master",
    "main",
    "master",
)


def infer_base(root: Path, head: str) -> "str | None":
    """Best guess at what `head` diverged from.

    Tries the merge-base against the repository's default branch, and falls back to
    `head`'s first parent. Both are guesses, which is why `witness bundle --base` exists
    and why the result is recorded in `anchors.base_commit` rather than left implicit:
    a reader can see which commit the file claims were compared against, and disagree.

    A merge-base equal to `head` means the default branch already contains it - there is
    no change to describe against that base - so the parent is used instead.
    """
    for candidate in DEFAULT_BRANCH_CANDIDATES:
        try:
            resolved = resolve(root, candidate)
        except GitError:
            continue
        base = merge_base(root, resolved, head)
        if base and base != head:
            return base
    return parent_of(root, head)


def current_branch(root: Path) -> "str | None":
    """Branch name, or None in detached HEAD."""
    name = _run(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    return None if name == "HEAD" else name


def remote_url(root: Path, name: str = "origin") -> "str | None":
    """Remote URL, or None.

    Null is a first-class case per the bundle schema, not degraded mode: a local-only
    repository is a legitimate subject, and reporting a remote it does not have would be
    the kind of small invention this format exists to prevent.
    """
    try:
        return _run(root, "remote", "get-url", name).strip() or None
    except GitError:
        return None


def slug(root: Path) -> str:
    """`owner/name` from the remote when there is one, else the directory name."""
    url = remote_url(root)
    if not url:
        return root.resolve().name
    return owner_name(url)


def owner_name(url: str) -> str:
    """`owner/name` from a remote URL (https or scp-style); the input when it has no two parts."""
    trimmed = url[:-4] if url.endswith(".git") else url
    parts = [p for p in trimmed.replace(":", "/").split("/") if p]
    return "/".join(parts[-2:]) if len(parts) >= 2 else trimmed


def find_containing_commit(
    root: Path, path: str, sha256: str, limit: int = 500, after: "str | None" = None
) -> "str | None":
    """Newest commit reachable from HEAD whose tree holds `path` with content `sha256`.

    This is the recovery path for a dead `commit_sha`. After a squash merge and branch
    delete, the commit a bundle names is gone, but the *content* it recorded is still in
    history under a different commit. Finding it restores verification of the file claims
    without pretending the original commit still exists - the two facts are reported
    separately, and the bundle is never rewritten to hide the difference.

    Bounded because it walks history. A miss returns None and the claim degrades honestly.
    `after` excludes that commit and its ancestors, so only content produced after it
    can match.
    """
    revs_spec = ["HEAD", f"^{after}"] if after else ["HEAD"]
    try:
        revs = _run(root, "rev-list", f"--max-count={limit}", *revs_spec, "--", path).split()
    except GitError:
        return None
    for rev in revs:
        try:
            if sha256_at(root, rev, path) == sha256:
                return rev
        except GitError:
            continue
    return None
