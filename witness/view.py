"""Bundle viewer. One bundle in, one self-contained HTML file out.

WHY HTML AND NOT SOMETHING NICER. The reader is an auditor in month fourteen, on a
machine that has never heard of this tool, who will not install anything. A local server
needs a running process at exactly the moment nobody is running one. An SPA adds a
toolchain to a one-dependency package. Terminal output cannot be emailed, and
`validation-plan.md` says the artifact you want is an email.

So: no server, no framework, no script, no web font, no network fetch of any kind. The
file renders in fourteen years for the same reason the bundle verifies in fourteen months
- it depends on nothing.

THE THREE RULES THIS FILE EXISTS TO NOT BREAK
---------------------------------------------
1. No aggregate grade. `SPEC.md` 4.3 and S2 forbid collapsing mixed tiers to one number,
   and a viewer is exactly where one gets added because it looks tidy. `tier_floor` is a
   floor - "nothing here is better attested than X" - and is rendered as that sentence,
   never as a score.
2. A decayed claim is not a failure. `out_of_retention` and `unverified-offline` are the
   system working correctly. Nothing here renders them in the failure colour.
3. No claim without its tier - and no tier the bundle does not carry. `files[]` and
   `model_turns[]` have no tier field in the schema, so no per-row pill is drawn for
   them; their tier is stated once at section level and attributed to the viewer's own
   reasoning. An earlier revision stamped TIER B on every file row, which invented a
   claim the bundle never made. That is the failure this whole format exists to prevent,
   and it is easiest to commit here, where it merely looks tidy.

Absence is rendered as an em dash plus the reason, never as zero and never omitted. That
is the same discipline as the schema's `unavailable` map, carried into the presentation
layer, because a viewer that silently drops a null is a viewer that lies.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

# The evidence-bundle schema's own `required` list, mirrored here so the viewer can
# refuse a non-bundle without carrying the schema files and a JSON Schema registry into
# every install. `test_required_bundle_fields_match_the_schema` fails if the two drift,
# which is what makes the mirror safe.
REQUIRED_BUNDLE_FIELDS = (
    "schema_version",
    "id",
    "generated_at",
    "generated_by",
    "tier_floor",
    "commit_sha",
    "anchors",
    "repo",
    "sources",
    "observations",
    "files",
    "gates",
    "model_turns",
    "unavailable",
)


class NotABundleError(ValueError):
    """The input is not an evidence bundle, so it must not be rendered as one.

    WHY THIS IS AN ERROR AND NOT A DEGRADED RENDER. Every field this viewer reads goes
    through `dict.get`, which is correct for a bundle that legitimately carries a null -
    absence is rendered as an em dash plus its reason, per the module docstring. Applied
    to a document that is not a bundle at all, the same tolerance produces a page headed
    "Evidence bundle" whose anchors read "Base commit - root commit" and "Assembled by
    -", because nothing was there to read.

    That page is indistinguishable, to a reader, from a real bundle describing a change
    with no anchors. It is the exact confusion between *asserted* and *absent* that this
    format exists to prevent, arriving through the one surface a human actually looks at.
    A `normalize` output triggers it: it carries `observations` and `gates` and nothing
    else the bundle requires.

    Refusing is the only safe behaviour. A viewer that renders anything will eventually
    render something untrue.
    """


def assert_is_bundle(doc: object, source: "Path | str | None" = None) -> None:
    """Raise `NotABundleError` unless `doc` has every field the bundle schema requires.

    Deliberately a structural check, not full schema validation: `scripts/validate.sh`
    validates against the schemas, and `verify` will re-derive claims. This guard exists
    only to stop the viewer rendering a document that was never a bundle, and it is
    sized for that.
    """
    where = f" in {source}" if source else ""
    if not isinstance(doc, dict):
        raise NotABundleError(
            f"expected an evidence bundle{where}, found {type(doc).__name__}"
        )
    missing = [f for f in REQUIRED_BUNDLE_FIELDS if f not in doc]
    if not missing:
        return
    detail = ", ".join(missing)
    hint = ""
    if "observations" in doc and "schema_version" not in doc:
        hint = (
            "\nThis looks like `witness normalize` output. Normalised observations are an "
            "input to a bundle, not a bundle: they carry no commit, no anchors and no "
            "tier floor. Assembling them into one is `witness bundle`."
        )
    raise NotABundleError(
        f"not an evidence bundle{where}: missing required field(s): {detail}.{hint}"
    )


TIER_MEANING = {
    "A": "attested by our own runner, hash-chained and anchored in git",
    "B": "attested by a third party the audited party does not control",
    "C": "self-reported by the agent; git-anchoring makes it non-repudiable, not verified",
}

TIER_CATCHES = {
    "A": "post-hoc edits to the journal",
    "B": "local fabrication — but perishable, it decays when the host's retention window closes",
    "C": "nothing on its own",
}

# Light only, deliberately. This gets printed, emailed and attached to audit workpapers.
# Values carried from the mysentry UX reference, which was contrast-checked: 18 of 19
# pairs pass WCAG AA. --fg-faint is the corrected value (#64748a failed at 4.32 on canvas).
CSS = """
:root{
  --canvas:#f1f4f8; --card:#fcfdff; --border:#dce3ec; --border-strong:#b6c3d3;
  --fg:#17273d; --fg-muted:#526278; --fg-faint:#5c6a80;
  --tier-a:#237049; --tier-b:#2455b8; --tier-c:#8b620b;
  --neutral:#536276; --redacted-bg:#ede6fa; --redacted-fg:#652aa5;
  --row-alt:#f7fafd;
  --font-ui:"IBM Plex Sans","Segoe UI",system-ui,-apple-system,sans-serif;
  --font-mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
  --radius:5px;
}
*{box-sizing:border-box}
body{margin:0;background:var(--canvas);color:var(--fg);font-family:var(--font-ui);
     font-size:13px;line-height:1.5;-webkit-font-smoothing:antialiased}
.wrap{max-width:1140px;margin:0 auto;padding:28px 22px 64px}
h1{font-size:23px;margin:0 0 2px;letter-spacing:-.01em}
h2{font-size:15px;margin:0;font-weight:600}
.sub{color:var(--fg-muted);margin:0 0 22px}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
      margin-bottom:18px;overflow:hidden}
.card-h{padding:12px 16px;border-bottom:1px solid var(--border);display:flex;
        align-items:baseline;gap:10px;flex-wrap:wrap}
.card-h .note{color:var(--fg-faint);font-size:12px;margin-left:auto}
.body{padding:14px 16px}
/* Severity treatment is a left border plus a word pill, never a row background. A row
   wash makes every other field in the row unreadable and turns the table into an
   uncalibrated heat map. */
.pill{display:inline-flex;align-items:center;gap:5px;padding:1px 7px;border-radius:3px;
      font-size:10px;font-weight:600;letter-spacing:.03em;border:1px solid currentColor;
      background:var(--card);white-space:nowrap}
.t-A{color:var(--tier-a)} .t-B{color:var(--tier-b)} .t-C{color:var(--tier-c)}
.t-none{color:var(--neutral)}
table{border-collapse:collapse;width:100%;font-size:13px}
th{text-align:left;font-size:11px;letter-spacing:.04em;text-transform:uppercase;
   color:var(--fg-muted);font-weight:600;padding:8px 12px;border-bottom:1px solid var(--border);
   white-space:nowrap}
td{padding:8px 12px;border-bottom:1px solid var(--border);vertical-align:top}
tr:last-child td{border-bottom:none}
tbody tr:nth-child(even){background:var(--row-alt)}
td.sev{border-left:3px solid transparent}
.num{text-align:right;font-family:var(--font-mono);font-variant-numeric:tabular-nums;
     font-size:12px;white-space:nowrap}
.mono{font-family:var(--font-mono);font-size:12px;word-break:break-all}
.scroll{overflow-x:auto}
.none{color:var(--fg-faint)}
.reason{color:var(--fg-faint);font-size:12px}
.kv{display:grid;grid-template-columns:150px 1fr;gap:6px 16px;font-size:13px}
.kv dt{color:var(--fg-muted)}
.kv dd{margin:0;word-break:break-all}
.banner{border:1px solid var(--border-strong);border-left:3px solid var(--neutral);
        background:var(--card);border-radius:var(--radius);padding:12px 16px;margin-bottom:18px}
.banner b{display:block;margin-bottom:2px}
.floor{border-left-color:var(--tier-c)}
.legend{display:grid;gap:8px}
.legend div{display:flex;gap:10px;align-items:baseline}
.legend span.txt{color:var(--fg-muted);font-size:12px}
.section-tier{margin:0 0 8px;display:flex;gap:9px;align-items:baseline;font-size:12px;color:var(--fg-muted)}
.section-tier b{color:var(--fg);font-weight:600}
.redacted{background:var(--redacted-bg);color:var(--redacted-fg);padding:0 4px;
          border-radius:3px;font-family:var(--font-mono);font-size:12px}
details{margin-top:10px}
summary{cursor:pointer;color:var(--tier-b);font-size:12px;font-weight:600}
details pre{background:var(--canvas);border:1px solid var(--border);border-radius:var(--radius);
            padding:12px;overflow-x:auto;font-family:var(--font-mono);font-size:11.5px;margin:8px 0 0}
footer{color:var(--fg-faint);font-size:12px;border-top:1px solid var(--border);
       padding-top:14px;margin-top:26px}
footer p{margin:0 0 5px}
@media print{body{background:#fff}.card{break-inside:avoid}}
"""


def e(value: object) -> str:
    return html.escape("" if value is None else str(value))


def tier_pill(tier: "str | None") -> str:
    if not tier:
        return '<span class="pill t-none">NO TIER</span>'
    return f'<span class="pill t-{e(tier)}">TIER {e(tier)}</span>'


def absent(reason: "str | None") -> str:
    """An em dash and the reason. Never zero, never blank, never omitted."""
    if reason:
        return f'<span class="none">— <span class="reason">{e(reason)}</span></span>'
    return '<span class="none">—</span>'


def _sev_border(tier: "str | None") -> str:
    colour = {"A": "var(--tier-a)", "B": "var(--tier-b)", "C": "var(--tier-c)"}.get(tier or "", "transparent")
    return f' style="border-left-color:{colour}"'


def _reason_for(bundle: dict, pointer: str) -> "str | None":
    return (bundle.get("unavailable") or {}).get(pointer)


def render(bundle: dict, verification: "dict | None" = None) -> str:
    assert_is_bundle(bundle)
    repo = bundle.get("repo") or {}
    floor = bundle.get("tier_floor")
    parts: list[str] = []

    parts.append(f"""<div class="wrap">
<h1>Evidence bundle</h1>
<p class="sub">{e(repo.get('slug'))} &middot; {e(repo.get('branch'))} &middot; bundle <span class="mono">{e(bundle.get('id'))}</span></p>""")

    parts.append(_verification_banner(verification))
    parts.append(_floor_banner(floor))
    parts.append(_change_card(bundle, repo))
    parts.append(_files_card(bundle))
    parts.append(_gates_card(bundle))
    parts.append(_observations_card(bundle))
    parts.append(_turns_card(bundle))
    parts.append(_sources_card(bundle))
    parts.append(_legend_card())
    parts.append(_footer(bundle))
    parts.append("</div>")

    body = "\n".join(parts)
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>Evidence bundle {e(bundle.get('id'))}</title>"
        f"<style>{CSS}</style></head><body>{body}</body></html>\n"
    )


def _verification_banner(verification: "dict | None") -> str:
    """States what was checked and when. Never claims more than it did."""
    if not verification:
        return """<div class="banner">
<b>Not verified in this view</b>
This page renders what the bundle asserts. It does not re-check any claim.
Run <span class="mono">witness verify</span> to re-derive them, which is a separate operation with its own result.
</div>"""
    at = e(verification.get("at"))
    mode = "offline" if verification.get("offline") else "online"
    return f"""<div class="banner">
<b>Verified {e(mode)} at {at}</b>
Tier B claims re-fetched from their hosts where reachable. Claims that could not be
re-checked are reported as unverified, never as passing.
</div>"""


def _floor_banner(floor: "str | None") -> str:
    """A floor, not a score. The distinction is the product."""
    if not floor:
        return ""
    return f"""<div class="banner floor">
<b>Tier floor: {e(floor)} &nbsp;{tier_pill(floor)}</b>
Nothing in this bundle is better attested than tier {e(floor)}. This is a floor, not a grade &mdash;
each claim below carries its own tier, and they are deliberately not averaged.
</div>"""


def _change_card(bundle: dict, repo: dict) -> str:
    anchors = bundle.get("anchors") or {}
    rows = [
        ("Commit", f'<span class="mono">{e(bundle.get("commit_sha"))}</span>'),
        ("Base commit", f'<span class="mono">{e(anchors.get("base_commit"))}</span>' if anchors.get("base_commit") else absent("root commit")),
        ("Base tree", f'<span class="mono">{e(anchors.get("base_tree"))}</span>' if anchors.get("base_tree") else absent(None)),
        ("Patch id", (f'<span class="mono">{e(anchors.get("patch_id"))}</span> {tier_pill("C")} '
                      f'<span class="reason">correlation hint, not an identity</span>')
                     if anchors.get("patch_id") else absent("empty diff")),
        ("Merge commit", f'<span class="mono">{e(anchors.get("merge_commit"))}</span>' if anchors.get("merge_commit")
                         else absent("not merged yet")),
        ("Remote", f'<span class="mono">{e(repo.get("remote"))}</span>' if repo.get("remote") else absent("local-only repository")),
        ("Pull request", f'<span class="mono">{e(repo.get("pr_url"))}</span>' if repo.get("pr_url") else absent("not opened")),
        ("Assembled", f'{e(bundle.get("generated_at"))} by <span class="mono">{e(bundle.get("generated_by"))}</span>'),
    ]
    items = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
    return f"""<div class="card"><div class="card-h"><h2>The change</h2>
<span class="note">anchors survive squash and rebase; the commit may not</span></div>
<div class="body"><dl class="kv">{items}</dl></div></div>"""


def _files_card(bundle: dict) -> str:
    files = bundle.get("files") or []
    if not files:
        return ""
    rows = "".join(
        f"""<tr><td><span class="mono">{e(f.get('path'))}</span></td>
<td>{e(f.get('action'))}</td>
<td><span class="mono">{e((f.get('sha256') or '')[:16])}&hellip;</span></td></tr>"""
        for f in files
    )
    # No per-row tier pill. `files[]` carries no tier in the schema, and stamping one
    # here would invent a claim the bundle does not make - the exact failure this format
    # exists to prevent. The tier belongs to the section and is stated as the viewer's
    # own reasoning, attributed, so it cannot be mistaken for bundle data.
    return f"""<div class="card"><div class="card-h"><h2>Files</h2>
<span class="note">sha256 of the bytes in the tree, not the working copy</span></div>
<div class="scroll"><table><thead><tr><th>Path</th><th>Action</th><th>sha256</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<div class="body"><p class="section-tier">{tier_pill('B')} <b>These are tier B by construction, not by assertion.</b>
Anyone holding the repository can recompute them; the bundle does not have to be believed.</p>
<span class="reason">Content hashes are identical in any repository holding the same bytes, so they
survive rebase, squash, cherry-pick and re-clone. The bundle records no per-file tier and none is shown.</span></div></div>"""


def _gates_card(bundle: dict) -> str:
    gates = bundle.get("gates")
    if gates is None:
        return ""
    if not gates:
        return """<div class="card"><div class="card-h"><h2>Gates</h2></div>
<div class="body">No approval boundary was crossed. <span class="reason">An empty list is
meaningful and is not the same as a missing one: it asserts that nothing gated this change.</span></div></div>"""
    rows = "".join(
        f"""<tr><td class="sev"{_sev_border(g.get('tier'))}>{e(g.get('gate'))}</td>
<td>{e(g.get('decision'))}</td>
<td>{e(g.get('actor')) if g.get('actor') else absent('no actor recorded')}</td>
<td class="num">{e(g.get('at'))}</td>
<td>{tier_pill(g.get('tier'))}</td></tr>"""
        for g in gates
    )
    return f"""<div class="card"><div class="card-h"><h2>Gates</h2>
<span class="note">what this records, not whether it was wise</span></div>
<div class="scroll"><table><thead><tr><th>Gate</th><th>Decision</th><th>Actor</th><th>At</th><th>Tier</th></tr></thead>
<tbody>{rows}</tbody></table></div></div>"""


def _observations_card(bundle: dict) -> str:
    obs = bundle.get("observations") or []
    if not obs:
        return ""
    rows = []
    for o in obs:
        src = o.get("source") or {}
        tier = src.get("tier")
        retrievable = src.get("retrievable_from")
        where = (f'<span class="mono">{e(retrievable[:52])}&hellip;</span>' if retrievable
                 else absent("not independently retrievable"))
        rows.append(
            f"""<tr><td class="sev"{_sev_border(tier)}>{e(o.get('event'))}</td>
<td>{e(o.get('actor'))}</td>
<td>{e(o.get('phase')) if o.get('phase') else absent('phase not inferred')}</td>
<td class="num">{e(o.get('timestamp'))}</td>
<td>{tier_pill(tier)}</td>
<td>{where}</td></tr>"""
        )
    payloads = json.dumps([o.get("payload") for o in obs], indent=2)
    return f"""<div class="card"><div class="card-h"><h2>Observations</h2>
<span class="note">{len(obs)} record(s), in timestamp order</span></div>
<div class="scroll"><table><thead><tr><th>Event</th><th>Actor</th><th>Phase</th><th>At</th><th>Tier</th><th>Re-fetchable from</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<div class="body"><details><summary>Exact payloads</summary><pre>{e(payloads)}</pre></details></div></div>"""


def _turns_card(bundle: dict) -> str:
    turns = bundle.get("model_turns") or []
    if not turns:
        return """<div class="card"><div class="card-h"><h2>Model turns</h2></div>
<div class="body">""" + absent("no contributing host emitted model turn data") + "</div></div>"
    rows = []
    for t in turns:
        tokens = t.get("tokens") or {}
        # Deliberately NOT summed. input+output is a number this viewer would have
        # invented, and cache reads are priced differently - a single "tokens" figure
        # reads as a measurement while hiding which parts were actually emitted.
        in_out = (f"{tokens['input']:,} / {tokens['output']:,}"
                  if tokens.get("input") is not None and tokens.get("output") is not None else None)
        cached = tokens.get("cache_read")
        rows.append(
            f"""<tr><td class="sev"{_sev_border('C')}>{e(t.get('model_id')) if t.get('model_id') else absent('host_does_not_emit')}</td>
<td>{e(t.get('host'))}</td>
<td>{e(t.get('transport')) if t.get('transport') else absent(None)}</td>
<td class="num">{e(in_out) if in_out else absent('host_does_not_emit')}</td>
<td class="num">{e(f"{cached:,}") if cached is not None else absent('host_does_not_emit')}</td>
<td class="num">{('$' + e(t.get('cost_usd'))) if t.get('cost_usd') is not None else absent('not emitted')}</td></tr>"""
        )
    cost = bundle.get("cost") or {}
    note = f'<div class="body"><span class="reason">{e(cost.get("disclaimer"))}</span></div>' if cost.get("disclaimer") else ""
    return f"""<div class="card"><div class="card-h"><h2>Model turns</h2>
<span class="note">self-reported by the agent</span></div>
<div class="body"><p class="section-tier">{tier_pill('C')} <b>Self-reported, and nothing here corroborates it.</b>
The bundle records no per-turn tier; this is the tier of the source that supplied the section.</p></div>
<div class="scroll"><table><thead><tr><th>Model</th><th>Host</th><th>Transport</th><th class="num">in / out</th><th class="num">cached read</th><th class="num">Cost</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>{note}</div>"""


def _sources_card(bundle: dict) -> str:
    sources = bundle.get("sources") or []
    if not sources:
        return ""
    rows = "".join(
        f"""<tr><td class="sev"{_sev_border(s.get('tier'))}>{e(s.get('host'))}</td>
<td>{e(s.get('channel'))}</td>
<td><span class="mono">{e(s.get('adapter_version'))}</span></td>
<td class="num">{e(s.get('collected_at'))}</td>
<td>{tier_pill(s.get('tier'))}</td></tr>"""
        for s in sources
    )
    return f"""<div class="card"><div class="card-h"><h2>Sources</h2>
<span class="note">the provenance of the provenance</span></div>
<div class="scroll"><table><thead><tr><th>Host</th><th>Channel</th><th>Adapter</th><th>Collected</th><th>Tier</th></tr></thead>
<tbody>{rows}</tbody></table></div></div>"""


def _legend_card() -> str:
    items = "".join(
        f'<div>{tier_pill(t)}<span class="txt"><b>{e(TIER_MEANING[t])}.</b> Catches {e(TIER_CATCHES[t])}.</span></div>'
        for t in ("A", "B", "C")
    )
    return f"""<div class="card"><div class="card-h"><h2>What the tiers mean</h2>
<span class="note">assigned per claim, never per bundle</span></div>
<div class="body"><div class="legend">{items}</div></div></div>"""


def _footer(bundle: dict) -> str:
    unavailable = bundle.get("unavailable") or {}
    lines = "".join(
        f'<p><span class="mono">{e(k)}</span> — {e(v)}</p>' for k, v in sorted(unavailable.items())
    )
    return f"""<footer>
<p><b>&ldquo;—&rdquo; means no measurement, not zero.</b> A claim the host never emitted is shown as
absent with its reason, never as a zero and never omitted.</p>
<p>Tier B claims are perishable. When a host's retention window closes the claim degrades to tier C
and says so &mdash; that is the format working correctly, not a failure.</p>
<p>No aggregate grade is shown, by design. Every realistic bundle mixes tiers, and collapsing them to
one number is the dishonesty this format exists to prevent.</p>
{f'<p style="margin-top:10px"><b>Not applicable or not emitted:</b></p>{lines}' if lines else ''}
</footer>"""


def render_file(bundle_path: Path, out_path: "Path | None" = None) -> Path:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert_is_bundle(bundle, bundle_path)
    target = out_path or bundle_path.with_suffix(".html")
    target.write_text(render(bundle), encoding="utf-8")
    return target
