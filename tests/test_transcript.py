"""The Claude Code transcript channel (W2b).

Fixture lines below are trimmed from a real transcript captured against this
repository's own session on 2026-09-23 - not invented, because the shape most likely to
drift is exactly the one nobody hand-wrote a fixture for.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from jsonschema import Draft202012Validator

from witness import bundle, gitrepo, raw, tiers, ulid
from witness.adapters.claudecode import normalize_transcript, transcript_path

ROOT = pathlib.Path(__file__).resolve().parents[1]

ASSISTANT_LINE = {
    "parentUuid": "c301d250-beb2-4413-8010-449248139115",
    "isSidechain": False,
    "message": {
        "model": "claude-sonnet-5",
        "id": "msg_011CfLHxsVvQtTTNUVft5QUx",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "..."}],
        "stop_reason": "tool_use",
        "usage": {
            "input_tokens": 2,
            "cache_creation_input_tokens": 19956,
            "cache_read_input_tokens": 36019,
            "output_tokens": 259,
        },
    },
    "requestId": "req_011CfLHxs39AYmfseFZomvQv",
    "type": "assistant",
    "uuid": "0725fb9a-47cd-4d75-aca4-c121a5f5c0dd",
    "timestamp": "2026-09-23T11:29:11.333Z",
    "effort": "high",
    "session_id": "d0ae0945-18fc-4eec-a8a3-31e266d6f09c",
    "userType": "external",
    "entrypoint": "cli",
    "cwd": "/Users/dev/source/witness",
    "sessionId": "d0ae0945-18fc-4eec-a8a3-31e266d6f09c",
    "version": "2.1.248",
    "gitBranch": "main",
}

USER_LINE = {
    "parentUuid": None,
    "isSidechain": False,
    "type": "user",
    "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
    "uuid": "aaaa",
    "timestamp": "2026-09-23T11:29:00.000Z",
    "sessionId": "d0ae0945-18fc-4eec-a8a3-31e266d6f09c",
}


# ---- normalize_transcript -------------------------------------------------------------


def test_an_assistant_line_becomes_one_model_turn() -> None:
    result = normalize_transcript([ASSISTANT_LINE])
    assert len(result["model_turns"]) == 1
    turn = result["model_turns"][0]
    assert turn["model_id"] == "claude-sonnet-5"
    assert turn["tokens"] == {"input": 2, "output": 259, "cache_read": 36019, "cache_write": 19956}
    assert turn["effort"] == "high"
    assert turn["host"] == "claude-code"
    assert turn["transport"] == "claude-cli"
    assert turn["at"] == "2026-09-23T11:29:11.333Z"
    assert turn["cost_usd"] is None


def test_the_turn_validates_against_the_bundle_schema_fragment() -> None:
    """model_turns[] has no standalone schema file - it is inlined in
    evidence-bundle.schema.json - so this pins the shape against that file directly."""
    schema_doc = json.loads((ROOT / "schemas" / "evidence-bundle.schema.json").read_text())
    item_schema = schema_doc["properties"]["model_turns"]["items"]
    validator = Draft202012Validator(item_schema)
    turn = normalize_transcript([ASSISTANT_LINE])["model_turns"][0]
    errors = list(validator.iter_errors(turn))
    assert not errors, [e.message for e in errors]


def test_a_user_line_contributes_no_turn() -> None:
    assert normalize_transcript([USER_LINE])["model_turns"] == []


def test_an_assistant_line_with_no_usage_block_is_skipped_not_fabricated() -> None:
    line = {**ASSISTANT_LINE, "message": {**ASSISTANT_LINE["message"], "usage": None}}
    assert normalize_transcript([line])["model_turns"] == []


def test_malformed_lines_are_skipped() -> None:
    assert normalize_transcript([{"_malformed": "not json"}])["model_turns"] == []


def test_seq_is_assigned_in_order_of_appearance() -> None:
    turns = normalize_transcript([ASSISTANT_LINE, USER_LINE, ASSISTANT_LINE])["model_turns"]
    assert [t["seq"] for t in turns] == [0, 1]


def test_an_empty_transcript_contributes_no_source() -> None:
    """No turns worth reporting means no claim was made, so no source names the
    transcript channel as having contributed - matches _dedupe_sources' contract that a
    source in the list asserts it produced something."""
    result = normalize_transcript([USER_LINE])
    assert result["source"] is None


def test_a_nonempty_transcript_names_the_transcript_channel_at_tier_c() -> None:
    result = normalize_transcript([ASSISTANT_LINE])
    assert result["source"]["channel"] == "transcript"
    assert result["source"]["tier"] == tiers.TIER_SELF_REPORTED


# ---- transcript_path --------------------------------------------------------------


def test_transcript_path_follows_the_observed_convention(tmp_path: pathlib.Path) -> None:
    home = tmp_path / "dothome"
    path = transcript_path("abc-123", "/Users/x/source/witness", claude_home=home)
    assert path == home / "projects" / "-Users-x-source-witness" / "abc-123.jsonl"


# ---- wired into bundle.assemble (W2b acceptance) -----------------------------------


def git(repo: pathlib.Path, *args: str) -> None:
    import subprocess

    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        env={
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.com",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.com",
            # Fixed, and before every fixture's captured_at in this file (earliest is
            # 11:00) - real commits otherwise land at the real wall-clock time pytest
            # runs, which bundle.assemble now uses as a lower bound (S19) and would
            # exclude these fixtures' captures as predating their own base commit.
            "GIT_AUTHOR_DATE": "2026-09-23T09:00:00Z", "GIT_COMMITTER_DATE": "2026-09-23T09:00:00Z",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
            "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(repo),
        },
    )


@pytest.fixture()
def repo_with_a_capture(tmp_path: pathlib.Path) -> pathlib.Path:
    r = tmp_path / "svc"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "README.md").write_text("base\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    git(r, "checkout", "-q", "-b", "feature")
    (r / "x.py").write_text("x = 1\n")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "add x")

    session = "d0ae0945-18fc-4eec-a8a3-31e266d6f09c"
    raw.append({"session_id": session, "hook_event_name": "UserPromptSubmit"}, root=r, now="2026-09-23T11:00:00Z")
    return r


def test_bundle_assemble_populates_model_turns_from_a_matching_transcript(
    repo_with_a_capture: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "claudehome"
    session = "d0ae0945-18fc-4eec-a8a3-31e266d6f09c"
    transcript_dir = home / "projects" / str(repo_with_a_capture).replace("/", "-")
    transcript_dir.mkdir(parents=True)
    (transcript_dir / f"{session}.jsonl").write_text(json.dumps(ASSISTANT_LINE) + "\n")

    import witness.adapters.claudecode.normalize as normalize_mod

    monkeypatch.setattr(normalize_mod, "DEFAULT_CLAUDE_HOME", home)

    doc = bundle.assemble(
        repo_with_a_capture, base=gitrepo.resolve(repo_with_a_capture, "main"), now="2026-09-23T12:00:00Z"
    )

    assert len(doc["model_turns"]) == 1
    assert doc["model_turns"][0]["model_id"] == "claude-sonnet-5"
    assert any(s["channel"] == "transcript" for s in doc["sources"])
    # still tier C: the transcript is a second self-report, S3 forbids treating it as more
    assert doc["tier_floor"] == tiers.TIER_SELF_REPORTED


def test_bundle_assemble_is_unaffected_by_a_missing_transcript(
    repo_with_a_capture: pathlib.Path, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W2b's explicit acceptance criterion: a session with no transcript must still
    produce a valid bundle, not an error and not a fabricated turn."""
    import witness.adapters.claudecode.normalize as normalize_mod

    monkeypatch.setattr(normalize_mod, "DEFAULT_CLAUDE_HOME", tmp_path / "empty-claudehome")

    doc = bundle.assemble(
        repo_with_a_capture, base=gitrepo.resolve(repo_with_a_capture, "main"), now="2026-09-23T12:00:00Z"
    )
    assert doc["model_turns"] == []
    assert doc["tier_floor"] == tiers.TIER_SELF_REPORTED

    from witness import verify

    report = verify.verify_offline(doc, repo_with_a_capture)
    assert report["ok"], report
