"""Claude Code adapter: hook capture to normalised observations."""

from witness import raw as _raw

from .normalize import MANIFEST, normalize_session, normalize_transcript, transcript_path

__all__ = ["MANIFEST", "normalize_session", "normalize_transcript", "transcript_path", "collect_model_turns"]


def collect_model_turns(root, session_ids):
    """Optional adapter hook `bundle.assemble` calls when present (W2b).

    Reads each session's transcript by Claude Code's on-disk convention, normalises it,
    and returns the union. A missing transcript file is not an error - it is the normal
    state for an old session or a machine that never had one - so it is simply skipped
    rather than raising; the bundle still gets whatever sessions do have one.
    """
    turns: list = []
    sources: list = []
    for session_id in session_ids:
        path = transcript_path(session_id, root)
        if not path.is_file():
            continue
        result = normalize_transcript(_raw.read(path))
        turns.extend(result["model_turns"])
        if result["source"]:
            sources.append(result["source"])
    return {"model_turns": turns, "sources": sources}
