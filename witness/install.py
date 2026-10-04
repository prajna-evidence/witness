"""Hook installation. Cold path, runs once, never during a session.

`init` exists because the alternative is a README asking people to hand-edit JSON, and
a capture that depends on hand-edited JSON is a capture that is silently absent on most
machines. An evidence tool whose first failure mode is "nobody installed it correctly"
cannot make claims about coverage.

Two properties matter more than convenience here:

*Idempotent.* Running it twice leaves one hook, not two. A duplicated hook would append
every event twice and inflate the record, which is a false statement about what happened
even though nothing was fabricated.

*Additive.* The settings file belongs to the user, not to us. Hooks we did not write are
preserved exactly, and `--uninstall` removes only our own entries. We identify ours by the
command string and by nothing else - not by position, not by index - because any other
handle breaks the moment someone reorders the file by hand.

The hook is written to the PROJECT settings file by default, not the user's. That is a
deliberate choice and it is the auditable one: a committed hook makes "capture was enabled
on this branch, from this commit onward" a fact anchored in git history rather than an
assertion about someone's laptop. `--local` opts out for anyone who wants it per-machine.

Raw captures are gitignored on purpose. The bundle is the artifact that gets committed
(`.witness/evidence/`); `.witness/raw/` is unnormalised hot-path output that may contain
whatever the agent happened to read, and committing it would be a redaction problem we
have not solved and do not need to.
"""

from __future__ import annotations

import json
import pathlib
import shutil

# Every hook event the claudecode adapter consumes. Narrowing this set does not make the
# record smaller, it makes it wrong: the normaliser pairs PreToolUse with PostToolUse and
# reports an unpaired call as a gap, so dropping one event manufactures gaps that did not
# happen. Adding a sixth event is an adapter change first, and this list follows it.
HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")

# Events that take a tool matcher. The rest are session-level and take none.
TOOL_EVENTS = ("PreToolUse", "PostToolUse")

# Match every tool. A filtered matcher would hide exactly the calls an auditor asks about.
MATCHER = "*"

COMMAND = "witness capture"

SETTINGS_PROJECT = ".claude/settings.json"
SETTINGS_LOCAL = ".claude/settings.local.json"

GITIGNORE_BODY = "# Raw hot-path capture. Unnormalised; never committed.\nraw/\n"


def _is_ours(entry: dict) -> bool:
    """True if this matcher block was written by us.

    Identified by command string only. Anything else - index, order, a marker key we
    invented - breaks when the file is edited by hand, which it will be.
    """
    for hook in entry.get("hooks", []):
        if isinstance(hook, dict) and hook.get("command") == COMMAND:
            return True
    return False


def _entry_for(event: str) -> dict:
    entry: dict = {"hooks": [{"type": "command", "command": COMMAND}]}
    if event in TOOL_EVENTS:
        # Key order matters only for readability of the settings file a human will open.
        entry = {"matcher": MATCHER, **entry}
    return entry


def _load(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    return json.loads(text)


def _write(path: pathlib.Path, settings: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def settings_path(root: pathlib.Path, local: bool = False) -> pathlib.Path:
    return root / (SETTINGS_LOCAL if local else SETTINGS_PROJECT)


def install(root: pathlib.Path, local: bool = False) -> dict:
    """Add the capture hook for every consumed event. Returns a per-event report.

    Values are "added" or "already-present". Never "updated": if a block of ours exists
    we leave it alone, because rewriting it would silently discard a matcher someone
    narrowed on purpose.
    """
    path = settings_path(root, local)
    settings = _load(path)
    hooks = settings.setdefault("hooks", {})
    report: dict[str, str] = {}

    for event in HOOK_EVENTS:
        entries = hooks.setdefault(event, [])
        if any(_is_ours(e) for e in entries if isinstance(e, dict)):
            report[event] = "already-present"
            continue
        entries.append(_entry_for(event))
        report[event] = "added"

    _write(path, settings)
    _write_raw_gitignore(root)
    return report


def uninstall(root: pathlib.Path, local: bool = False) -> dict:
    """Remove only our entries. Hooks written by anyone else are untouched.

    Empty structures we emptied are pruned, so uninstalling leaves the file as close to
    how we found it as we can get. A settings file that only ever held our hooks is
    removed entirely rather than left as `{}`.
    """
    path = settings_path(root, local)
    if not path.exists():
        return {}

    settings = _load(path)
    hooks = settings.get("hooks", {})
    report: dict[str, str] = {}

    for event in list(hooks):
        entries = hooks[event]
        if not isinstance(entries, list):
            continue
        kept = [e for e in entries if not (isinstance(e, dict) and _is_ours(e))]
        if len(kept) != len(entries):
            report[event] = "removed"
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]

    if not hooks:
        settings.pop("hooks", None)

    if settings:
        _write(path, settings)
    else:
        path.unlink()

    return report


def _write_raw_gitignore(root: pathlib.Path) -> None:
    """Keep `.witness/raw/` out of git without touching the repo's own .gitignore."""
    target = root / ".witness" / ".gitignore"
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(GITIGNORE_BODY, encoding="utf-8")


def resolve_command() -> "str | None":
    """Absolute path of the `witness` entry point, or None if it is not on PATH.

    Reported rather than repaired. Rewriting the hook to an absolute interpreter path
    would bind the hook to one virtualenv and break the moment it is rebuilt, so the
    honest move is to install the command on PATH and say so when it is not.
    """
    return shutil.which("witness")
