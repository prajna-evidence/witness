"""The hot path, and the only code that runs inside a hook.

This module appends a line to a file and does nothing else. No parsing, no
normalisation, no schema validation, no git. That separation is decision S10, and it
is what makes an interpreted language viable here: a hook fires on every tool call,
and a parser in that path is how an observability tool gets uninstalled in week two.

It also never fails the caller. A capture that raises would break the agent it is
meant to be observing, which is a far worse outcome than a missing record - and the
missing record is itself detectable later, because the normaliser reports gaps rather
than silently shortening the run.
"""

from __future__ import annotations

import json
import os
import pathlib
from datetime import datetime, timezone

RAW_DIRNAME = ".witness/raw"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def raw_dir(root: "str | os.PathLike[str] | None" = None) -> pathlib.Path:
    base = pathlib.Path(root) if root is not None else pathlib.Path.cwd()
    return base / RAW_DIRNAME


def append(event: dict, root: "str | os.PathLike[str] | None" = None, now: "str | None" = None) -> "pathlib.Path | None":
    """Append one captured event. Returns the file written, or None if capture failed.

    The wrapper adds `captured_at` because hook payloads carry no timestamp of their
    own. That is the host's limit, not ours, and the normaliser records it as such:
    our capture time is the best available clock and may lag the event.
    """
    try:
        session = str(event.get("session_id") or "unknown-session")
        safe = "".join(c for c in session if c.isalnum() or c in "-_")[:64] or "unknown-session"
        directory = raw_dir(root)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{safe}.jsonl"
        line = json.dumps(
            {"captured_at": now or _utc_now_iso(), "event": event},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return path
    except Exception:  # noqa: BLE001 - never break the agent being observed
        return None


def read(path: "str | os.PathLike[str]") -> list[dict]:
    """Read a raw capture file. Malformed lines are skipped and counted by the caller."""
    out: list[dict] = []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"_malformed": line})
    return out
