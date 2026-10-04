"""The viewer.

These pin properties that are cheap to break and expensive to notice. A viewer is the
last place a bundle passes through before a human believes it, and every failure mode
here is the same shape: the page says something the bundle did not.
"""

from __future__ import annotations

import json
import pathlib

from witness import view

EXAMPLE = pathlib.Path(__file__).resolve().parents[1] / "examples" / "mixed-tier-bundle.json"


def bundle() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def rendered() -> str:
    return view.render(bundle())


# ---- it must not invent claims ---------------------------------------------


def test_files_section_draws_no_per_row_tier_pill() -> None:
    """Regression. An earlier revision stamped TIER B on every file row.

    `files[]` has no tier field in the schema, so a per-row pill is a claim the bundle
    never made - the exact failure this format exists to prevent, committed in the one
    place where it merely looks tidy.
    """
    html = rendered()
    files_section = html.split("<h2>Files</h2>")[1].split("</div></div>")[0]
    table = files_section.split("<tbody>")[1].split("</tbody>")[0]

    assert "pill" not in table, "no tier pill belongs inside the files table body"
    # The tier is stated once, at section level, attributed to the viewer's reasoning.
    assert "tier B by construction, not by assertion" in files_section


def test_model_turns_draw_no_per_row_tier_pill() -> None:
    html = rendered()
    section = html.split("<h2>Model turns</h2>")[1]
    table = section.split("<tbody>")[1].split("</tbody>")[0]

    assert "pill" not in table


def test_token_counts_are_shown_as_parts_never_as_an_invented_total() -> None:
    """input + output is a number the viewer would have made up, and cache reads price
    differently. Showing one figure reads as a measurement while hiding the parts."""
    html = rendered()

    assert "18,422 / 1,136" in html
    assert "15,200" in html
    assert "19,558" not in html, "input+output must not be summed into a single figure"


def test_no_aggregate_grade_is_rendered() -> None:
    """S2 / SPEC 4.3. tier_floor is a floor, rendered as a sentence."""
    html = rendered()

    assert "Nothing in this bundle is better attested than tier C" in html
    assert "floor, not a grade" in html


# ---- absence ---------------------------------------------------------------


def test_absent_values_render_as_a_dash_and_a_reason_never_zero() -> None:
    html = rendered()

    assert "&mdash;" in html or "—" in html
    assert "not merged yet" in html  # anchors.merge_commit is null
    assert "not independently retrievable" in html  # a tier C source has no locator


def test_the_unavailable_map_is_rendered_not_dropped() -> None:
    html = rendered()

    for pointer in bundle()["unavailable"]:
        assert pointer in html, f"{pointer} was silently dropped"


def test_absent_helper_never_emits_a_zero() -> None:
    assert "0" not in view.absent(None)
    assert "out_of_retention" in view.absent("out_of_retention")


# ---- self-contained --------------------------------------------------------


def test_the_page_fetches_nothing() -> None:
    """The durability argument. An auditor opens this on a machine with no network,
    no fonts installed, and no willingness to install anything."""
    html = rendered()

    assert "<script" not in html.lower()
    assert "http://" not in html.replace("http://www.w3.org", "")
    assert "fonts.googleapis" not in html
    assert "@import" not in html
    assert "cdn" not in html.lower()


def test_remote_urls_from_the_bundle_are_text_not_links() -> None:
    """A bundle is untrusted input; it is written by whatever produced the change.
    Nothing in it becomes a clickable target in the viewer."""
    html = rendered()

    assert "<a " not in html
    assert "github.com/acme/payments-service/pull/812" in html  # shown, not linked


def test_bundle_content_is_escaped() -> None:
    b = bundle()
    b["repo"]["slug"] = '<img src=x onerror="alert(1)">'

    html = view.render(b)

    assert "<img" not in html
    assert "&lt;img" in html


# ---- verification context --------------------------------------------------


def test_unverified_view_says_so_rather_than_implying_a_pass() -> None:
    html = rendered()

    assert "Not verified in this view" in html
    assert "does not re-check any claim" in html


def test_verified_view_reports_mode_and_time() -> None:
    html = view.render(bundle(), verification={"at": "2026-09-18T12:00:00Z", "offline": True})

    assert "Verified offline at 2026-09-18T12:00:00Z" in html
    assert "never as passing" in html


# ---- file output -----------------------------------------------------------


def test_render_file_defaults_to_a_sibling_html_file(tmp_path: pathlib.Path) -> None:
    src = tmp_path / "b.evidence.json"
    src.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")

    out = view.render_file(src)

    assert out == tmp_path / "b.evidence.html"
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


# ---- it must refuse anything that is not a bundle ---------------------------

SCHEMA = pathlib.Path(__file__).resolve().parents[1] / "schemas" / "evidence-bundle.schema.json"
NORMALIZED = {
    "observations": [],
    "gates": [],
    "gaps": [],
    "gates_unavailable": {},
    "malformed_lines": 0,
}


def test_required_bundle_fields_match_the_schema() -> None:
    """Drift guard. view.REQUIRED_BUNDLE_FIELDS mirrors the schema's `required` list so
    the viewer can refuse a non-bundle without shipping a JSON Schema registry. The
    mirror is only safe while it is identical, and a field added to the schema would
    otherwise silently stop being checked here."""
    required = json.loads(SCHEMA.read_text(encoding="utf-8"))["required"]
    assert sorted(view.REQUIRED_BUNDLE_FIELDS) == sorted(required)


def test_normalize_output_is_refused_not_rendered() -> None:
    """Regression, found 2026-09-20. `witness view` was handed a `normalize` output and
    produced a page headed "Evidence bundle" with every anchor blank - "Base commit -
    root commit", "Assembled by -". Indistinguishable from a real bundle whose change
    had no anchors, which is the confusion between asserted and absent that this whole
    format exists to prevent."""
    try:
        view.render(dict(NORMALIZED))
    except view.NotABundleError as exc:
        assert "not an evidence bundle" in str(exc)
        assert "schema_version" in str(exc)
        return
    raise AssertionError("render() accepted a normalize output")


def test_refusal_names_normalize_output_specifically() -> None:
    """The likeliest wrong input is the output of the previous pipeline step, so the
    error says so and names the command that would produce a real bundle."""
    try:
        view.render(dict(NORMALIZED))
    except view.NotABundleError as exc:
        assert "witness bundle" in str(exc)
        return
    raise AssertionError("render() accepted a normalize output")


def test_partial_bundle_is_refused_and_names_every_missing_field() -> None:
    """A truncated or half-assembled bundle is refused the same way, and the message
    lists all of what is missing rather than the first one, so one run is enough."""
    partial = {k: None for k in view.REQUIRED_BUNDLE_FIELDS if k not in ("anchors", "files")}
    try:
        view.render(partial)
    except view.NotABundleError as exc:
        assert "anchors" in str(exc) and "files" in str(exc)
        return
    raise AssertionError("render() accepted a partial bundle")


def test_non_object_input_is_refused() -> None:
    for junk in ([], "a string", 7, None):
        try:
            view.render(junk)  # type: ignore[arg-type]
        except view.NotABundleError:
            continue
        raise AssertionError(f"render() accepted {junk!r}")


def test_the_real_example_still_renders() -> None:
    """The guard must not reject the artifact the auditor calls depend on."""
    assert "<h1>Evidence bundle</h1>" in rendered()
