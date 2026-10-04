"""Command line surface.

`capture` is the hot path and is deliberately the dumbest command here: read stdin,
append, exit 0. It is wired into a Claude Code hook and runs on every tool call, so it
does no parsing and cannot fail the agent it observes (S10).

`normalize` is the cold path: it runs once, later, and does all the work.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from witness import __version__, bundle as bundle_mod, install, raw, verify as verify_mod, view
from witness.adapters import load


def cmd_init(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root) if args.root else pathlib.Path.cwd()
    path = install.settings_path(root, args.local)

    if args.uninstall:
        report = install.uninstall(root, args.local)
        if not report:
            print(f"no witness hooks in {path}")
            return 0
        for event, state in sorted(report.items()):
            print(f"  {state:15s} {event}")
        print(f"removed from {path}")
        print("note: .witness/raw/ and any committed evidence are left in place")
        return 0

    report = install.install(root, args.local)
    for event, state in sorted(report.items()):
        print(f"  {state:15s} {event}")
    print(f"wrote {path}")

    # Reported, never repaired: binding the hook to an absolute interpreter path would
    # tie it to one virtualenv and break silently when that is rebuilt.
    if install.resolve_command() is None:
        print(
            "warning: `witness` is not on PATH, so the hook will not fire.\n"
            "         install it with `pipx install witness` (or `pip install -e .`).",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_bundle(args: argparse.Namespace) -> int:
    attestations = None
    if args.attest_repo or args.attest_digest:
        if not (args.attest_repo and args.attest_digest):
            print("error: --attest-repo and --attest-digest must be given together", file=sys.stderr)
            return 2
        attestations = [{"repo": args.attest_repo, "digest": args.attest_digest, "artifact": args.attest_artifact}]
    try:
        doc = bundle_mod.assemble(
            root=args.root or pathlib.Path.cwd(),
            base=args.base,
            head=args.head,
            adapter=args.adapter,
            pr_url=args.pr_url,
            attestations=attestations,
        )
    except bundle_mod.BundleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    root = args.root or pathlib.Path.cwd()
    stale = bundle_mod.stale_raw_files(root, doc["anchors"]["base_commit"])
    for path in stale:
        print(f"note: {path} predates base and was excluded (RUN.md section 7)", file=sys.stderr)

    if args.stdout:
        print(json.dumps(doc, indent=2, sort_keys=True))
        return 0
    print(bundle_mod.write(doc, root, args.out))
    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    try:
        bundle_mod.reconcile(args.file, args.merge_commit, root=args.root)
    except bundle_mod.BundleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    # reconcile() deliberately does not commit (RUN.md's own CI recipe batches several
    # bundles into one commit itself) - but staying silent about that left the file
    # sitting modified-on-disk-and-forgotten as the sharp edge RUN.md section 7
    # documents. Say it, every time: a stale reminder on a no-op re-run costs a line of
    # stderr; a forgotten merge_commit costs the anchor that survives a squash.
    print(f"note: {args.file} was modified; commit it, or the merge_commit anchor is lost at the next squash (RUN.md section 7)", file=sys.stderr)
    print(args.file)
    return 0


def cmd_view(args: argparse.Namespace) -> int:
    # Refused rather than rendered: a hollow page headed "Evidence bundle" is worse than
    # no page. See view.NotABundleError.
    try:
        print(view.render_file(args.file, args.out))
    except view.NotABundleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def _print_verify_report(report: dict) -> None:
    print(f"mode: {report['mode']}")

    schema = report["schema"]
    print(f"  schema        {'ok' if schema['ok'] else 'FAIL'}")
    for err in schema["errors"][:10]:
        print(f"                  {err['path']}: {err['message']}")

    for key, loc in report["locators"].items():
        if loc is None:
            continue
        print(f"  locator {key:13s} {'reachable' if loc['reachable'] else 'DEAD (expected after a squash/rebase + delete)'}  {loc['sha']}")

    content = report["content"]
    print(f"  content       {content['matched']}/{content['total']} file claims re-verified at an anchor")
    if content.get("recovered"):
        print(
            f"                  {content['recovered']} recovered from history: the content existed after the"
            " claimed base, but no live anchor ties it to this change (run `witness reconcile`)"
        )
    for row in content["results"]:
        if row["outcome"] not in ("match", "recovered"):
            print(f"                  {row['outcome'].upper():8s} {row['path']} (checked at {row['checked_at']})")

    floor = report["tier_floor"]
    print(f"  tier_floor    declared={floor['declared']} computed={floor['computed']} {'ok' if floor['ok'] else 'FAIL'}")
    for note in floor["notes"]:
        print(f"                  {note}")

    unavailable = report["unavailable"]
    print(f"  unavailable   {'ok' if unavailable['ok'] else 'FAIL'}")
    for path in unavailable["missing"]:
        print(f"                  missing reason for {path}")

    chain = report["chain"]
    if chain["applicable"]:
        print(f"  chain (tier A) {'ok' if chain['ok'] else 'FAIL'}")
    else:
        print("  chain (tier A) not applicable")

    for claim in report["tier_b_claims"]:
        label = f"{claim['host']}:{claim['channel']}" if claim["kind"] == "source" else f"gate:{claim['gate']}"
        print(f"  tier B claim  {label:30s} {claim['outcome']}")

    if report.get("online") is not None:
        for row in report["online"]:
            src = row["source"]
            print(f"  online        {src['host']}:{src['channel']} -> {row.get('outcome', row.get('skipped'))}")

    print()
    print("PASS" if report["ok"] else "FAIL")


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        report = verify_mod.verify_file(
            args.file, root=args.root or pathlib.Path.cwd(), online=args.online
        )
    except verify_mod.VerifyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        _print_verify_report(report)
    return 0 if report["ok"] else 1


def cmd_capture(args: argparse.Namespace) -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - a malformed payload must not break the agent
        return 0
    raw.append(event, root=args.root)
    return 0


def cmd_normalize(args: argparse.Namespace) -> int:
    adapter = load(args.adapter)
    captures = raw.read(args.file)
    result = adapter.normalize_session(captures)
    json.dump(result, sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")
    if result["gaps"]:
        print(
            f"note: {len(result['gaps'])} tool call(s) have unknown outcomes; recorded, not dropped",
            file=sys.stderr,
        )
    return 0


def cmd_manifest(args: argparse.Namespace) -> int:
    adapter = load(args.adapter)
    json.dump(adapter.MANIFEST, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="witness", description="Evidence layer for AI-authored code changes")
    parser.add_argument("--version", action="version", version=f"witness {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="install the capture hook into this repo")
    p_init.add_argument("--root", default=None, help="repo root; defaults to cwd")
    p_init.add_argument(
        "--local",
        action="store_true",
        help="write .claude/settings.local.json instead of the committed settings.json",
    )
    p_init.add_argument("--uninstall", action="store_true", help="remove only witness's hooks")
    p_init.set_defaults(func=cmd_init)

    p_capture = sub.add_parser("capture", help="append one hook payload from stdin (hot path)")
    p_capture.add_argument("--root", default=None, help="repo root; defaults to cwd")
    p_capture.set_defaults(func=cmd_capture)

    p_norm = sub.add_parser("normalize", help="normalise a raw capture file to observations")
    p_norm.add_argument("file", type=pathlib.Path)
    p_norm.add_argument("--adapter", default="claudecode")
    p_norm.set_defaults(func=cmd_normalize)

    p_bundle = sub.add_parser("bundle", help="assemble observations and a git anchor into an evidence bundle")
    p_bundle.add_argument("--root", type=pathlib.Path, default=None, help="repo root; defaults to cwd")
    p_bundle.add_argument("--base", default=None, help="base revision; inferred from the default branch when omitted")
    p_bundle.add_argument("--head", default="HEAD", help="head revision (default: HEAD)")
    p_bundle.add_argument("--adapter", default="claudecode")
    p_bundle.add_argument("--pr-url", dest="pr_url", default=None)
    p_bundle.add_argument("--out", type=pathlib.Path, default=None, help="output path; defaults to .witness/evidence/<id>.evidence.json")
    p_bundle.add_argument("--stdout", action="store_true", help="print the bundle instead of writing it")
    p_bundle.add_argument("--attest-repo", dest="attest_repo", default=None, help="owner/repo to check a build-provenance attestation for (W4)")
    p_bundle.add_argument("--attest-digest", dest="attest_digest", default=None, help="artifact digest (sha256:... or bare hex) to check")
    p_bundle.add_argument("--attest-artifact", dest="attest_artifact", default=None, help="local artifact path or oci:// ref to additionally run `gh attestation verify` against")
    p_bundle.set_defaults(func=cmd_bundle)

    p_rec = sub.add_parser("reconcile", help="record the merge commit on an existing bundle, after the change lands")
    p_rec.add_argument("file", type=pathlib.Path)
    p_rec.add_argument("--merge-commit", dest="merge_commit", required=True)
    p_rec.add_argument("--root", type=pathlib.Path, default=None, help="repo root, to resolve the revision")
    p_rec.set_defaults(func=cmd_reconcile)

    p_view = sub.add_parser("view", help="render a bundle as one self-contained HTML file")
    p_view.add_argument("file", type=pathlib.Path)
    p_view.add_argument("--out", type=pathlib.Path, default=None, help="output path; defaults to <bundle>.html")
    p_view.set_defaults(func=cmd_view)

    p_verify = sub.add_parser("verify", help="re-derive a bundle's claims; network disabled unless --online")
    p_verify.add_argument("file", type=pathlib.Path)
    p_verify.add_argument("--root", type=pathlib.Path, default=None, help="repo root; defaults to cwd")
    p_verify.add_argument("--online", action="store_true", help="additionally re-fetch tier B claims")
    p_verify.add_argument("--json", action="store_true", help="print the full report as JSON")
    p_verify.set_defaults(func=cmd_verify)

    p_man = sub.add_parser("manifest", help="print an adapter's manifest")
    p_man.add_argument("--adapter", default="claudecode")
    p_man.set_defaults(func=cmd_manifest)

    return parser


def main(argv: "list[str] | None" = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
