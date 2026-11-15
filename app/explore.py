"""The "Explore the data" tab: where states pay more or less than similar loans at the same lender, and how
the typical APR moved month by month at each lender. Both read app/model/extras.json (src/build_extras.py).
"""
from __future__ import annotations

import csv
import io
import urllib.parse

import charts
import markupcheck_model
import scoring
import sections
from fmt import _esc

TIER_LABELS = {"deep subprime": "Deep subprime (250–500)", "subprime": "Subprime (501–600)",
               "near-prime": "Near-prime (601–660)", "prime": "Prime (661–780)", "super-prime": "Super-prime (781–900)"}


def _signed(x: float) -> str:
    return f"{'+' if x > 0 else '−' if x < 0 else ''}{abs(x):.2f}"  # a true minus sign, not a hyphen


def _extras():
    loaded = markupcheck_model._load()
    return loaded.get("extras") if loaded else None


def states_html() -> str:
    extras = _extras()
    if not extras or "states" not in extras:
        return "<div class='mc-result'><p class='mc-note'>The state data isn't built yet (run src/build_extras.py).</p></div>"
    st = extras["states"]
    by = st["by_state"]
    svg = sections.both(charts.tile_map_svg, {k: {"gap": v["gap"], "holds": v["holds"]} for k, v in by.items()},
                        "map", "Price gap by state, same lender")
    holding = sorted(((k, v) for k, v in by.items() if v["holds"]), key=lambda kv: kv[1]["gap"])
    rows = "".join(
        f"<tr><th scope='row'>{_esc(k)}</th><td>{_signed(v['gap'])}</td>"
        f"<td>{_signed(v['ci_low'])} to {_signed(v['ci_high'])}</td><td>{v['loans']:,}</td></tr>"
        for k, v in holding[:5] + holding[-5:])
    return (
        "<div class='mc-result'><section class='mc-section mc-first'><h2 class='mc-form-title'>Do some states pay more?</h2>"
        f"<p>Each state's average APR compared with similar loans at the <strong>same lender</strong>, in points. "
        f"Positive means borrowers there paid more. {st['holds']} of {st['tested']} states with enough loans still "
        "show a gap after a correction for testing many states at once (solid outline); the rest could be chance "
        "(dashed outline).</p>"
        f"<figure class='mc-figure'>{svg}</figure>"
        "<h3>The five lowest and five highest gaps that hold up</h3>"
        "<table class='mc-table'><thead><tr><th scope='col'>State</th><th scope='col'>Gap (points)</th>"
        "<th scope='col'>95% interval</th><th scope='col'>Loans</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        "<p class='mc-note'>The data can't say why a state differs: state law, risk the data doesn't show, or "
        "dealer practice. It has no race, sex or age, so it can't test those groups.</p>"
        + _download(st, extras) + "</section></div>"
    )


def _download(st: dict, extras: dict) -> str:
    """Every tested state as a CSV built into the link (no file is kept on the server), plus how to cite it."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["state_code", "state", "gap_points_same_lender", "ci95_low", "ci95_high", "loans",
                "holds_after_holm_correction"])
    for code, v in sorted(st["by_state"].items()):
        w.writerow([code, charts.STATE_NAMES.get(code, code), v["gap"], v["ci_low"], v["ci_high"], v["loans"],
                    "yes" if v["holds"] else "no"])
    href = "data:text/csv;charset=utf-8," + urllib.parse.quote(buf.getvalue())
    loans = f"{int(extras['n_loans']):,} " if extras.get("n_loans") else ""
    deals, lenders = extras.get("n_deals"), extras.get("n_lenders")
    source = (f"{deals} SEC Regulation AB II bond deals from {lenders} lenders" if deals and lenders
              else "SEC Regulation AB II bond deals")
    return (
        f"<p><a class='mc-btn' download='markupcheck_state_gaps.csv' href=\"{href}\">Download all {st['tested']} "
        "states (CSV)</a></p>"
        f"<p class='mc-note'><strong>How to cite:</strong> MarkupCheck, a student project (2026). State price gaps at "
        f"the same lender, from {loans}car loans in {source}, "
        "originated January 2023 to January 2026. Keep the line above with any number you quote.</p>"
    )


def tracker_html(tier: str, kind: str) -> str:
    extras = _extras()
    if not extras or "tracker" not in extras:
        return "<div class='mc-result'><p class='mc-note'>The tracker data isn't built yet (run src/build_extras.py).</p></div>"
    tr = extras["tracker"]
    used = 1 if kind == "used" else 0
    series_by_lender = tr["series"].get(f"{tier}|{used}", {})
    series = [(scoring.LENDERS[k]["name"], vals) for k, vals in sorted(series_by_lender.items())
              if any(v is not None for v in vals)]
    label = f"{TIER_LABELS.get(tier, tier)}, {'used' if used else 'new'} cars"
    if not series:
        return (f"<div class='mc-result'><section class='mc-section mc-first'><h2 class='mc-form-title'>Typical APR over time</h2>"
                f"<p>None of the lenders made at least {tr['min_loans']} loans a month for {_esc(label)}. "
                "Try another credit tier.</p></section></div>")
    svg = sections.both(charts.tracker_svg, tr["months"], series, "trk", y_label="Median APR")
    return (
        "<div class='mc-result'><section class='mc-section mc-first'><h2 class='mc-form-title'>Typical APR over time</h2>"
        f"<p>The median APR each month for {_esc(label)}, by lender, from the loans in our data "
        f"({_esc(tr['months'][0])} to {_esc(tr['months'][-1])}). Months with fewer than {tr['min_loans']} loans are left out.</p>"
        f"<figure class='mc-figure'>{svg}</figure>"
        "<p class='mc-note'>These are raw medians, not adjusted for the mix of loans each month, so a jump can mean "
        "the lender made different kinds of loans that month, not only that prices changed.</p></section></div>"
    )
