#!/usr/bin/env python3
"""Validate the schemas against JSON Schema 2020-12, then validate every example
under examples/ against the schema it names.

Run: python3 scripts/validate.py
"""
from __future__ import annotations

import json
import pathlib
import sys

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"
EXAMPLE_DIR = ROOT / "examples"


def build_registry() -> tuple[Registry, dict[str, dict]]:
    """Register every schema under its path relative to schemas/, and additionally
    under its declared $id when that $id is absolute.

    Vendored upstream files declare absolute $ids and reference each other by them,
    so both keys are needed for offline resolution.
    """
    registry = Registry()
    contents: dict[str, dict] = {}
    for path in sorted(SCHEMA_DIR.rglob("*.schema.json")):
        rel = path.relative_to(SCHEMA_DIR).as_posix()
        doc = json.loads(path.read_text())
        contents[rel] = doc
        resource = Resource.from_contents(doc, default_specification=DRAFT202012)
        registry = registry.with_resource(rel, resource)
        declared = doc.get("$id", "")
        if declared.startswith("http"):
            registry = registry.with_resource(declared, resource)
    return registry, contents


def main() -> int:
    registry, contents = build_registry()
    failures = 0

    for rel, doc in contents.items():
        try:
            Draft202012Validator.check_schema(doc)
            print(f"  ok   schema   {rel}")
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  FAIL schema   {rel}: {exc}")
            failures += 1

    for path in sorted(EXAMPLE_DIR.glob("*.json")):
        doc = json.loads(path.read_text())
        target = doc.get("$schema_under_test")
        if not target:
            print(f"  FAIL example  {path.name}: missing $schema_under_test")
            failures += 1
            continue
        subject = {k: v for k, v in doc.items() if k != "$schema_under_test"}
        validator = Draft202012Validator(
            contents[target],
            registry=registry,
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )
        errors = sorted(validator.iter_errors(subject), key=lambda e: list(e.path))
        if errors:
            failures += 1
            print(f"  FAIL example  {path.name} against {target}")
            for err in errors[:10]:
                loc = "/".join(str(p) for p in err.path) or "(root)"
                print(f"         {loc}: {err.message}")
        else:
            print(f"  ok   example  {path.name} against {target}")

    # Negative cases. A schema that accepts everything proves nothing, so each of
    # these MUST be rejected; a pass here is the failure.
    for path in sorted((EXAMPLE_DIR / "invalid").glob("*.json")):
        doc = json.loads(path.read_text())
        target = doc.get("$schema_under_test")
        why = doc.get("$must_fail_because", "")
        subject = {k: v for k, v in doc.items() if not k.startswith("$")}
        validator = Draft202012Validator(
            contents[target],
            registry=registry,
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )
        if any(validator.iter_errors(subject)):
            print(f"  ok   rejected {path.name}")
        else:
            failures += 1
            print(f"  FAIL accepted {path.name} but should not have: {why}")

    print()
    print("FAILED" if failures else "all green")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
