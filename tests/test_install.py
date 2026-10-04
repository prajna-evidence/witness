"""Hook installation.

The properties pinned here are the ones whose failure is silent. A duplicated hook
double-counts events and overstates the record; a clobbered settings file destroys
someone else's configuration; a missing matcher on a tool event changes which calls are
seen at all. None of these raise, and none are visible until an auditor asks why the
numbers are wrong.
"""

from __future__ import annotations

import json
import pathlib

from witness import install


def _settings(root: pathlib.Path, local: bool = False) -> dict:
    return json.loads(install.settings_path(root, local).read_text(encoding="utf-8"))


def _ours(entries: list) -> list:
    return [e for e in entries if install._is_ours(e)]


def test_install_covers_every_consumed_event(tmp_path: pathlib.Path) -> None:
    report = install.install(tmp_path)

    assert set(report) == set(install.HOOK_EVENTS)
    assert set(report.values()) == {"added"}

    hooks = _settings(tmp_path)["hooks"]
    for event in install.HOOK_EVENTS:
        assert len(_ours(hooks[event])) == 1, event


def test_tool_events_carry_a_matcher_and_session_events_do_not(tmp_path: pathlib.Path) -> None:
    install.install(tmp_path)
    hooks = _settings(tmp_path)["hooks"]

    for event in install.TOOL_EVENTS:
        assert _ours(hooks[event])[0]["matcher"] == install.MATCHER

    for event in set(install.HOOK_EVENTS) - set(install.TOOL_EVENTS):
        assert "matcher" not in _ours(hooks[event])[0]


def test_install_is_idempotent(tmp_path: pathlib.Path) -> None:
    install.install(tmp_path)
    report = install.install(tmp_path)

    assert set(report.values()) == {"already-present"}

    hooks = _settings(tmp_path)["hooks"]
    for event in install.HOOK_EVENTS:
        # One hook, not two. A second would append every event twice, which is a false
        # statement about what happened even though nothing was fabricated.
        assert len(_ours(hooks[event])) == 1, event


def test_install_preserves_foreign_hooks_and_unrelated_settings(tmp_path: pathlib.Path) -> None:
    path = install.settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "model": "opus",
                "hooks": {
                    "PostToolUse": [
                        {"matcher": "Write", "hooks": [{"type": "command", "command": "other-tool"}]}
                    ],
                    "Notification": [{"hooks": [{"type": "command", "command": "notify-me"}]}],
                },
            }
        ),
        encoding="utf-8",
    )

    install.install(tmp_path)
    settings = _settings(tmp_path)

    assert settings["model"] == "opus"
    assert settings["hooks"]["Notification"][0]["hooks"][0]["command"] == "notify-me"

    post = settings["hooks"]["PostToolUse"]
    assert len(post) == 2
    assert any(e.get("matcher") == "Write" for e in post)
    assert len(_ours(post)) == 1


def test_install_does_not_rewrite_a_hand_narrowed_matcher(tmp_path: pathlib.Path) -> None:
    """Someone who narrowed our matcher on purpose keeps their edit."""
    path = install.settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "PostToolUse": [
                        {"matcher": "Edit", "hooks": [{"type": "command", "command": install.COMMAND}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    report = install.install(tmp_path)

    assert report["PostToolUse"] == "already-present"
    assert _settings(tmp_path)["hooks"]["PostToolUse"][0]["matcher"] == "Edit"


def test_uninstall_removes_only_our_entries(tmp_path: pathlib.Path) -> None:
    path = install.settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "model": "opus",
                "hooks": {
                    "PostToolUse": [
                        {"matcher": "Write", "hooks": [{"type": "command", "command": "other-tool"}]}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    install.install(tmp_path)
    install.uninstall(tmp_path)
    settings = _settings(tmp_path)

    assert settings["model"] == "opus"
    assert settings["hooks"]["PostToolUse"] == [
        {"matcher": "Write", "hooks": [{"type": "command", "command": "other-tool"}]}
    ]
    for event in set(install.HOOK_EVENTS) - {"PostToolUse"}:
        assert event not in settings["hooks"]


def test_uninstall_removes_a_file_that_only_ever_held_our_hooks(tmp_path: pathlib.Path) -> None:
    install.install(tmp_path)
    install.uninstall(tmp_path)

    # Left as we found it: absent, not an empty object.
    assert not install.settings_path(tmp_path).exists()


def test_uninstall_on_a_clean_repo_is_a_no_op(tmp_path: pathlib.Path) -> None:
    assert install.uninstall(tmp_path) == {}


def test_local_flag_targets_the_uncommitted_settings_file(tmp_path: pathlib.Path) -> None:
    install.install(tmp_path, local=True)

    assert install.settings_path(tmp_path, local=True).exists()
    assert not install.settings_path(tmp_path).exists()


def test_raw_captures_are_gitignored(tmp_path: pathlib.Path) -> None:
    """Raw output is unnormalised and may hold whatever the agent read. The bundle is
    the artifact that gets committed; this is not."""
    install.install(tmp_path)

    assert "raw/" in (tmp_path / ".witness" / ".gitignore").read_text(encoding="utf-8")


def test_existing_gitignore_is_not_clobbered(tmp_path: pathlib.Path) -> None:
    target = tmp_path / ".witness" / ".gitignore"
    target.parent.mkdir(parents=True)
    target.write_text("raw/\nscratch/\n", encoding="utf-8")

    install.install(tmp_path)

    assert "scratch/" in target.read_text(encoding="utf-8")


def test_settings_file_with_blank_content_is_tolerated(tmp_path: pathlib.Path) -> None:
    path = install.settings_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("\n", encoding="utf-8")

    install.install(tmp_path)

    assert len(_ours(_settings(tmp_path)["hooks"]["Stop"])) == 1
