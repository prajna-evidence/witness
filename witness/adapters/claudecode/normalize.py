"""Normalise Claude Code hook captures into observations.

Pure: raw captured lines in, observations out. No clock, no filesystem, no network -
everything that varies is derived from the input, which is what lets the conformance
kit demand byte-for-byte reproduction.

WHAT THIS HOST DOES NOT GIVE US, and therefore what is nulled with a reason rather
than invented:

- **No event timestamp.** Hook payloads carry none, so `timestamp` is our capture
  clock. Recorded honestly: the gap between the event and our capture is unmeasurable
  from here, and pretending otherwise would put a fabricated precision into evidence.
- **No model id, tokens or cost on the hook channel.** Those live in the transcript,
  which is a separate read (W2b).
- **No task identity.** `trace_id` is required by the journal-event contract and
  Claude Code has no task concept, so the session is the correlation key.

WHAT IT DOES GIVE US THAT MATTERS: `permission_mode`. A session run under
`bypassPermissions` or `acceptEdits` has a materially different governance story from
one run under `default`, and that distinction is mapped to a gate rather than dropped.
"""

from __future__ import annotations

import json
import pathlib
import uuid
from typing import Any, Iterable

from witness import tiers

#: Default root Claude Code writes session transcripts under. Overridable so tests and
#: callers with a nonstandard CLAUDE_HOME never touch the real one.
DEFAULT_CLAUDE_HOME = pathlib.Path.home() / ".claude"

MANIFEST = json.loads((pathlib.Path(__file__).parent / "manifest.json").read_text())

ADAPTER_VERSION = f"{MANIFEST['adapter']}/{MANIFEST['version']}"
HOST = MANIFEST["host"]

#: Fixed namespace so identifiers are reproducible across runs and machines.
NAMESPACE = uuid.UUID("6f9a1c52-3d84-5b17-9e0a-2c4d8f6b1a03")

EVENT_NAMES = {
    "UserPromptSubmit": "intent.submitted",
    "PreToolUse": "tool.requested",
    "PostToolUse": "tool.completed",
    "SessionStart": "session.started",
    "SessionEnd": "session.ended",
    "Stop": "turn.completed",
}

#: Tools whose use is unambiguously a code-phase act. Everything else gets a null
#: phase with a reason, because inferring "build" from a shell command line is a guess
#: dressed as evidence, and SPEC.md forbids filling a field by inference.
CODE_TOOLS = frozenset({"Write", "Edit", "NotebookEdit", "MultiEdit"})

#: Permission modes that mean a human was not asked. Mapped to `auto_approved`, which
#: the bundle deliberately keeps distinct from `approved` - a policy override and a
#: human decision are not the same evidence.
UNATTENDED_MODES = frozenset({"bypassPermissions", "acceptEdits", "auto", "dontAsk"})


def _as_uuid(value: str, kind: str) -> str:
    """Claude Code session ids are usually UUIDs but are not contractually so, while
    journal-event requires the UUID form. A non-UUID is mapped deterministically
    rather than rejected - losing a whole session over an identifier format would be
    a worse failure than deriving one."""
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return str(uuid.uuid5(NAMESPACE, f"{kind}:{value}"))


def _audit_id(session: str, seq: int, hook_event: str, tool_use_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{session}|{seq}|{hook_event}|{tool_use_id}"))


def _source(collected_at: str) -> dict[str, Any]:
    return {
        "host": HOST,
        "channel": "hook",
        "tier": tiers.TIER_SELF_REPORTED,
        "collected_at": collected_at,
        "retrievable_from": None,
        "adapter_version": ADAPTER_VERSION,
    }


def _transcript_source(collected_at: str) -> dict[str, Any]:
    return {
        "host": HOST,
        "channel": "transcript",
        # Still tier C: the transcript is a second self-report, not a third party.
        # Reading it under a different name would be exactly the "corroboration
        # upgrades a tier" mistake S3 exists to forbid.
        "tier": tiers.TIER_SELF_REPORTED,
        "collected_at": collected_at,
        "retrievable_from": None,
        "adapter_version": ADAPTER_VERSION,
    }


def transcript_path(
    session_id: str, cwd: "str | pathlib.Path", claude_home: "pathlib.Path | None" = None
) -> pathlib.Path:
    """Where Claude Code writes this session's transcript.

    Reverse-engineered from observed output, not documented by the host: one file per
    session under `~/.claude/projects/<cwd, "/" -> "-">/<session-id>.jsonl`. If this
    convention ever changes, callers can bypass it entirely by passing an explicit path
    to `normalize_transcript` - this function is a default, not a contract.
    """
    home = claude_home or DEFAULT_CLAUDE_HOME
    slug = str(cwd).replace("/", "-")
    return home / "projects" / slug / f"{session_id}.jsonl"


def _turn_from_line(seq: int, line: dict[str, Any]) -> "dict[str, Any] | None":
    """One `journal-event` `model_turns[]` row from one transcript line, or None if the
    line is not a model turn with usage we can report (a user message, a sidechain
    summary, tool-result bookkeeping, or an assistant line the host wrote without a
    usage block - all real cases, none of them a model turn to report on)."""
    if line.get("type") != "assistant":
        return None
    message = line.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict) or "input_tokens" not in usage or "output_tokens" not in usage:
        return None

    tokens: dict[str, int] = {
        "input": usage["input_tokens"],
        "output": usage["output_tokens"],
    }
    if "cache_read_input_tokens" in usage:
        tokens["cache_read"] = usage["cache_read_input_tokens"]
    if "cache_creation_input_tokens" in usage:
        tokens["cache_write"] = usage["cache_creation_input_tokens"]

    entrypoint = line.get("entrypoint")
    transport = "claude-cli" if entrypoint == "cli" else entrypoint

    return {
        "seq": seq,
        "at": line.get("timestamp"),
        "phase": None,
        "host": HOST,
        "transport": transport,
        "model_id": message.get("model"),
        "effort": line.get("effort"),
        "tokens": tokens,
        # No price table yet (W2b scope, see manifest.json notes).
        "cost_usd": None,
        "injected_units": None,
    }


def normalize_transcript(lines: Iterable[dict[str, Any]], collected_at: "str | None" = None) -> dict[str, Any]:
    """Normalise one session transcript into `model_turns`.

    Pure and separate from `normalize_session`: the hook channel and the transcript
    channel are read independently (different files, different shapes) and only
    combined by the caller (`bundle.assemble`). A transcript with zero usable lines is
    not an error - it produces an empty turn list, same as a session with no transcript
    file at all, and the schema permits that only when the bundle's floor is already C
    (evidence-bundle.schema.json's allOf), which is exactly this adapter's ceiling.
    """
    turns: list[dict[str, Any]] = []
    seq = 0
    for line in lines:
        if "_malformed" in line:
            continue
        turn = _turn_from_line(seq, line)
        if turn is None:
            continue
        turns.append(turn)
        seq += 1

    source = _transcript_source(collected_at or (turns[-1]["at"] if turns else ""))
    return {"model_turns": turns, "source": source if turns else None}


def _phase(hook_event: str, tool_name: str) -> tuple[str | None, str | None]:
    """Returns (phase, reason_if_null)."""
    if hook_event == "UserPromptSubmit":
        return "intent", None
    if hook_event in ("PreToolUse", "PostToolUse"):
        if tool_name in CODE_TOOLS:
            return "code", None
        return None, tiers.HOST_DOES_NOT_EMIT
    return None, tiers.NOT_APPLICABLE


def _actor(event: dict[str, Any]) -> str:
    agent_type = event.get("agent_type")
    return f"agent:claude-code/{agent_type}" if agent_type else "agent:claude-code"


def normalize_session(captures: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Normalise one session's raw captures.

    Returns {"observations": [...], "gates": [...], "gaps": [...]}.
    """
    observations: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []
    seen_modes: set[str] = set()
    pending: dict[str, dict[str, Any]] = {}
    completed: set[str] = set()
    malformed = 0

    for seq, capture in enumerate(captures):
        if "_malformed" in capture:
            malformed += 1
            continue
        event = capture.get("event") or {}
        collected_at = capture.get("captured_at") or ""
        hook_event = str(event.get("hook_event_name") or "")
        raw_session = str(event.get("session_id") or "unknown-session")
        session_uuid = _as_uuid(raw_session, "session")
        tool_name = str(event.get("tool_name") or "")
        tool_use_id = str(event.get("tool_use_id") or "")

        mode = event.get("permission_mode")
        if isinstance(mode, str):
            seen_modes.add(mode)

        phase, phase_reason = _phase(hook_event, tool_name)

        unavailable: dict[str, str] = {
            "/tokens": tiers.HOST_DOES_NOT_EMIT,
            "/cost_usd": tiers.HOST_DOES_NOT_EMIT,
            "/injected_units": tiers.NOT_APPLICABLE,
        }
        if phase_reason:
            unavailable["/phase"] = phase_reason

        payload: dict[str, Any] = {"unavailable": unavailable}
        if tool_name:
            payload["tool_name"] = tool_name
        if tool_use_id:
            payload["tool_use_id"] = tool_use_id
        if isinstance(mode, str):
            payload["permission_mode"] = mode
        effort = event.get("effort")
        if isinstance(effort, dict) and effort.get("level"):
            payload["effort"] = effort["level"]
        if hook_event in ("PreToolUse", "PostToolUse"):
            target = _tool_target(event)
            if target:
                payload["target"] = target

        observations.append(
            {
                "audit_id": _audit_id(raw_session, seq, hook_event, tool_use_id),
                "session_id": session_uuid,
                "timestamp": collected_at,
                "event": EVENT_NAMES.get(hook_event, f"hook.{hook_event or 'unknown'}"),
                "actor": _actor(event),
                "trace_id": raw_session,
                "task_id": None,
                "repo_id": None,
                "phase": phase,
                "tokens": None,
                "cost_usd": None,
                "injected_units": None,
                "prev_hash": None,
                "entry_hash": None,
                "payload": payload,
                "source": _source(collected_at),
            }
        )

        if hook_event == "PreToolUse" and tool_use_id:
            pending[tool_use_id] = {
                "seq": seq,
                "session": raw_session,
                "collected_at": collected_at,
                "tool_name": tool_name,
                "event": event,
            }
        elif hook_event == "PostToolUse" and tool_use_id:
            completed.add(tool_use_id)

    gaps = _gap_observations(pending, completed)
    observations.extend(gaps)

    # A gate is only emitted where we can name what actually happened.
    #
    # An unattended mode is a POSITIVE finding: no human was asked, and `auto_approved`
    # says exactly that. An interactive mode is not the mirror image of it - it tells us
    # a permission prompt regime was in force, not that any particular prompt was shown
    # or answered. Emitting `approved` with a placeholder actor would manufacture a human
    # decision out of a configuration value, which is the failure mode this format exists
    # to prevent. So interactive modes produce no gate and a reason instead.
    gates_unavailable: dict[str, str] = {}
    for mode in sorted(seen_modes):
        if mode in UNATTENDED_MODES:
            gates.append(
                {
                    "gate": "tool-permission",
                    "decision": "auto_approved",
                    "actor": None,
                    "at": _first_collected(observations),
                    "reason": f"claude-code permission_mode={mode}",
                    "tier": tiers.TIER_SELF_REPORTED,
                }
            )
        else:
            gates_unavailable["/gates"] = tiers.HOST_DOES_NOT_EMIT

    return {
        "gates": gates,
        "gates_unavailable": gates_unavailable,
        "gaps": [g["payload"]["tool_use_id"] for g in gaps],
        "malformed_lines": malformed,
        "observations": observations,
    }


def _tool_target(event: dict[str, Any]) -> str | None:
    """The one field of tool_input worth lifting: what was acted on. Everything else
    stays in the raw capture rather than being copied into evidence, because a tool
    input can contain anything and this file does not redact."""
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "notebook_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _gap_observations(pending: dict[str, dict[str, Any]], completed: set[str]) -> list[dict[str, Any]]:
    """A tool call that was requested and never reported as completed is a HOLE, and
    the record says so.

    The alternative - dropping the unmatched request, or assuming it succeeded - is
    the failure this whole format exists to prevent: it turns a limit of the evidence
    into a silent claim about what happened.
    """
    out: list[dict[str, Any]] = []
    for tool_use_id, info in pending.items():
        if tool_use_id in completed:
            continue
        # Same phase rule as the request it stands for, not a special case: the reason
        # we cannot name the phase is the host, and that does not change because the
        # outcome went missing.
        phase, phase_reason = _phase("PreToolUse", info["tool_name"])
        out.append(
            {
                "audit_id": _audit_id(info["session"], info["seq"], "GapOutcomeUnknown", tool_use_id),
                "session_id": _as_uuid(info["session"], "session"),
                "timestamp": info["collected_at"],
                "event": "tool.outcome_unknown",
                "actor": _actor(info["event"]),
                "trace_id": info["session"],
                "task_id": None,
                "repo_id": None,
                "phase": phase,
                "tokens": None,
                "cost_usd": None,
                "injected_units": None,
                "prev_hash": None,
                "entry_hash": None,
                "payload": {
                    "tool_name": info["tool_name"],
                    "tool_use_id": tool_use_id,
                    "error": "PreToolUse captured with no matching PostToolUse; the outcome of this tool call is unknown to us",
                    "unavailable": {
                        "/payload/tool_response": tiers.COLLECTION_FAILED,
                        "/tokens": tiers.HOST_DOES_NOT_EMIT,
                        "/cost_usd": tiers.HOST_DOES_NOT_EMIT,
                        "/injected_units": tiers.NOT_APPLICABLE,
                        **({"/phase": phase_reason} if phase_reason else {}),
                    },
                },
                "source": _source(info["collected_at"]),
            }
        )
    return sorted(out, key=lambda o: o["audit_id"])


def _first_collected(observations: list[dict[str, Any]]) -> str:
    return observations[0]["timestamp"] if observations else ""
