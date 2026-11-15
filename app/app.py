"""MarkupCheck Gradio app.

The UI depends only on `markupcheck_model.predict(offer)` and the keys fixed in CONTRACT.md,
so the stub can be replaced by the trained model without touching this file.
"""

import datetime
import html
import json
import sys
import traceback
import uuid
from pathlib import Path

import gradio as gr
import numpy as np
from starlette.middleware import Middleware
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

import finance
import explore
import i18n
import markupcheck_model
import sections
import tabs
import teacher
import web_security
from fmt import CHIP_TEXT, FLAG_TEXT, _esc, _flag_chip, _pct, _usd, percentile_text  # noqa: F401  (re-exported for tests)
from inputs import (L_ADDONS, L_APR, L_FINANCED, L_KIND, L_LENDER, L_PAYMENT, L_PRICE, L_SCORE, L_TERM,  # noqa: F401
                    L_YEAR,
                    _number, validate)

TITLE = "MarkupCheck: is your car-loan rate fair?"
DISCLAIMER = "This project is a prototype and is not financial advice."

# Jordan's example from the build plan: (score, new/used, year, price, financed, term, APR, lender).
JORDAN = (660, "used", 2019, 17500, 18500, 72, 15.9, "")
# Sam's example: the first APR the model calls "well above" for this profile (notebook section 11).
SAM = (760, "used", 2022, 24000, 25000, 60, 14.5, "")

# AdmitPath's palette (app/globals.css). ACCENT fills buttons, bars and borders; as text it is only 4.3:1 on
# the card, so blue text uses BRAND_TEXT. MUTED and ERROR_TEXT are also darker than AdmitPath's own values
# (#5A6275 and #DC2626) so that text passes WCAG AA, 4.5:1.
ACCENT = "#4A6FA5"
BRAND_TEXT = "#3A5A7E"
BRAND_DARK = "#2E4A6E"
PRIMARY_LIGHT = "#E8EFF8"
PRIMARY_BORDER = "#D5E0EE"
GROUND = "#D5DCE8"
SURFACE = "#EFF2F8"
SUNKEN = "#E3E8F1"
TEXT = "#1B2030"
SECONDARY = "#454B5E"
MUTED = "#535B6E"
ERROR = "#DC2626"
ERROR_LIGHT = "#FEE2E2"
ERROR_TEXT = "#991B1B"

# ---------------------------------------------------------------- rendering


def render_errors(errors, heading: str = "Please check these entries", ref: str | None = None) -> str:
    """`errors` are (field label or None, message) pairs; the page script marks those fields aria-invalid."""
    fields = "|".join(dict.fromkeys(field for field, _ in errors if field))
    items = "".join(f"<li>{message}</li>" for _, message in errors)
    ref_line = f'<p class="mc-ref">Reference code: <code>{_esc(ref)}</code></p>' if ref else ""
    return (
        f'<div class="mc-result"><div class="mc-error" id="mc-error" role="alert" data-invalid="{_esc(fields)}">'
        f"<h3>{heading}</h3>"
        f"<ul>{items}</ul>{ref_line}</div></div>"
    )


def render_empty() -> str:
    return (
        '<div class="mc-result"><div class="mc-empty">'
        '<div class="mc-empty-icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="24" height="24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/></svg></div>'
        "<h3>Your result will appear here</h3>"
        "<p>Enter the loan offer and press <strong>Check my rate</strong>, or try an example: "
        "<strong>Jordan</strong> (a fair rate) or <strong>Sam</strong> (a rate well above similar loans).</p>"
        "</div></div>"
    )


def _verdict_sentence(offer_apr: float, low: float, high: float, typical: float) -> str:
    """One plain sentence that answers 'is my rate fair?' before any detail."""
    rng = f"{_pct(low)}–{_pct(high)}"
    if offer_apr > high:
        gap = offer_apr - high
        gap_text = f"{gap:.1f}" if gap >= 0.1 else f"{gap:.2f}"  # never "0.0 points above"
        return (f"Your {_pct(offer_apr)} is <strong>{gap_text} points above</strong> the range "
                f"similar loans got ({rng}).")
    if offer_apr < low:
        return f"Your {_pct(offer_apr)} is <strong>below</strong> the range similar loans got ({rng})."
    side = "below" if offer_apr < typical else "above"
    return (f"Your {_pct(offer_apr)} is <strong>inside</strong> the range similar loans got ({rng}), "
            f"{side} the typical {_pct(typical)}.")


def _range_bar(low: float, high: float, typical: float, offer_apr: float) -> str:
    lo = min(low, typical, offer_apr)
    hi = max(high, typical, offer_apr)
    pad = max((hi - lo) * 0.15, 1.0)
    axis_min, axis_max = max(0.0, lo - pad), hi + pad

    def pos(x: float) -> float:
        return (x - axis_min) / (axis_max - axis_min) * 100

    left, right = pos(low), pos(high)
    marker = pos(offer_apr)
    # The label grows away from the nearer edge so it never overflows a phone-width bar.
    side = "mc-label-end" if marker > 50 else "mc-label-start"
    summary = (f"Your offer {_pct(offer_apr)}. Similar loans mostly got {_pct(low)} to {_pct(high)}; "
               f"typical {_pct(typical)}.")
    return (
        f'<div class="mc-bar" role="img" aria-label="{_esc(summary)}">'
        f'<div class="mc-marker-label {side}" style="left:{marker:.2f}%">Your offer {_pct(offer_apr)}</div>'
        '<div class="mc-track">'
        f'<div class="mc-range" style="left:{left:.2f}%;width:{right - left:.2f}%"></div>'
        f'<div class="mc-typical" style="left:{pos(typical):.2f}%"></div>'
        f'<div class="mc-marker" style="left:{marker:.2f}%"></div>'
        "</div>"
        '<div class="mc-scale">'
        f'<span class="{"mc-label-start" if left < 15 else "mc-label-end"}" style="left:{left:.2f}%">{_pct(low)}</span>'
        f'<span class="{"mc-label-end" if right > 85 else "mc-label-start"}" style="left:{right:.2f}%">{_pct(high)}</span>'
        "</div></div>"
    )


FEW_LENDER_LOANS = 5000  # under this, a lender's own typical rate rests on few loans
FEW_TEST_LOANS = 1000  # under this, a lender's test result is too small to lean on


def _lender_test_line(same_lender) -> str:
    """How the same-lender check did on this lender's own held-back loans, so a thin or untested lender reads as such."""
    t = (same_lender or {}).get("test")
    if t is None:
        return ""
    name, n = _esc(same_lender["lender"]), int(same_lender["n_loans"])
    parts = []
    if n < FEW_LENDER_LOANS:
        parts.append(f"We have only {n:,} loans from {name}, so its typical rate is less certain than for bigger "
                     "lenders.")
    if not t["loans"] and t.get("later_deals_all_promotional"):
        parts.append(f"None of the loans from {name} fell in our test months, and its later deals hold only "
                     "promotional loans, which aren't market prices, so we couldn't measure how well this check does "
                     "on its loans.")
    elif not t["loans"]:
        parts.append(f"None of the loans from {name} fell in our test months, so we couldn't measure how well this "
                     "check does on its loans alone.")
    elif t.get("later_deal"):  # its loans fell before the test months, so it was tested on a later deal (later_deals.py)
        parts.append(f"On {int(t['loans']):,} loans from a later {name} deal the model never saw, the typical rate "
                     f"here was off by {t['miss_pts']:.2f} points on average, against {t['rule_miss_pts']:.2f} for the "
                     "rule of thumb.")
    else:
        parts.append(f"On {int(t['loans']):,} loans from {name} held back for testing, the typical rate here was off "
                     f"by {t['miss_pts']:.2f} points on average, against {t['rule_miss_pts']:.2f} for the rule of "
                     "thumb.")
        if t["loans"] < FEW_TEST_LOANS:
            parts.append("That test is small, so treat it with care.")
    return "<p class='mc-note mc-lender-test'>" + " ".join(parts) + "</p>"


def _same_lender(same_lender, lender) -> str:
    if same_lender:
        diff = float(same_lender["difference_pts"])  # this lender's typical APR minus the whole market's
        versus = "about the same" if abs(diff) < 0.005 else f"{abs(diff):.2f} points {'higher' if diff > 0 else 'lower'}"
        rows = "".join(f"<tr><th scope='row'>{label}</th><td>{value}</td></tr>" for label, value in [
            ("Lender", _esc(same_lender["lender"])),
            ("Typical APR at this lender", _pct(same_lender["typical_pct"])),
            ("Versus all lenders", versus),
            ("Loans from this lender in our data", f"{int(same_lender['n_loans']):,}"),
        ])
        return (
            '<section class="mc-section"><h3>Loans from the same lender</h3>'
            f'<table class="mc-table mc-kv">{rows}</table></section>'
        )
    if lender:
        return (
            '<section class="mc-section"><h3>Loans from the same lender</h3>'
            f"<p>We don't have enough loans from {_esc(lender)} in our data to compare, "
            "so the result above uses all lenders.</p></section>"
        )
    return ""


def _lenders_section(lenders, typed_lender) -> str:
    """The same offer at each lender in the data, each compared with that lender's own similar loans."""
    if not lenders:
        return ""
    rows = []
    for row in lenders:
        mark = ' class="mc-row-yours"' if row["yours"] else ""
        name = _esc(row["lender"]) + (' <span class="mc-yours">your lender</span>' if row["yours"] else "")
        rows.append(f"<tr{mark}><th scope='row'>{name}<span class='mc-sub'>{int(row['n_loans']):,} loans</span></th>"
                    f"<td>{_pct(row['typical_pct'])}</td>"
                    f"<td>{_pct(row['range_low_pct'])}–<wbr>{_pct(row['range_high_pct'])}</td>"
                    f"<td>{_flag_chip(row['flag'])}</td></tr>")
    named = any(row["yours"] for row in lenders)
    if named:
        intro = "Your offer next to each lender's own similar loans. Your lender is marked."
    elif typed_lender:
        intro = (f"We don't have loans from {_esc(typed_lender)} in our data, so here is your offer next to "
                 "each lender we do have.")
    else:
        intro = ("Your offer next to each lender's own similar loans. Add your lender above to make it the main "
                 "comparison.")
    return (
        '<section class="mc-section"><h3>Your offer at each lender</h3>'
        f'<p class="mc-section-intro">{intro}</p>'
        '<table class="mc-table mc-lenders"><thead><tr><th scope="col">Lender</th><th scope="col">Typical</th>'
        '<th scope="col">Range</th><th scope="col">Your offer</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )


def _credit_union_section(cu, offer_apr: float, term: int | None = None, fresh=None) -> str:
    if not cu:
        return ""
    kind = "new-car" if cu["new_or_used"] == "new" else "used-car"
    gap = offer_apr - float(cu["credit_union_pct"])
    where = (f"Your offer is {gap:.1f} points above the credit-union average." if gap >= 0.05 else
             f"Your offer is {abs(gap):.1f} points below the credit-union average." if gap <= -0.05 else
             "Your offer matches the credit-union average.")
    return (
        '<section class="mc-section"><h3>Credit unions and banks</h3>'
        f"<p>On {_esc(cu['rate_date'])}, credit unions reported an average of "
        f"<strong>{_pct(cu['credit_union_pct'])}</strong> and banks <strong>{_pct(cu['bank_pct'])}</strong> "
        f"for a {int(cu['term_months'])}-month {kind} loan (NCUA, from S&amp;P Global data). {where}"
        + (f" NCUA reports no {term}-month rate, so this compares with its closest term."
           if term and int(term) != int(cu["term_months"]) else "") + "</p>"
        + _fresh_rates_lines(fresh)
        + "<p class='mc-note'>These are national averages, not adjusted for credit score, so they show where to ask "
        "rather than your rate. A pre-approval from a credit union gives you a real number to compare.</p></section>"
    )


def _sponsor_slot(fresh) -> str:
    """An empty, hidden place for a partner's block. The page script fills it only when the address names a
    partner (?partner=...), so the server's result, and every number in it, is the same with or without one."""
    if not fresh:
        return ""
    return (f'<div class="mc-sponsor-slot" hidden data-kind="{fresh["new_or_used"]}" '
            f'data-median="{fresh["median_pct"]}" data-asof="{fresh["as_of"]}"></div>')


def _fresh_rates_lines(fresh) -> str:
    if not fresh:
        return ""
    as_of = datetime.datetime.strptime(fresh["as_of"], "%Y-%m-%d")
    kind = "new-car" if fresh["new_or_used"] == "new" else "used-car"
    out = (f"<p>Newer: on {as_of:%B} {as_of.day}, {as_of.year}, the middle credit union was offering "
           f"<strong>{_pct(fresh['median_pct'])}</strong> on {kind} loans, and half were between "
           f"{_pct(fresh['p25_pct'])} and {_pct(fresh['p75_pct'])} ({fresh['n']:,} credit unions reporting to NCUA). "
           "Each credit union reports one posted rate, not a rate for your credit score.</p>")
    g = {s["label"]: s for s in fresh.get("g19") or []}
    b60, b72 = g.get("Commercial banks, new car, 60-month"), g.get("Commercial banks, new car, 72-month")
    fin = g.get("Finance companies, new car (all terms)")
    if b60 and b72 and fin:
        out += (f"<p>Banks' average new-car rates (Federal Reserve G.19, {b60['period']}"
                + (", preliminary" if b60["preliminary"] else "")
                + f"): {_pct(b60['value_pct'])} for 60 months and {_pct(b72['value_pct'])} for 72 months; finance "
                f"companies {_pct(fin['value_pct'])} ({fin['period']}).</p>")
    return out


def _checks_section(result: dict) -> str:
    """Does the verdict survive each doubt about the inputs and the data? Plus how much data backs it,
    and how often loans priced like this later ran into trouble."""
    checks, evidence, risk = result.get("checks"), result.get("evidence"), result.get("risk")
    if checks is None and not evidence:
        return ""
    verdict = FLAG_TEXT.get(str(result["flag"]), (str(result["flag"]).capitalize(),))[0]
    parts = ['<section class="mc-section"><h3>How sure is this?</h3>']
    if checks:
        held = sum(1 for c in checks if c["same_flag"])
        if held == len(checks):
            parts.append(f"<p class='mc-check-summary'>Your verdict, <strong>{_esc(verdict)}</strong>, holds in "
                         f"<strong>all {len(checks)}</strong> checks below.</p>")
        else:
            parts.append(f"<p class='mc-check-summary'>Your verdict, <strong>{_esc(verdict)}</strong>, changes in "
                         f"<strong>{len(checks) - held} of {len(checks)}</strong> checks below, so treat it as "
                         "less certain.</p>")
        items = "".join(
            f"<li><span class='mc-check-q'>{_esc(c['question'])}:</span> typical {_pct(c['typical_pct'])}, "
            f"range {_pct(c['range_low_pct'])}–{_pct(c['range_high_pct'])}. Your offer: {_flag_chip(c['flag'])}</li>"
            for c in checks)
        parts.append(f"<ul class='mc-checks'>{items}</ul>")
    if evidence:
        n = int(evidence["n_similar"])
        line = (f"<strong>{n:,}</strong> of the {int(evidence['n_loans']):,} loans in the data are like yours "
                "(same new or used, credit score within about 20 points, term within about 6 months).")
        if n < 500:
            line += " That's few, so treat the range with care."
        rare = " ".join(_esc(r) for r in evidence.get("rare") or [])
        parts.append(f"<p><strong>Evidence.</strong> {line}{(' ' + rare) if rare else ''}</p>")
    if risk and risk.get("rows"):
        rates = "; ".join(f"{_esc(r['lender'])} {100 * r['bad_rate_high']:.0f}% against {100 * r['bad_rate_other']:.0f}%"
                          for r in risk["rows"])
        parts.append(
            f"<p><strong>Risk.</strong> In our repayment test, loans priced above 90% of similar loans were more often "
            f"30 or more days late or charged off within about {float(risk['months']):.0f} months than other "
            f"loans: {rates}. So part of a high price can be risk the data doesn't show, not only a markup.</p>")
    parts.append(_forward_line(result.get("forward_test")))
    parts.append("</section>")
    return "".join(parts)


def _forward_line(f) -> str:
    """The frozen model on newer loans it never saw (src/forward_test.py), so a buyer knows how the range has aged."""
    if not f:
        return ""
    return (f"<p><strong>On newer loans.</strong> We later tested the same model, unchanged, on {f['loans']:,} "
            f"{_esc(f['lender'])} loans from {_esc(f['months'])}. Its typical price stayed closer than the rule of "
            f"thumb (off by {f['model_mae']:.2f} points against {f['rule_mae']:.2f}), but the range held for only "
            f"{f['coverage_pct']:.0f}% of them, and {f['below_pct']:.0f}% were cheaper than the range. So for newer "
            "loans the range may sit too high, and an offer can look more typical than it is.</p>")


def _view_line(view) -> str:
    """'whole market' or 'same lender: <name>' -> a small line above the big number."""
    if not view:
        return ""
    view = str(view)
    if view.lower().startswith("same lender:"):
        text = f"same lender ({view.split(':', 1)[1].strip()})"
    elif view.lower() == "whole market":
        text = "whole market (all lenders)"
    else:
        text = view
    return f'<p class="mc-view">Compared with: {_esc(text)}</p>'


def _market_line(market) -> str:
    """Whole-market comparison shown under the headline when the main view is same-lender."""
    if not market:
        return ""
    line = (f"Across all lenders: typical {_pct(market['typical_pct'])}, "
            f"range {_pct(market['range_low_pct'])}–{_pct(market['range_high_pct'])}")
    if market.get("percentile") is not None:
        line += f"; your APR is higher than {percentile_text(market['percentile'])} of those loans"
    if market.get("flag"):
        line += f" ({_esc(FLAG_TEXT.get(market['flag'], (market['flag'],))[0].lower())})"
    return f'<p class="mc-market">{line}.</p>'


def _rule_line(rule, low: float, high: float) -> str:
    """The credit-tier rule of thumb (the write-up's B1 baseline) for this offer, beside the model's range."""
    if not rule:
        return ""
    t = rule["test"]
    return (
        "<p class='mc-note mc-rule'><strong>Next to a simple rule of thumb.</strong> A rate table that uses only your "
        f"credit tier ({explore.TIER_LABELS.get(rule['tier'], rule['tier'])}) and new or used would say typical "
        f"{_pct(rule['typical_pct'])}, range {_pct(rule['range_low_pct'])} to {_pct(rule['range_high_pct'])}. "
        "MarkupCheck also uses the car's age, the amount, the loan-to-value and the term; its range for you is "
        f"{high - low:.1f} points wide, the rule's {rule['range_high_pct'] - rule['range_low_pct']:.1f}. In our test "
        f"on later loans, its typical price was off by {t['model_mae']:.2f} points on average, against "
        f"{t['rule_mae']:.2f} for the rule.</p>"
    )


def _recalibrated_line(rc) -> str:
    """Says when the same-lender range was updated from that lender's newest filings (src/recalibrate.py)."""
    if not rc:
        return ""
    first, last = (datetime.datetime.strptime(m, "%Y-%m") for m in (rc["months"][0], rc["months"][-1]))
    span = (f"{last:%B %Y}" if first == last else f"{first:%B} to {last:%B %Y}" if first.year == last.year
            else f"{first:%B %Y} to {last:%B %Y}")
    way = "lower" if float(rc.get("shift_points", -1)) < 0 else "higher"
    return (f'<p class="mc-note mc-fresh">This range was updated with {_esc(rc["lender"])}\'s newest filed loans '
            f"({span}, {rc['loans']:,} loans), because its newer loans were priced {way} than the model expected.</p>")


def _freshness_line(months) -> str:
    """How old the loan data is on the day of the check, so a buyer can weigh the verdict."""
    if not months:
        return ""
    newest = datetime.datetime.strptime(months["newest_loans"], "%Y-%m")
    today = datetime.date.today()
    age = (today.year - newest.year) * 12 + today.month - newest.month
    text = f"Newest loans in our data: {newest:%B %Y}"
    if age > 0:
        text += f", {age} month{'s' if age != 1 else ''} before this check"
    rate = datetime.datetime.strptime(months["rate_benchmark"], "%Y-%m")
    text += f". Your offer is compared after adjusting for the {rate:%B %Y} Treasury rate."
    if age > 6:
        text += " Rates may have moved since; the checks below show how much that could matter."
    return f'<p class="mc-note mc-fresh">{text}</p>'


def _what_to_do(offer: dict) -> str:
    extra_financed = offer["amount_financed"] - offer["vehicle_price"]
    if extra_financed > 0:
        add_ons = (
            f"You're financing {_usd(extra_financed)} more than the car's price. Ask what that covers "
            "(taxes and fees, or extras like an extended warranty or GAP coverage) and whether you can drop any of it."
        )
    else:
        add_ons = ("Extras like an extended warranty or GAP coverage are often added to the loan. "
                   "Ask what is included and whether you can drop any of it.")
    return (
        '<section class="mc-section"><h3>What to do</h3><ul class="mc-list">'
        "<li><strong>Ask for the buy rate.</strong> That is the rate the lender approved you for, "
        "before the dealer adds anything. Ask the dealer to bring your rate down to it.</li>"
        "<li><strong>Bring a credit-union pre-approval.</strong> A written offer from a credit union "
        "or bank gives you a rate to compare and lets you finance somewhere else. "
        "<a href='https://mapping.ncua.gov/' target='_blank' rel='noopener noreferrer'>Find a credit union near you</a> "
        "(NCUA's locator).</li>"
        f"<li><strong>Check the amount financed for add-ons.</strong> {add_ons}</li>"
        "</ul></section>"
    )


def render_result(result: dict, offer: dict, payment: float | None = None, addons: float | None = None,
                  derived: bool = False) -> str:
    offer_apr = offer["offered_apr_pct"]
    low, high = float(result["range_low_pct"]), float(result["range_high_pct"])
    typical = float(result["typical_pct"])
    percentile = float(result["percentile"])
    extra = float(result["extra_cost_usd"])
    term = offer["term_months"]

    parts = ['<div class="mc-result">']

    if result.get("stub"):
        parts.append(
            '<div class="mc-banner" role="note"><strong>Placeholder numbers.</strong> '
            "The trained model is not connected yet, so every number below is a placeholder, "
            "not a real comparison.</div>"
        )

    parts.append(_view_line(result.get("view")))

    # The verdict comes first: the flag and one plain sentence, before any numbers to interpret.
    flag = str(result["flag"])
    name, css_class, explanation = FLAG_TEXT.get(flag, (flag.capitalize(), "mc-flag-high", ""))
    if flag == "typical" and offer_apr < low:
        explanation = "That's a good rate for a profile like yours."
    parts.append(
        f'<section class="mc-verdict mc-verdict-{css_class}">'
        f'<h2 class="mc-verdict-name"><span class="mc-flag {css_class}">{_esc(name)}</span></h2>'
        f'<p class="mc-verdict-line">{_verdict_sentence(offer_apr, low, high, typical)}</p>'
        + (f'<p class="mc-verdict-detail">{explanation}</p>' if explanation else "")
        + "</section>"
    )
    if derived and payment:
        parts.append(sections.derived_apr_note(offer_apr, payment))
    parts.append(sections.jump_links())

    parts.append(
        '<p class="mc-headline">Your APR is higher than '
        f'<span class="mc-percent">{percentile_text(percentile)}</span> of similar loans</p>'
    )
    parts.append(_market_line(result.get("market")))
    parts.append(_freshness_line(result.get("data_months")))
    parts.append(_lender_test_line(result.get("same_lender")))
    parts.append(_recalibrated_line(result.get("recalibrated")))

    parts.append(
        '<section class="mc-section"><h3>Where your rate sits</h3>'
        + _range_bar(low, high, typical, offer_apr)
        + '<p class="mc-legend" aria-hidden="true"><span class="mc-key mc-key-range"></span>Range similar loans mostly got '
        f'<span class="mc-key mc-key-typical"></span>Typical ({_pct(typical)}) '
        f'<span class="mc-key mc-key-offer"></span>Your offer ({_pct(offer_apr)})</p>'
        + f"<p class='mc-caption'>Similar loans mostly got an APR between <strong>{_pct(low)}</strong> "
        f"and <strong>{_pct(high)}</strong>. The range aims to hold 8 in 10 loans; in our test on later loans "
        f"it held for {float(result.get('range_coverage_pct', 80.0)):.0f}% of buyers like you.</p>"
        + _rule_line(result.get("rule_of_thumb"), low, high)
        + sections.distribution_chart(result, offer) + "</section>"
    )

    if extra > 0.5:
        cost_line = f"That's <strong>{_usd(extra)} more</strong> over {term} months than at the typical APR."
    elif extra < -0.5:
        # A negative extra cost means the offer is cheaper than typical; show the size, never a minus sign.
        cost_line = (f"That's about <strong>{_usd(extra)} less</strong> than a typical loan like yours, "
                     f"over {term} months.")
    else:
        cost_line = f"That's about the same as the typical APR over {term} months."
    parts.append(
        '<section class="mc-section"><h3>What it costs you</h3>'
        '<table class="mc-table"><thead><tr><th scope="col"></th><th scope="col">APR</th>'
        '<th scope="col">Monthly payment</th></tr></thead><tbody>'
        f"<tr><th scope='row'>Your offer</th><td>{_pct(offer_apr)}</td>"
        f"<td>{_usd(result['monthly_payment_offer'], cents=True)}</td></tr>"
        f"<tr><th scope='row'>Typical for similar loans</th><td>{_pct(typical)}</td>"
        f"<td>{_usd(result['monthly_payment_typical'], cents=True)}</td></tr>"
        f"</tbody></table><p class='mc-cost'>{cost_line}</p>"
        + sections.cost_per_point_line(offer) + sections.timeline_chart(result, offer) + "</section>"
    )
    parts.append(sections.whole_deal_section(result, offer))
    if payment and not derived:
        parts.append(sections.payment_section(offer, payment))
    if addons:
        parts.append(sections.addons_section(offer, addons))

    if result.get("lenders"):
        parts.append(_lenders_section(result["lenders"], offer.get("lender")))
    else:
        parts.append(_same_lender(result.get("same_lender"), offer.get("lender")))
    parts.append(_credit_union_section(result.get("credit_union"), offer_apr, term, result.get("fresh_rates")))
    parts.append(_sponsor_slot(result.get("fresh_rates")))
    parts.append(sections.better_rate_section(result, offer))
    parts.append(_checks_section(result))

    reasons = "".join(f"<li>{_esc(r)}</li>" for r in result["reasons"])
    parts.append(
        '<section class="mc-section"><h3>Why this is the typical price</h3>'
        + sections.waterfall_chart(result) + f'<ul class="mc-list">{reasons}</ul></section>'
    )

    parts.append(_what_to_do(offer))
    parts.append(sections.dealer_card(result, offer, payment, addons))
    parts.append(sections.pushback_section(result, offer))
    parts.append(sections.quote_request_section(offer))
    parts.append(sections.state_section(offer))
    parts.append(sections.questions_section(result, offer))

    weak = "".join(f"<li>{_esc(w)}</li>" for w in result["weak_spots"])
    parts.append(
        "<section class='mc-section'><h3>What the data can't tell you</h3>"
        f'<ul class="mc-list">{weak}</ul>'
        f"<p class='mc-note'><strong>Data used:</strong> {_esc(result['data_note'])}</p></section>"
    )

    parts.append(f'<p class="mc-disclaimer">{DISCLAIMER}</p>')
    parts.append("</div>")
    return "".join(parts)


# ---------------------------------------------------------------- handlers


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _prepare(credit_score, new_or_used, vehicle_model_year, vehicle_price,
             amount_financed, term_months, offered_apr_pct, lender, payment=None, addons=None):
    """Validate everything the buyer typed. With a monthly payment and no APR, the APR is worked out from the
    payment first. Returns (offer or None, errors, payment, add-ons, whether the APR was worked out)."""
    pay, add = _number(payment), _number(addons)
    extra, derived = [], False
    if not _blank(payment) and (pay is None or pay <= 0):
        extra.append((L_PAYMENT, "Enter the monthly payment in dollars (more than $0), or leave it blank."))
        pay = None
    if not _blank(addons) and (add is None or add < 0):
        extra.append((L_ADDONS, "Enter the add-ons in dollars, or leave the field blank."))
        add = None
    if _blank(offered_apr_pct) and pay:
        amt, t = _number(amount_financed), _number(term_months)
        if amt and t and amt > 0 and t >= 1:
            apr = finance.apr_from_payment(amt, pay, int(t))
            if apr is None:
                extra.append((L_PAYMENT, f"A {_usd(pay, cents=True)} payment doesn't fit {_usd(amt)} over {int(t)} "
                                         "months at any APR from 0% to 60%. Check the payment, amount and term."))
            else:
                offered_apr_pct, derived = round(apr, 2), True
    offer, errors = validate(credit_score, new_or_used, vehicle_model_year, vehicle_price,
                             amount_financed, term_months, offered_apr_pct, lender)
    if offer and add and add >= offer["amount_financed"]:
        extra.append((L_ADDONS, "The add-ons can't be more than the amount financed, which already includes them."))
    errors = errors + extra
    return (None if errors else offer), errors, pay, (add or None), derived


def check_offer(credit_score, new_or_used, vehicle_model_year, vehicle_price,
                amount_financed, term_months, offered_apr_pct, lender, payment=None, addons=None) -> str:
    """Validate the inputs, call the model, and return the result panel as HTML (with both an APR and a
    payment, the payment is checked against the APR)."""
    offer, errors, pay, add, derived = _prepare(credit_score, new_or_used, vehicle_model_year, vehicle_price,
                                                amount_financed, term_months, offered_apr_pct, lender, payment, addons)
    if errors:
        return render_errors(errors)
    try:
        result = markupcheck_model.predict(offer)
        return render_result(result, offer, payment=pay, addons=add, derived=derived)
    except Exception as exc:
        ref = _log_error("check_offer", exc)
        return render_errors([(None, "Something went wrong on our side, not with your entries. They are still "
                                     "in the form, so press Check my rate to try again.")],
                             heading="We couldn't check this offer", ref=ref)


def jordan_example():
    return JORDAN


def sam_example():
    return SAM


def _log_error(scope: str, exc: Exception) -> str:
    """One JSON line per error, as AdmitPath logs them (the offer itself is not logged); returns its reference."""
    ref = uuid.uuid4().hex[:8]
    # Only the error's type and the code lines it passed through: its message can quote the buyer's numbers.
    print(json.dumps({"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(), "level": "error",
                      "scope": scope, "ref": ref, "message": type(exc).__name__,
                      "stack": "".join(traceback.format_tb(exc.__traceback__))}), file=sys.stderr)
    return ref


API_VERSION = "1"  # raise it when a field is removed or changes meaning; new fields don't need a new version


def _plain(value):
    """NumPy numbers as Python ones: Gradio's queue stream (the one gradio_client reads) sends NumPy values as strings."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value.item() if isinstance(value, np.generic) else value


def check_api(credit_score: float, new_or_used: str, model_year: int, vehicle_price: float, amount_financed: float,
              term_months: int, apr: float | None = None, lender: str = "", payment: float | None = None) -> dict:
    """JSON version of a check for other programs. Pass the APR, or leave it empty and pass the monthly
    payment. Returns {"errors": [...]} or {"offer": ..., "result": ...} with the same numbers the page shows."""
    offer, errors, pay, _, derived = _prepare(credit_score, new_or_used, model_year, vehicle_price, amount_financed,
                                              term_months, apr, lender, payment, None)
    if errors:
        return {"errors": [{"field": f, "message": html.unescape(m)} for f, m in errors]}
    try:
        result = markupcheck_model.predict(offer, grid=False)
    except Exception as exc:
        return {"errors": [{"field": None, "message": "Something went wrong on our side, not with your entries. "
                                                      "Try again in a moment.", "reference": _log_error("check_api", exc)}]}
    result = {k: v for k, v in result.items() if k != "whatif"}  # the slider grid is page-only
    out = {"api_version": API_VERSION, "offer": offer, "apr_from_payment": derived, "result": result,
           "verdict": FLAG_TEXT.get(result["flag"], (result["flag"],))[0], "disclaimer": DISCLAIMER}
    if pay and not derived:
        out["payment_check"] = finance.payment_check(offer["amount_financed"], offer["term_months"],
                                                     offer["offered_apr_pct"], pay)
    return _plain(out)


def _english_props(block) -> dict:
    """The English text of a fixed component, for re-labelling it on a language switch."""
    if isinstance(block, gr.HTML):
        return {"value": block.value}
    if isinstance(block, (gr.Tab, gr.DownloadButton)):  # a DownloadButton's text is its label; its value is the file
        return {"label": block.label}
    if isinstance(block, gr.Button):
        return {"value": block.value}
    props = {k: getattr(block, k, None) for k in ("label", "info", "placeholder") if getattr(block, k, None)}
    if isinstance(block, (gr.Radio, gr.Dropdown)):
        props["choices"] = [tuple(c) for c in block.choices]
    return props


def _localized(props: dict, lang: str) -> dict:
    out = {}
    for key, value in props.items():
        if key == "choices":
            out[key] = [(i18n.t(label, lang), val) for label, val in value]
        elif key == "value" and isinstance(value, str) and value.lstrip().startswith("<"):
            out[key] = i18n.translate_html(value, lang)
        else:
            out[key] = i18n.t(value, lang)
    return out


def batch_handler(file):
    if not file:
        return "<div class='mc-result'><p class='mc-note'>Choose a CSV file first.</p></div>", None
    return tabs.batch_check(file)


# ---------------------------------------------------------------- page
#
# The page follows the AdmitPath design system (app/globals.css and app/layout.tsx in that project) rule by
# rule. The few differences are noted where they occur; each is an accessibility fix.

APP_DIR = Path(__file__).resolve().parent
FONT_DIR = APP_DIR / "fonts"  # self-hosted Latin subsets (fonts/OFL.txt), so no request leaves the app
FAVICON = APP_DIR / "favicon.svg"

SANS = ["Inter", "Inter Fallback", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "sans-serif"]
MONO = ["JetBrains Mono", "JetBrains Mono Fallback", "Fira Code", "Consolas", "ui-monospace", "monospace"]
SERIF = "'Lora', 'Playfair Display', Georgia, serif"
MONO_CSS = "'JetBrains Mono', 'JetBrains Mono Fallback', 'Fira Code', Consolas, ui-monospace, monospace"
SHADOW_SM = "0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.06)"
EASE = "cubic-bezier(0.4, 0, 0.2, 1)"
EASE_OUT = "cubic-bezier(0.16, 1, 0.3, 1)"

THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.blue,
    secondary_hue=gr.themes.colors.slate,
    neutral_hue=gr.themes.colors.slate,
    radius_size=gr.themes.sizes.radius_md,
    font=SANS,
    font_mono=MONO,
).set(
    body_background_fill=GROUND,
    body_background_fill_dark=GROUND,  # AdmitPath is light-only (see HEAD); avoids a dark flash while loading
    body_text_color=TEXT,
    body_text_color_dark=TEXT,
    body_text_color_subdued=MUTED,
    body_text_size="15px",
    color_accent=ACCENT,
    color_accent_soft=PRIMARY_LIGHT,
    border_color_accent=ACCENT,
    border_color_primary="rgba(0, 0, 0, 0.09)",
    background_fill_primary=SURFACE,
    background_fill_secondary=SUNKEN,
    block_background_fill="transparent",
    block_border_width="0px",
    block_shadow="none",
    block_shadow_dark="none",
    block_title_text_color=SECONDARY,
    block_label_text_color=SECONDARY,
    block_info_text_color=MUTED,
    block_info_text_size="12px",
    link_text_color=BRAND_TEXT,
    link_text_color_hover=BRAND_DARK,
    link_text_color_visited=BRAND_TEXT,
    link_text_color_active=BRAND_DARK,
    loader_color=ACCENT,
    input_background_fill="rgba(255, 255, 255, 0.7)",
    input_background_fill_hover="rgba(255, 255, 255, 0.85)",
    input_background_fill_focus="rgba(255, 255, 255, 0.95)",
    input_border_width="1px",
    input_border_color="rgba(0, 0, 0, 0.09)",
    input_border_color_hover="rgba(74, 111, 165, 0.25)",
    input_border_color_focus=ACCENT,
    input_radius="10px",
    # AdmitPath's placeholder grey #6B748A is 4.4:1 here; the muted grey passes.
    input_placeholder_color=MUTED,
    input_shadow="none",
    input_shadow_focus="0 0 0 4px rgba(74, 111, 165, 0.1), 0 2px 8px rgba(74, 111, 165, 0.08)",
    input_text_size="16px",  # AdmitPath uses 14px; iOS Safari zooms the page when a focused input is under 16px
    checkbox_label_padding="12px 12px",
    checkbox_label_background_fill="rgba(255, 255, 255, 0.5)",
    checkbox_label_background_fill_hover="rgba(74, 111, 165, 0.05)",
    checkbox_label_background_fill_selected="rgba(74, 111, 165, 0.08)",
    checkbox_label_border_color="rgba(0, 0, 0, 0.09)",
    checkbox_label_border_color_hover=ACCENT,
    checkbox_label_border_color_selected=ACCENT,
    checkbox_label_text_color=TEXT,
    checkbox_background_color_selected=ACCENT,
    checkbox_border_color_selected=ACCENT,
    checkbox_border_color_focus=ACCENT,
    button_large_radius="14px",
    button_medium_radius="12px",
    button_small_radius="10px",
    button_primary_background_fill=f"linear-gradient(135deg, {ACCENT} 0%, {BRAND_DARK} 100%)",
    # AdmitPath's hover runs #5580B5 to #3A5A7E, where white text drops to 4.1:1; starting at ACCENT keeps 4.7:1.
    button_primary_background_fill_hover=f"linear-gradient(135deg, {ACCENT} 0%, {BRAND_TEXT} 100%)",
    button_primary_text_color="#ffffff",
    button_primary_text_color_hover="#ffffff",
    button_primary_shadow="none",
    button_primary_shadow_hover="none",
    button_primary_shadow_active="none",
    button_secondary_background_fill="rgba(255, 255, 255, 0.7)",
    button_secondary_background_fill_hover="rgba(255, 255, 255, 0.9)",
    button_secondary_border_color="rgba(0, 0, 0, 0.08)",
    button_secondary_border_color_hover=ACCENT,
    button_secondary_text_color=TEXT,
    button_secondary_text_color_hover=BRAND_TEXT,
    button_secondary_shadow="none",
    button_secondary_shadow_hover="none",
    button_secondary_shadow_active="none",
)

LATIN = ("U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, "
         "U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD")
FONT_FACES = (
    "@font-face{font-family:'Inter';font-style:normal;font-weight:400 800;font-display:swap;"
    f"src:url(mc-fonts/inter-latin.woff2) format('woff2');unicode-range:{LATIN}}}"
    "@font-face{font-family:'Inter Fallback';src:local('Arial');ascent-override:90.44%;descent-override:22.52%;"
    "line-gap-override:0%;size-adjust:107.12%}"
    "@font-face{font-family:'JetBrains Mono';font-style:normal;font-weight:700;font-display:swap;"
    f"src:url(mc-fonts/jetbrains-mono-latin.woff2) format('woff2');unicode-range:{LATIN}}}"
    "@font-face{font-family:'JetBrains Mono Fallback';src:local('Arial');ascent-override:75.79%;"
    "descent-override:22.29%;line-gap-override:0%;size-adjust:134.59%}"
    "@font-face{font-family:'Lora';font-style:italic;font-weight:700;font-display:swap;"
    f"src:url(mc-fonts/lora-latin-700-italic.woff2) format('woff2');unicode-range:{LATIN}}}"
)
# Page-level rules live in the head, not in CSS: Gradio scopes every `css` rule to its content area
# (".gradio-container .contain ..."), so rules for html, body, gradio-app or the container itself, and any
# such rule inside an @media block, would never match there.
PAGE_CSS = (
    "html,body{overflow-x:clip}"
    "body{-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;text-rendering:optimizeLegibility;"
    "-webkit-text-size-adjust:100%;-webkit-tap-highlight-color:rgba(74,111,165,0.10)}"
    f"::selection{{background:{PRIMARY_LIGHT};color:{BRAND_TEXT}}}"
    "html{scrollbar-width:thin;scrollbar-color:rgba(74,111,165,0.2) transparent}"
    "::-webkit-scrollbar{width:8px;height:8px}::-webkit-scrollbar-thumb{background:rgba(74,111,165,0.2);border-radius:100px}"
    "::-webkit-scrollbar-thumb:hover{background:rgba(74,111,165,0.35)}"
    "gradio-app{background-image:linear-gradient(rgba(0,0,0,0.028) 1px,transparent 1px),"
    "linear-gradient(90deg,rgba(0,0,0,0.028) 1px,transparent 1px)!important;background-size:40px 40px!important}"
    # min-width 0 lets the container shrink to a phone's width instead of its content's widest word.
    ".gradio-container{max-width:1200px!important;width:100%!important;min-width:0!important;"
    "margin-left:auto!important;margin-right:auto!important;padding:32px 36px!important}"
    ".gradio-container .main.fillable{padding:0!important}"
    "@media (max-width:900px){.gradio-container{padding:24px 20px!important}}"
    "@media (max-width:600px){.gradio-container{padding:16px 14px!important}}"
    "@media print{@page{margin:0.6in}body,gradio-app,.gradio-container{background:#ffffff!important;"
    "background-image:none!important}body{font-size:12pt}"
    ".gradio-container,.gradio-container .main,.gradio-container .wrap{overflow:visible!important;height:auto!important}"
    ".mc-whatif,.mc-card-actions,.tab-wrapper,[role=tablist],#mc-topbar{display:none!important}"
    "body.mc-printing-card #mc-header,body.mc-printing-card #mc-footer,"
    "body.mc-printing-card .mc-result>:not(#mc-card){display:none!important}"
    "body.mc-printing-sheet #mc-header,body.mc-printing-sheet #mc-footer,body.mc-printing-sheet [role=tablist],"
    "body.mc-printing-sheet .mc-teacher>:not(#mc-sheet),body.mc-printing-sheet #mc-sheet .mc-card-actions"
    "{display:none!important}}"
    f"#mc-offline{{position:fixed;left:16px;right:16px;bottom:16px;z-index:1000;max-width:640px;margin:0 auto;"
    f"padding:12px 16px;border-radius:12px;background:{TEXT};color:#ffffff;"
    "font:500 15px/1.5 'Inter','Inter Fallback',system-ui,sans-serif;box-shadow:0 8px 24px rgba(27,32,48,0.25)}"
    "#mc-offline[hidden]{display:none}"
    "@media print{#mc-offline{display:none!important}}"
)
DESCRIPTION = ("Check whether a car-loan APR is fair: MarkupCheck compares it with similar real loans from public "
               "SEC filings. A student prototype, not financial advice.")
JSON_LD = json.dumps({"@context": "https://schema.org", "@type": "WebApplication", "name": "MarkupCheck",
                      "applicationCategory": "FinanceApplication", "operatingSystem": "Any",
                      "description": DESCRIPTION, "isAccessibleForFree": True})

# Gradio follows the phone's dark-mode setting, but AdmitPath is light-only (its ThemeProvider has
# enableSystem off), so the first script removes the "dark" class whenever Gradio adds it. Gradio injects
# these scripts after it has read ?__theme=, so a URL parameter can't do this. The second gives the number
# fields a number keypad on phones. The third marks the fields a validation message names as aria-invalid
# and reads each new verdict out through a polite live region. Both re-run on DOM changes because Gradio
# renders the inputs and results after these scripts run.
PARTNERS = {k: v for k, v in json.loads((Path(__file__).parent / "partners.json").read_text()).items()
            if not k.startswith("_")}
PARTNERS_JSON = json.dumps(PARTNERS).replace("</", "<\\/")  # inside a <script>, "</" could end it
PARTNER_JS = (
    "<script>(() => { if (window.__mcPartner) return; window.__mcPartner = 1;"
    f" const P = {PARTNERS_JSON};"
    " const key = new URLSearchParams(location.search).get('partner');"
    " const p = key && Object.prototype.hasOwnProperty.call(P, key) && P[key]; if (!p) return;"
    " const el = (tag, text, cls) => { const e = document.createElement(tag); if (text) e.textContent = text;"
    "  if (cls) e.className = cls; return e; };"
    " const fill = () => document.querySelectorAll('.mc-sponsor-slot[hidden]').forEach(s => {"
    "  const es = document.documentElement.lang === 'es', used = s.dataset.kind === 'used';"
    "  const rate = s.dataset.median + '%', d = new Date(s.dataset.asof + 'T12:00:00');"
    "  const day = d.toLocaleDateString(es ? 'es-US' : 'en-US', {year: 'numeric', month: 'long', day: 'numeric'});"
    "  const name = es ? p.name_es : p.name; const box = el('section', '', 'mc-section mc-sponsor');"
    "  box.append(el('h3', (es ? 'De ' : 'From ') + name));"
    "  box.append(el('p', es ? name + ' es un nombre inventado para esta demostración. Una cooperativa de crédito podría mostrar"
    " aquí su propia tasa publicada; esta demostración muestra en su lugar la tasa mediana de las cooperativas de crédito del país'"
    " + ' para un préstamo de auto ' + (used ? 'usado' : 'nuevo') + ', ' + rate + ' (NCUA, ' + day + ').'"
    "   : name + ' is a made-up name for this demo. A credit union could show its own posted rate here; this demo shows the'"
    " + ' national median credit-union rate for a ' + (used ? 'used' : 'new') + '-car loan instead, ' + rate + ' (NCUA, ' + day + ').'));"
    "  const a = el('a', es ? 'Encuentra una cooperativa de crédito' : 'Find a credit union'); a.href = p.apply_url;"
    "  a.target = '_blank'; a.rel = 'noopener noreferrer'; const pa = el('p'); pa.append(a); box.append(pa);"
    "  box.append(el('p', es ? 'Quién paga: nadie le paga a MarkupCheck hoy. Un socio puede agregar aquí su nombre, su tasa"
    " publicada y un enlace; no puede cambiar ningún número de arriba, que viene de los datos públicos de préstamos.'"
    "   : 'Who pays: nobody pays MarkupCheck today. A partner can add its name, its posted rate and a link here; it'"
    " + ' can\\'t change any number above, which comes from the public loan data.', 'mc-note'));"
    "  s.replaceChildren(box); s.hidden = false; });"
    " new MutationObserver(fill).observe(document.documentElement, {childList: true, subtree: true}); fill(); })();</script>"
)

HEAD = (
    f"<meta name='description' content='{DESCRIPTION}'>"
    f"<meta name='theme-color' content='{GROUND}'>"
    "<meta name='color-scheme' content='light'>"
    "<meta name='referrer' content='strict-origin-when-cross-origin'>"
    "<meta name='format-detection' content='telephone=no, address=no, email=no'>"
    "<link rel='preload' href='mc-fonts/inter-latin.woff2' as='font' type='font/woff2' crossorigin>"
    f"<style>{FONT_FACES}{PAGE_CSS}</style>"
    f"<script type='application/ld+json'>{JSON_LD}</script>"
    "<noscript><style>body::before{content:'MarkupCheck needs JavaScript to run. Turn it on and reload the page; "
    "nothing you typed is stored.';display:block;padding:16px;font:18px/1.5 Arial,sans-serif;"
    f"background:#fff;color:{TEXT}}}</style></noscript>"
    "<script>(() => { if (window.__mcLight) return; window.__mcLight = 1;"
    " const light = () => document.querySelectorAll('.dark').forEach(e => e.classList.remove('dark'));"
    " light(); new MutationObserver(light).observe(document.documentElement,"
    " {attributes: true, attributeFilter: ['class'], subtree: true}); })();</script>"
    "<script>(() => { if (window.__mcKeys) return; window.__mcKeys = 1;"
    " new MutationObserver(() => document.querySelectorAll('.mc-num input, .mc-num textarea')"
    ".forEach(e => { if (e.inputMode !== 'decimal') e.inputMode = 'decimal'; }))"
    ".observe(document.documentElement, {childList: true, subtree: true}); })();</script>"
    "<script>(() => { if (window.__mcLive) return; window.__mcLive = 1;"
    " const live = document.createElement('div'); live.id = 'mc-live'; live.className = 'sr-only';"
    " live.setAttribute('role', 'status'); live.setAttribute('aria-live', 'polite'); let said = ''; const saidTab = {};"
    " new MutationObserver(() => { if (!live.isConnected && document.body) document.body.appendChild(live);"
    " const panel = document.getElementById('mc-result-panel'); if (!panel) return;"
    " [['mc-result-panel', '#mc-form', 'mc-error'], ['mc-compare-panel', '#mc-compare-form', 'mc-error-compare'],"
    "  ['mc-refi-panel', '#mc-refi-form', 'mc-error-refi'], ['mc-tila-panel', '#mc-tila', 'mc-error-tila']].forEach(([pid, form, eid]) => {"
    "  const p = document.getElementById(pid); const err = p && p.querySelector('.mc-error');"
    "  const bad = err ? (err.dataset.invalid || '').split('|').filter(Boolean) : [];"
    "  document.querySelectorAll(form + ' .block').forEach(b => { if (form === '#mc-form' && b.closest('#mc-tila')) return;"
    "   const name = b.querySelector('[data-testid=\"block-info\"]'); const on = !!name && bad.includes(name.textContent.trim());"
    "   b.querySelectorAll('textarea, input').forEach(i => { if (on) { i.setAttribute('aria-invalid', 'true');"
    "    i.setAttribute('aria-describedby', eid); } else if (i.hasAttribute('aria-invalid')) {"
    "    i.removeAttribute('aria-invalid'); i.removeAttribute('aria-describedby'); } }); }); });"
    " const more = document.documentElement.lang === 'es' ? 'Más pestañas' : 'More tabs';"
    " document.querySelectorAll('#mc-tabs .overflow-menu > button').forEach(x => { if (x.getAttribute('aria-label') !== more) x.setAttribute('aria-label', more); });"
    " document.querySelectorAll('fieldset').forEach((fs, n) => { const rs = fs.querySelectorAll('input[type=radio]');"
    "  if (rs.length > 1) rs.forEach(r => { if (r.name !== 'mc-group-' + n) r.name = 'mc-group-' + n; }); });"
    " document.querySelectorAll('.file-preview tr').forEach(tr => { const a = tr.querySelector('a'); const f = tr.querySelector('.filename');"
    "  if (a && f) { const l = (document.documentElement.lang === 'es' ? 'Descargar ' : 'Download ') + f.textContent.trim();"
    "   if (a.getAttribute('aria-label') !== l) a.setAttribute('aria-label', l); } });"
    " const name = panel.querySelector('.mc-verdict-name'); const line = panel.querySelector('.mc-verdict-line');"
    " const text = name ? (name.textContent + '. ' + (line ? line.textContent : '')).trim() : '';"
    " if (text && text !== said) { said = text; live.textContent = text; }"
    " ['mc-compare-panel', 'mc-refi-panel', 'mc-batch-panel', 'mc-tila-panel'].forEach(id => { const el = document.getElementById(id);"
    "  if (!el || el.querySelector('.mc-error')) return; const h = el.querySelector('h3');"
    "  const t = h ? (h.textContent + '. ' + (h.nextElementSibling ? h.nextElementSibling.textContent : '')).trim().slice(0, 240) : '';"
    "  if (t && t !== saidTab[id]) { saidTab[id] = t; live.textContent = t; } });"
    " }).observe(document.documentElement, {childList: true, subtree: true, characterData: true}); })();</script>"
    "<script>(() => { if (window.__mcPage) return; window.__mcPage = 1;"
    " window.addEventListener('beforeprint', () => document.querySelectorAll('details.mc-faq:not([open])')"
    "  .forEach(d => { d.open = true; d.dataset.mcPrinted = '1'; }));"
    " window.addEventListener('afterprint', () => document.querySelectorAll('details[data-mc-printed]')"
    "  .forEach(d => { d.open = false; delete d.dataset.mcPrinted; }));"
    " const pay = (p, apr, n) => { const r = apr / 1200; return r ? p * r / (1 - Math.pow(1 + r, -n)) : p / n; };"
    " const money = v => '$' + v.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});"
    " const dollars = v => '$' + Math.round(v).toLocaleString('en-US');"
    " const pct = v => { let t = v.toFixed(2).replace(/0+$/, ''); if (t.endsWith('.')) t += '0'; return t + '%'; };"
    " const update = root => { const w = JSON.parse(root.dataset.whatif); const q = c => root.querySelector(c);"
    "  const si = +q('.mc-wi-score').value, ti = +q('.mc-wi-term').value, di = +q('.mc-wi-down').value;"
    "  const c = w.cells[(si * w.terms.length + ti) * w.downs.length + di];"
    "  const down = w.downs[di] * w.price, amount = w.amount - down, term = w.terms[ti];"
    "  q('.mc-wi-score-out').textContent = w.scores[si]; q('.mc-wi-score').setAttribute('aria-valuetext', w.scores[si]);"
    "  const es = document.documentElement.lang === 'es';"
    "  const W = es ? ['Típica ', ', la mayoría entre ', ' y ', '. Tu tasa de ', ' sería ', '. Pago con la tasa típica: ', ' meses',"
    "   ' Hay pocos préstamos así en los datos, así que tómalo con cuidado.']"
    "   : ['Typical ', ', most between ', ' and ', '. Your ', ' would be ', '. Payment at the typical rate: ', ' months',"
    "   ' Few loans in the data are like this, so treat it with care.'];"
    "  q('.mc-wi-term-out').textContent = term + W[6]; q('.mc-wi-term').setAttribute('aria-valuetext', term + W[6]);"
    "  q('.mc-wi-down-out').textContent = dollars(down); q('.mc-wi-down').setAttribute('aria-valuetext', dollars(down));"
    "  q('.mc-wi-result').innerHTML = W[0] + pct(c[0]) + W[1] + pct(c[1]) + W[2] + pct(c[2]) +"
    "   W[3] + pct(w.offer_apr) + W[4] + '<span class=\"mc-chip ' + w.classes[c[3]] + '\">' + w.labels[c[3]] +"
    "   '</span>' + W[5] + money(pay(amount, c[0], term)) + '.' + (c[4] != null && c[4] < w.thin ? W[7] : ''); };"
    " document.addEventListener('input', e => { const r = e.target.closest && e.target.closest('.mc-whatif'); if (r) update(r); });"
    " document.addEventListener('change', e => { const sel = e.target.closest && e.target.closest('.mc-state-select');"
    "  if (!sel) return; const sec = sel.closest('.mc-state'), out = sec.querySelector('.mc-state-out');"
    "  const es = document.documentElement.lang === 'es', row = JSON.parse(sec.dataset.states)[sel.value];"
    "  if (!row) { out.textContent = ''; return; } const name = sel.options[sel.selectedIndex].text, used = sec.dataset.kind === 'used';"
    "  const [gap, holds, loans, med, n] = row; let t = '';"
    "  if (gap === null) t = es ? 'Nuestros datos tienen muy pocos préstamos de ' + name + ' para comparar sus precios. '"
    "   : 'Our data has too few loans from ' + name + ' to compare its prices. ';"
    "  else { const pts = Math.abs(gap).toFixed(2), n0 = loans.toLocaleString('en-US');"
    "   t = es ? 'Con el mismo prestamista, los compradores de ' + name + ' pagaron ' + pts + ' puntos ' + (gap > 0 ? 'más' : 'menos')"
    "    + ' que préstamos similares (' + n0 + ' préstamos). ' + (holds ? 'Esto se mantuvo tras una corrección por probar muchos estados. '"
    "    : 'Esto no se mantuvo tras una corrección por probar muchos estados, así que puede ser casualidad. ')"
    "    + 'Los datos no pueden decir por qué: leyes estatales, riesgo o prácticas de los concesionarios. '"
    "    : 'At the same lender, ' + name + ' buyers paid ' + pts + ' points ' + (gap > 0 ? 'more' : 'less') + ' than similar loans ('"
    "    + n0 + ' loans). ' + (holds ? 'This held up after a correction for testing many states. '"
    "    : \"This didn't hold up after a correction for testing many states, so it may be chance. \")"
    "    + \"The data can't say why: state law, risk or dealer practice. \"; }"
    "  if (med === null) t += es ? 'Ninguna cooperativa de crédito con sede en ' + name + ' informó una tasa.'"
    "   : 'No credit union based in ' + name + ' reported a rate.';"
    "  else t += (es ? 'Las cooperativas de crédito con sede en ' + name + ' ofrecían una mediana de ' + pct(med) + ' en préstamos para autos '"
    "   + (used ? 'usados' : 'nuevos') + ' (' + n + ' cooperativas)' + (n < 10 ? '; pocas informan aquí, así que tómalo con cuidado' : '')"
    "   : 'Credit unions based in ' + name + ' were offering a median of ' + pct(med) + ' on ' + (used ? 'used' : 'new')"
    "   + '-car loans (' + n + ' credit unions)' + (n < 10 ? '; few report here, so treat it with care' : '')) + '.';"
    "  out.textContent = t; });"
    # The printed link follows the page language, so it is rewritten when <html lang> changes, not only when empty.
    " new MutationObserver(() => { document.querySelectorAll('.mc-share-url').forEach(s => {"
    "  const u = location.origin + location.pathname + s.dataset.share"
    "   + (document.documentElement.lang === 'es' ? '&g=es' : ''); if (s.textContent !== u) s.textContent = u; });"
    "  document.querySelectorAll('.mc-code code').forEach(c => { if (c.textContent.includes('https://YOUR-SPACE.hf.space'))"
    "   c.textContent = c.textContent.split('https://YOUR-SPACE.hf.space').join(location.origin); }); })"
    "  .observe(document.documentElement, {childList: true, subtree: true, attributes: true, attributeFilter: ['lang']});"
    " document.addEventListener('click', e => { if (!e.target.closest) return;"
    "  if (e.target.closest('.mc-print')) { document.body.classList.add('mc-printing-card'); window.print();"
    "   setTimeout(() => document.body.classList.remove('mc-printing-card'), 500); return; }"
    "  if (e.target.closest('.mc-print-sheet')) { document.body.classList.add('mc-printing-sheet'); window.print();"
    "   setTimeout(() => document.body.classList.remove('mc-printing-sheet'), 500); return; }"
    "  const jl = e.target.closest('.mc-jump a'); if (jl) { e.preventDefault();"
    "   const to = document.getElementById(jl.getAttribute('href').slice(1)); if (to) to.scrollIntoView({behavior:"
    "   matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start'}); return; }"
    "  const qt = e.target.closest('.mc-copy-text'); if (qt) { const sec = qt.closest('section');"
    "   const text = sec.querySelector('.mc-quote-text').textContent; const out = sec.querySelector('.mc-copy-status');"
    "   const ok = document.documentElement.lang === 'es' ? 'Mensaje copiado.' : 'Message copied.';"
    "   if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => { out.textContent = ok; },"
    "    () => { out.textContent = text; }); else out.textContent = text; return; }"
    "  const b = e.target.closest('.mc-copy'); if (!b) return;"
    "  const url = location.origin + location.pathname + b.dataset.share + (document.documentElement.lang === 'es' ? '&g=es' : '');"
    "  const out = b.parentElement.querySelector('.mc-copy-status');"
    "  const show = () => { out.textContent = url; };"
    "  const done = document.documentElement.lang === 'es' ? 'Enlace copiado.' : 'Link copied.';"
    "  if (navigator.clipboard) navigator.clipboard.writeText(url).then(() => { out.textContent = done; }, show); else show(); });"
    "})();</script>"
    # A check needs the server, so when the connection drops the page says so: a result already on screen is
    # still the last one the server sent, and a new check won't run until the connection is back.
    "<script>(() => { if (window.__mcNet) return; window.__mcNet = 1;"
    " const show = () => { let b = document.getElementById('mc-offline');"
    "  if (!b) { b = document.createElement('div'); b.id = 'mc-offline'; b.setAttribute('role', 'alert');"
    "   document.body.appendChild(b); }"
    "  b.textContent = document.documentElement.lang === 'es'"
    "   ? 'Estás sin conexión. Una revisión nueva no se hará hasta que vuelvas a conectarte; lo que ves es el último resultado.'"
    "   : \"You're offline. A new check won't run until you reconnect; what you see is the last result.\";"
    "  b.hidden = false; };"
    " window.addEventListener('offline', show);"
    " window.addEventListener('online', () => { const b = document.getElementById('mc-offline'); if (b) b.hidden = true; });"
    " if (navigator.onLine === false) { if (document.body) show(); else document.addEventListener('DOMContentLoaded', show); }"
    " })();</script>"
) + PARTNER_JS

FOOTER = (
    "<footer><p class='mc-note'><strong>Privacy.</strong> MarkupCheck doesn't keep your offer: nothing you type is "
    "saved on our server or in your browser. A shared link carries your numbers after the # sign, which browsers "
    "don't send to our server. Batch files are deleted within an hour. To limit misuse, the server counts checks "
    "from each IP address for one minute.</p>"
    "<p class='mc-note'><strong>Who pays.</strong> Nobody. MarkupCheck has no sponsors, ads or referral fees, so "
    "nothing pays it to send you to a lender.</p>"
    "<p class='mc-note'><strong>Accessibility.</strong> The pages are checked automatically for keyboard use, text "
    "contrast of at least 4.5 to 1, 44-pixel touch targets, and screen-reader labels and announcements, at phone, "
    "tablet and desktop widths, in English and Spanish. They haven't yet been tested by a person using a screen "
    "reader.</p>"
    f"<p>{DISCLAIMER}</p></footer>"
)

API_DOCS = (
    "<div class='mc-result'><section class='mc-section mc-first'><h2 class='mc-form-title'>Use MarkupCheck from your own "
    "program</h2><p>The same check is available as an API named <code>check</code>. Send the APR, or leave it empty "
    "and send the monthly payment. You get back JSON with the verdict, the range, the typical APR, each lender, "
    "the checks and the credit-union average.</p>"
    "<h3>Python</h3><pre class='mc-code'><code>pip install gradio_client\n\n"
    "from gradio_client import Client\n"
    "client = Client(\"https://YOUR-SPACE.hf.space\")  # this page's address\n"
    "result = client.predict(660, \"used\", 2019, 17500, 18500, 72, 15.9, \"\", None,\n"
    "                        api_name=\"/check\")\n"
    "print(result[\"verdict\"], result[\"result\"][\"typical_pct\"])</code></pre>"
    "<h3>Any language (two HTTP calls)</h3><pre class='mc-code'><code>curl -X POST https://YOUR-SPACE.hf.space/gradio_api/call/check \\\n"
    "  -H \"Content-Type: application/json\" \\\n"
    "  -d '{\"data\": [660, \"used\", 2019, 17500, 18500, 72, 15.9, \"\", null]}'\n"
    "# returns {\"event_id\": \"...\"}; then read the result:\n"
    "curl -N https://YOUR-SPACE.hf.space/gradio_api/call/check/EVENT_ID</code></pre>"
    "<h3>Inputs, in order</h3><ol class='mc-list'><li>credit score (250 to 900)</li><li>\"new\" or \"used\"</li>"
    "<li>model year</li><li>vehicle price ($)</li><li>amount financed ($)</li><li>term (months, 12 to 96)</li>"
    "<li>APR (%), or empty</li><li>lender name, or empty</li><li>monthly payment ($), or empty</li></ol>"
    "<p class='mc-note'>Limits: 30 checks a minute from one IP address. Nothing you send is stored. The results "
    "come with the same caveats as the page: MarkupCheck is a student prototype, not financial advice.</p>"
    "</section></div>"
)

# After a check, bring the top of the result (the verdict) into view if it isn't already; no animation when the
# visitor asked for reduced motion.
SHOW_VERDICT_JS = (
    "() => { const p = document.getElementById('mc-result-panel'); if (!p) return;"
    " const r = p.getBoundingClientRect(); if (r.top >= 0 && r.top < window.innerHeight * 0.5) return;"
    " const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;"
    " p.scrollIntoView({behavior: calm ? 'auto' : 'smooth', block: 'start'}); }"
)

# A shared link carries the offer after the #; demo.load runs this to fill the form (browsers never send the # part).
LOAD_FROM_LINK_JS = (
    "() => { const h = new URLSearchParams((location.hash || '').slice(1)); const g = k => h.get(k) || '';"
    " if (!h.has('s')) return ['', null, '', '', '', '', '', '', '', ''];"
    " return [g('s'), g('k') || null, g('y'), g('p'), g('a'), g('t'), g('r'), g('l'), g('m'), g('o')]; }"
)
# Then, only for a shared link, press "Check my rate" from the page itself: an ordinary visit makes no server call
# (each call counts against the rate limit).
RUN_FROM_LINK_JS = (
    "() => { const h = new URLSearchParams((location.hash || '').slice(1)); if (!h.has('s')) return;"
    " setTimeout(() => { const es = h.get('g') === 'es' && [...document.querySelectorAll('#mc-lang label')]"
    "  .find(l => l.textContent.trim() === 'Español');"
    # Switching the language re-runs the check for the filled form, so one server call either way.
    "  if (es) { es.querySelector('input').click(); return; }"
    "  const b = document.getElementById('mc-check'); if (b) b.click(); }, 50); }"
)

CSS = f"""
/* ---- headings and screen-reader text (page-level rules are in PAGE_CSS, in the head) */
h1, h2, h3 {{ text-wrap: balance; }}
.sr-only {{ position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden;
  clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }}

/* ---- skip link (.skip-to-content) */
.skip-to-content {{ position: absolute; left: -9999px; top: auto; width: 1px; height: 1px; overflow: hidden; }}
.skip-to-content:focus {{ position: fixed; top: 0.75rem; left: 1rem; width: auto; height: auto; overflow: visible;
  z-index: 9999; padding: 0.5rem 0.875rem; border-radius: 0.5rem; background: {TEXT}; color: #ffffff;
  font-size: 13px; font-weight: 600; text-decoration: none; outline: 2px solid {ACCENT}; outline-offset: 2px; }}

/* ---- header: eyebrow, h1 with a Lora italic accent, lede */
#mc-header {{ padding: 0 0 8px; }}
#mc-header .mc-eyebrow {{ font-size: 11px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase;
  color: {BRAND_TEXT}; margin: 0 0 12px; }}
#mc-header h1 {{ font-size: clamp(38px, 5vw, 56px); font-weight: 800; letter-spacing: -0.02em; line-height: 1.2;
  margin: 0 0 12px; color: {TEXT}; }}
#mc-header h1 em {{ font-family: {SERIF}; font-style: italic; font-weight: 700; color: {BRAND_DARK}; }}
#mc-header .mc-lede {{ margin: 0; max-width: 640px; color: {SECONDARY}; font-size: 17px; line-height: 1.7; }}

/* ---- glass cards (.card): 45% white, 12px blur, hairline border, 14px radius, 24px padding */
#mc-form, #mc-result-col {{ background: rgba(255, 255, 255, 0.45); -webkit-backdrop-filter: blur(12px);
  backdrop-filter: blur(12px); border: 1px solid rgba(0, 0, 0, 0.06); border-radius: 14px; box-shadow: {SHADOW_SM};
  padding: 24px !important; }}
@media (max-width: 768px) {{
  #mc-main {{ flex-direction: column !important; }}
  #mc-main > * {{ width: 100% !important; min-width: 0 !important; }}
}}

/* ---- form: card title (.dl-section-title), labels, helper lines, fields */
.mc-form-title {{ font-size: 22px; font-weight: 700; letter-spacing: -0.03em; line-height: 1.2; margin: 0 0 4px; }}
#mc-form .form {{ border: none !important; box-shadow: none !important; background: transparent !important; }}
/* The card supplies the side padding, so Gradio's own would only squeeze New/Used onto two lines. */
#mc-form .block, #mc-form .html-container, #mc-result-col .html-container {{ padding-left: 0 !important;
  padding-right: 0 !important; }}
/* Gradio wraps each pair of fields in one .form; the 12px gap goes there. */
.mc-pair, .mc-pair > .form {{ gap: 12px !important; flex-wrap: wrap; align-items: flex-end !important; }}
.mc-pair .block {{ min-width: 140px !important; }}
#mc-form [data-testid="block-info"] {{ font-size: 12px; font-weight: 600; letter-spacing: 0.06em;
  text-transform: uppercase; color: {SECONDARY}; transition: color 200ms {EASE}; }}
#mc-form label:focus-within [data-testid="block-info"] {{ color: {BRAND_TEXT}; }}
/* Same height for every helper line, so the two inputs in a pair line up. */
#mc-form .info-text {{ font-size: 12px; line-height: 1.5; color: {MUTED}; min-height: 3em; }}
/* 44px tall fields: the touch-target floor. */
#mc-form textarea, #mc-form input[type=text] {{ min-height: 44px; transition: all 0.25s {EASE_OUT}; }}
#mc-form textarea:focus, #mc-form input[type=text]:focus {{ transform: translateY(-1px); }}
#mc-form textarea:focus::placeholder {{ opacity: 0.6; }}
#mc-form [aria-invalid="true"] {{ border-color: rgba(220, 38, 38, 0.4) !important;
  background: rgba(254, 226, 226, 0.15) !important; }}
#mc-form [aria-invalid="true"]:focus {{ border-color: {ERROR} !important;
  box-shadow: 0 0 0 4px rgba(220, 38, 38, 0.1) !important; }}
#mc-form label:has(input[type=radio][aria-invalid="true"]) {{ border-color: rgba(220, 38, 38, 0.4) !important; }}
/* New / Used: AdmitPath's option card (10px radius; brand border and a 2px ring when chosen). */
#mc-form label:has(input[type=radio]) {{ border-radius: 10px !important; min-height: 44px;
  transition: border-color 200ms {EASE}, background 200ms {EASE}, box-shadow 200ms {EASE}; }}
#mc-form label:has(input[type=radio]:checked) {{ box-shadow: 0 0 0 2px rgba(74, 111, 165, 0.25) !important; }}
#mc-form input[type=radio] {{ accent-color: {ACCENT}; }}
input[type=number]::-webkit-outer-spin-button, input[type=number]::-webkit-inner-spin-button {{
  -webkit-appearance: none; margin: 0; }}
input[type=number] {{ -moz-appearance: textfield; }}

/* ---- buttons (.dl-btn): 200ms standard ease, press scale, 2px focus ring */
button {{ letter-spacing: -0.01em; transition: background 200ms {EASE}, border-color 200ms {EASE},
  box-shadow 200ms {EASE}, color 200ms {EASE}, transform 200ms {EASE}, filter 200ms {EASE}; }}
button:active:not(:disabled) {{ transform: scale(0.97); transition: transform 80ms ease; }}
button:disabled {{ opacity: 0.5; cursor: not-allowed; }}
*:focus-visible {{ outline: 2px solid {ACCENT} !important; outline-offset: 2px; }}
/* Check my rate: .dl-btn-primary at the -lg size, with its shimmer and arrow. */
#mc-check {{ position: relative; overflow: hidden; padding: 12px 28px; margin-top: 8px; min-height: 48px;
  font-size: 15px; font-weight: 600; line-height: 1; border: none;
  box-shadow: 0 1px 3px rgba(74,111,165,0.3), 0 1px 2px rgba(74,111,165,0.2) !important; }}
#mc-check:hover:not(:disabled) {{ transform: translateY(-2px); filter: brightness(1.05);
  box-shadow: 0 4px 12px rgba(74,111,165,0.4), 0 2px 4px rgba(74,111,165,0.2) !important; }}
#mc-check:active:not(:disabled) {{ transform: translateY(0) scale(0.98); filter: none;
  box-shadow: 0 1px 2px rgba(74,111,165,0.3) !important; }}
#mc-check::before {{ content: ""; position: absolute; inset: 0; pointer-events: none; transform: translateX(-100%);
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent);
  animation: mc-shimmer 4s ease-in-out infinite; }}
#mc-check::after {{ content: "\\2192" / ""; display: inline-block; margin-left: 7px;
  transition: transform 200ms {EASE}; }}
#mc-check:hover::after {{ transform: translate3d(2px, 0, 0); }}
@keyframes mc-shimmer {{ 0% {{ transform: translateX(-100%); }} 25% {{ transform: translateX(100%); }}
  100% {{ transform: translateX(100%); }} }}
/* Examples: .dl-btn-secondary. */
.mc-examples-label {{ margin: 12px 0 0; font-size: 12px; color: {MUTED}; }}
.mc-examples {{ gap: 8px !important; flex-wrap: wrap; margin-top: 4px; }}
.mc-examples button {{ min-height: 44px; padding: 9px 18px; font-size: 14px; font-weight: 600;
  border-width: 1.5px !important; -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px); }}
.mc-examples button:hover:not(:disabled) {{ transform: translateY(-1px); box-shadow: 0 2px 8px rgba(74,111,165,0.12) !important; }}

/* ---- result */
@keyframes mc-rise {{ from {{ transform: translateY(12px); }} to {{ transform: none; }} }}
@keyframes mc-scale-in {{ from {{ transform: scale(0.92); }} to {{ transform: none; }} }}
.mc-result {{ color: {TEXT}; font-size: 15px; line-height: 1.7; }}
/* Sections rise in 40ms apart (capped at 200ms) but are never transparent, so text reads from the first frame. */
.mc-result > * {{ animation: mc-rise 500ms {EASE_OUT} both; }}
.mc-result > :nth-child(2) {{ animation-delay: 40ms; }}
.mc-result > :nth-child(3) {{ animation-delay: 80ms; }}
.mc-result > :nth-child(4) {{ animation-delay: 120ms; }}
.mc-result > :nth-child(5) {{ animation-delay: 160ms; }}
.mc-result > :nth-child(n+6) {{ animation-delay: 200ms; }}
.mc-result h2, .mc-result h3 {{ font-style: normal; letter-spacing: -0.02em; }}
.mc-result h3 {{ font-size: 18px; font-weight: 600; line-height: 1.2; margin: 0 0 8px; }}
.mc-section {{ border-top: 1px solid rgba(0, 0, 0, 0.06); padding: 16px 0; }}
/* .dl-alert-info */
.mc-banner {{ padding: 12px 16px; border-radius: 10px; background: rgba(74, 111, 165, 0.08);
  border: 1px solid rgba(74, 111, 165, 0.2); color: {BRAND_DARK}; font-size: 13.5px; font-weight: 500; margin-bottom: 16px; }}
.mc-view {{ font-size: 12px; color: {MUTED}; margin: 0 0 4px; }}
.mc-headline {{ font-size: 18px; font-weight: 600; line-height: 1.3; margin: 4px 0 16px; }}
.mc-market {{ font-size: 13.5px; margin: -8px 0 16px; }}
/* The percentile is the page's stat: AdmitPath's mono stat style, at a larger size. */
.mc-percent {{ display: block; font-family: {MONO_CSS}; font-size: 64px; line-height: 1.05; font-weight: 700;
  letter-spacing: -0.02em; color: {BRAND_TEXT}; margin: 4px 0; font-variant-numeric: tabular-nums; }}

.mc-bar {{ position: relative; padding: 28px 0 24px; }}
/* Track: AdmitPath's progress track. The blue range border keeps 3:1+ against it. */
.mc-track {{ position: relative; height: 14px; background: rgba(0, 0, 0, 0.06); border-radius: 999px;
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.05); }}
.mc-range {{ position: absolute; top: 0; bottom: 0; background: rgba(74, 111, 165, 0.22); border: 2px solid {ACCENT};
  box-sizing: border-box; border-radius: 999px; }}
.mc-typical {{ position: absolute; top: -4px; bottom: -4px; width: 2px; margin-left: -1px; background: {ACCENT}; }}
.mc-marker {{ position: absolute; top: -8px; bottom: -8px; width: 4px; margin-left: -2px; border-radius: 2px;
  background: {TEXT}; }}
.mc-marker-label {{ position: absolute; top: 0; white-space: nowrap; font-size: 14px; font-weight: 700; }}
.mc-label-end {{ transform: translateX(-100%); padding-right: 6px; }}
.mc-label-start {{ margin-left: -2px; }}
.mc-scale {{ position: relative; height: 20px; margin-top: 8px; font-size: 12px; color: {MUTED};
  font-variant-numeric: tabular-nums; }}
.mc-scale span {{ position: absolute; top: 0; white-space: nowrap; }}
.mc-scale .mc-label-end {{ padding-right: 4px; }}
.mc-scale .mc-label-start {{ margin-left: 0; padding-left: 4px; }}
.mc-caption {{ font-size: 15px; margin: 0; }}

/* .dl-table: glass wrap, 11px uppercase headers, 13.5px cells, row hover, no border on the last row */
.mc-result .mc-table {{ width: 100%; border-collapse: separate !important; border-spacing: 0; margin: 0 0 8px;
  background: rgba(255, 255, 255, 0.65) !important; border: 1px solid rgba(0, 0, 0, 0.06) !important;
  border-radius: 14px; overflow: hidden; box-shadow: {SHADOW_SM}; }}
.mc-result .mc-table tr {{ background: transparent !important; border: none !important; }}
.mc-result .mc-table th, .mc-result .mc-table td {{ text-align: left; padding: 12px 16px;
  font-size: 13.5px; line-height: 1.5; border: none !important; border-bottom: 1px solid rgba(0, 0, 0, 0.06) !important;
  background: transparent !important; font-variant-numeric: tabular-nums; }}
.mc-result .mc-table td {{ color: {SECONDARY}; }}
.mc-result .mc-table thead th {{ padding: 10px 16px; font-size: 11px; font-weight: 700; letter-spacing: 0.07em;
  text-transform: uppercase; color: {MUTED}; background: rgba(0, 0, 0, 0.02) !important; }}
.mc-result .mc-table tbody th {{ font-weight: 600; color: {TEXT}; }}
.mc-result .mc-table tbody tr:last-child th, .mc-result .mc-table tbody tr:last-child td {{
  border-bottom: none !important; }}
.mc-result .mc-table tbody tr:hover {{ background: rgba(74, 111, 165, 0.04) !important; }}
.mc-cost {{ font-size: 17px; margin: 8px 0 0; }}

/* Small verdict chips in the lender table and the checks. */
.mc-chip {{ display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 700;
  line-height: 1.6; border: 1px solid transparent; white-space: nowrap; }}
.mc-chip.mc-flag-typical {{ background: {PRIMARY_LIGHT}; border-color: {PRIMARY_BORDER}; color: {BRAND_TEXT}; }}
.mc-chip.mc-flag-high {{ background: {SECONDARY}; color: #ffffff; }}
.mc-chip.mc-flag-marked {{ background: {ERROR}; color: #ffffff; }}
.mc-section-intro {{ font-size: 13.5px; color: {SECONDARY}; margin: 0 0 8px; }}
.mc-yours {{ display: inline-block; margin-left: 6px; padding: 0 8px; border-radius: 999px; font-size: 11px;
  font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; background: {PRIMARY_LIGHT}; color: {BRAND_TEXT}; }}
.mc-sub {{ display: block; font-size: 12px; font-weight: 400; color: {MUTED}; }}
.mc-result .mc-table tbody tr.mc-row-yours {{ background: rgba(74, 111, 165, 0.06) !important; }}
.mc-check-summary {{ margin: 0 0 8px; }}
.mc-checks {{ margin: 0 0 12px; padding-left: 20px; }}
.mc-checks li {{ margin: 6px 0; }}
.mc-check-q {{ color: {SECONDARY}; }}
/* Verdict flags as badges: brand badge for typical, solid secondary for high, solid error for well above. */
.mc-flag {{ display: inline-flex; align-items: center; padding: 4px 14px; border-radius: 999px; font-size: 20px;
  font-weight: 700; letter-spacing: -0.01em; border: 1px solid transparent; animation: mc-scale-in 0.3s {EASE_OUT}; }}
.mc-flag-typical {{ background: {PRIMARY_LIGHT}; border-color: {PRIMARY_BORDER}; color: {BRAND_TEXT}; }}
.mc-flag-high {{ background: {SECONDARY}; color: #ffffff; }}
.mc-flag-marked {{ background: {ERROR}; color: #ffffff; }}
/* The verdict box: AdmitPath's .aside 3px left rule, on a raised white surface. */
.mc-verdict {{ border-left: 3px solid rgba(0, 0, 0, 0.09); background: #ffffff; padding: 12px 16px;
  margin: 4px 0 20px; border-radius: 0 10px 10px 0; box-shadow: {SHADOW_SM}; }}
.mc-verdict .mc-verdict-name {{ font-size: 20px; margin: 0; }}
.mc-verdict p {{ margin: 6px 0 0; }}
.mc-verdict-mc-flag-typical {{ border-left-color: {ACCENT}; }}
.mc-verdict-mc-flag-high {{ border-left-color: {SECONDARY}; }}
.mc-verdict-mc-flag-marked {{ border-left-color: {ERROR}; background: {ERROR_LIGHT}; }}
.mc-verdict-line {{ font-size: 17px; line-height: 1.6; }}
.mc-verdict-detail {{ font-size: 14px; line-height: 1.6; color: {TEXT}; }}

.mc-legend {{ font-size: 12px; color: {MUTED}; margin: 0 0 8px; }}
.mc-key {{ display: inline-block; width: 14px; height: 10px; margin: 0 6px 0 12px; vertical-align: baseline; }}
.mc-legend .mc-key:first-child {{ margin-left: 0; }}
.mc-key-range {{ background: rgba(74, 111, 165, 0.22); border: 2px solid {ACCENT}; box-sizing: border-box;
  border-radius: 999px; }}
.mc-key-typical {{ width: 3px; height: 12px; background: {ACCENT}; }}
.mc-key-offer {{ width: 4px; height: 14px; border-radius: 2px; background: {TEXT}; }}

.mc-list {{ margin: 0; padding-left: 20px; }}
.mc-list li {{ margin: 4px 0; }}
.mc-note {{ font-size: 13.5px; line-height: 1.6; margin: 12px 0 0; }}
.mc-disclaimer {{ border-top: 1px solid rgba(0, 0, 0, 0.06); padding-top: 16px; margin: 0; font-weight: 600; }}
/* .dl-alert-error, with #991B1B text (AdmitPath's #DC2626 is 3.1:1 on its tint). */
.mc-error {{ padding: 12px 16px; border-radius: 10px; background: rgba(220, 38, 38, 0.08);
  border: 1px solid rgba(220, 38, 38, 0.2); color: {ERROR_TEXT}; font-size: 14px; font-weight: 500; }}
.mc-error h3 {{ color: {ERROR_TEXT}; font-size: 15px; font-weight: 700; margin: 0 0 4px; }}
.mc-error ul {{ margin: 0; padding-left: 20px; }}
.mc-error code {{ font-family: {MONO_CSS}; font-weight: 700; }}
.mc-ref {{ margin: 8px 0 0; }}
/* .dl-empty */
.mc-empty {{ text-align: center; padding: 60px 32px; color: {MUTED}; }}
.mc-empty-icon {{ width: 52px; height: 52px; margin: 0 auto 18px; border-radius: 20px; display: flex;
  align-items: center; justify-content: center; background: rgba(74, 111, 165, 0.08); color: {ACCENT}; }}
.mc-empty h3 {{ font-size: 17px; font-weight: 600; letter-spacing: -0.02em; color: {TEXT}; margin: 0 0 6px; }}
.mc-empty p {{ font-size: 13.5px; line-height: 1.6; max-width: 340px; margin: 0 auto; }}

/* ---- language switch, top right */
#mc-topbar {{ justify-content: flex-end; margin: -8px 0 4px; }}
#mc-lang {{ flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; background: transparent !important; }}
#mc-lang .wrap {{ gap: 6px; }}
#mc-lang label {{ min-height: 44px; padding: 8px 14px !important; border-radius: 999px !important; font-size: 13.5px; }}

/* ---- tabs (AdmitPath's pill toggles) and the other tabs' cards */
#mc-tabs [role=tablist] {{ gap: 6px; border: none !important; flex-wrap: nowrap; margin-bottom: 16px; }}
#mc-tabs .tab-container:not(.visually-hidden) {{ height: auto !important; overflow: visible !important; padding: 2px 0; }}
#mc-tabs button[role=tab] {{ min-height: 44px; padding: 8px 16px; border-radius: 999px !important; font-size: 14px;
  font-weight: 600; color: {SECONDARY}; background: rgba(255, 255, 255, 0.6); border: 1px solid rgba(0, 0, 0, 0.09) !important; }}
#mc-tabs button[role=tab]:hover {{ color: {BRAND_TEXT}; border-color: {ACCENT} !important; }}
#mc-tabs button[role=tab][aria-selected=true] {{ background: {ACCENT}; color: #ffffff; border-color: {ACCENT} !important;
  box-shadow: 0 2px 6px rgba(74, 111, 165, 0.25) !important; }}
#mc-tabs button[role=tab]::after {{ display: none !important; }}
#mc-tabs .tabitem {{ border: none !important; padding: 0 !important; background: transparent !important; }}
.mc-panel {{ background: rgba(255, 255, 255, 0.45); -webkit-backdrop-filter: blur(12px); backdrop-filter: blur(12px);
  border: 1px solid rgba(0, 0, 0, 0.06); border-radius: 14px; box-shadow: {SHADOW_SM}; padding: 24px !important;
  max-width: 820px; }}
.mc-panel .block, .mc-panel .html-container {{ padding-left: 0 !important; padding-right: 0 !important; }}
.mc-panel .form {{ border: none !important; box-shadow: none !important; background: transparent !important; }}
.mc-panel [data-testid="block-info"] {{ font-size: 12px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase;
  color: {SECONDARY}; }}
.mc-panel textarea, .mc-panel input[type=text] {{ min-height: 44px; }}
.mc-go {{ margin-top: 8px; min-height: 48px; }}
.mc-first {{ border-top: none !important; padding-top: 0 !important; }}
.mc-result h4 {{ font-size: 15px; font-weight: 600; margin: 12px 0 8px; }}
.mc-code, .mc-code * {{ color: #F0F2F5 !important; }}
.mc-code {{ background: {TEXT}; border-radius: 10px; padding: 12px 14px; font-family: {MONO_CSS};
  font-size: 12.5px; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }}
/* Gradio's uploaded-file row: its download link and remove button get 44px targets. */
.mc-panel .file-preview a, .mc-panel .file-preview button {{ display: inline-flex; align-items: center; min-height: 44px; }}
.mc-panel .file-preview td {{ vertical-align: middle; }}
/* The file box's corner "Clear" icon is 44px too, so the file row starts below it instead of under it. */
.mc-panel .icon-button {{ min-width: 44px; min-height: 44px; justify-content: center; }}
.mc-panel .file-preview {{ margin-top: 48px; }}
.mc-result code {{ font-family: {MONO_CSS}; font-size: 0.9em; }}

#mc-form .block, .mc-panel .block {{ overflow: visible !important; }}
ul.options > li {{ min-height: 44px; display: flex; align-items: center; }}

/* ---- money features: charts, sliders, dealer card, questions */
/* Each chart comes twice: the wide one, and a compact one for phones. */
.mc-chart {{ display: block; }}
.mc-chart-narrow {{ display: none !important; }}
@media (max-width: 600px) {{ .mc-chart-wide {{ display: none !important; }} .mc-chart-narrow {{ display: block !important; }} }}
/* Gradio moves tabs that don't fit into a menu; its button gets a 44px target (and a name, from the page script). */
#mc-tabs .overflow-menu > button {{ min-width: 44px; min-height: 44px; border-radius: 999px; }}
#mc-tabs .overflow-dropdown button {{ min-height: 44px; padding: 8px 16px; text-align: left; }}
.mc-figure {{ margin: 12px 0 0; }}
.mc-figure svg {{ width: 100%; height: auto; }}
.mc-figure figcaption {{ margin-top: 4px; }}
.mc-derived {{ margin: -8px 0 12px; }}
.mc-whatif {{ margin-top: 12px; padding: 16px; border-radius: 14px; background: rgba(255, 255, 255, 0.65);
  border: 1px solid rgba(0, 0, 0, 0.06); box-shadow: {SHADOW_SM}; }}
.mc-whatif h4 {{ font-size: 15px; font-weight: 600; margin: 0 0 4px; }}
.mc-wi-row {{ display: block; margin: 4px 0 0; }}
.mc-wi-row > span {{ display: flex; justify-content: space-between; gap: 8px; font-size: 13.5px; color: {SECONDARY}; }}
.mc-wi-row output {{ font-weight: 700; color: {TEXT}; font-variant-numeric: tabular-nums; }}
.mc-whatif input[type=range] {{ width: 100%; min-height: 44px; margin: 0; accent-color: {ACCENT}; cursor: pointer; }}
.mc-wi-result {{ margin: 8px 0 0; }}
.mc-result .mc-card {{ background: #ffffff; border: 1px solid rgba(0, 0, 0, 0.06); border-radius: 14px;
  padding: 16px; margin: 16px 0; box-shadow: {SHADOW_SM}; }}
.mc-card-facts {{ margin: 0 0 8px; padding-left: 20px; }}
.mc-card-facts li {{ margin: 4px 0; }}
.mc-card-actions {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 8px; }}
.mc-btn {{ min-height: 44px; padding: 9px 18px; border-radius: 12px; font-size: 14px; font-weight: 600;
  background: rgba(255, 255, 255, 0.7); border: 1.5px solid rgba(0, 0, 0, 0.08); color: {TEXT}; cursor: pointer; }}
.mc-btn:hover {{ border-color: {ACCENT}; color: {BRAND_TEXT}; transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(74, 111, 165, 0.12) !important; }}
/* min-height does nothing on an inline element, so link-styled buttons (calendar file, CSV) need a box. */
a.mc-btn {{ display: inline-flex; align-items: center; text-decoration: none; }}
.mc-copy-status {{ font-size: 12px; color: {MUTED}; word-break: break-all; }}
.mc-share-url {{ word-break: break-all; }}
.mc-jump {{ display: flex; flex-wrap: wrap; gap: 4px 16px; margin: 8px 0 0; font-size: 14px; }}
.mc-jump a {{ display: inline-flex; align-items: center; min-height: 44px; color: {BRAND_TEXT}; }}
.mc-state-label {{ display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 8px; font-weight: 600; }}
.mc-state-select {{ min-height: 44px; min-width: 220px; padding: 0 10px; border: 1px solid {PRIMARY_BORDER};
  border-radius: 10px; background: #FFFFFF; color: {TEXT}; font: inherit; font-weight: 400; }}
.mc-state-out {{ margin: 8px 0 0; }}
.mc-pushback {{ margin: 8px 0 0; }}
.mc-pushback dt {{ font-weight: 600; margin-top: 12px; }}
.mc-pushback dd {{ margin: 4px 0 0; padding-left: 12px; border-left: 3px solid {PRIMARY_BORDER}; }}
.mc-quote-text {{ background: {SURFACE}; border: 1px solid {PRIMARY_BORDER}; border-radius: 10px; padding: 12px 14px;
  margin: 8px 0; }}
.mc-faq {{ border: 1px solid rgba(0, 0, 0, 0.06); border-radius: 10px; background: rgba(255, 255, 255, 0.5); margin: 8px 0; }}
.mc-faq summary {{ min-height: 44px; display: flex; align-items: center; padding: 8px 12px; font-weight: 600; cursor: pointer; }}
.mc-faq summary:hover {{ color: {BRAND_TEXT}; }}
.mc-faq[open] summary {{ color: {BRAND_TEXT}; }}
.mc-faq p {{ margin: 0; padding: 0 12px 12px; font-size: 14px; }}

/* ---- footer */
#mc-footer footer {{ border-top: 1px solid rgba(0, 0, 0, 0.06); margin-top: 24px; padding: 24px 0 8px;
  font-size: 13px; color: {MUTED}; }}
#mc-footer footer p {{ margin: 0; }}
/* Hide Gradio's own footer links (API, settings): they aren't part of the tool. */
footer:not(#mc-footer footer) {{ display: none !important; }}

/* ---- touch targets: 44px on coarse pointers and on phones */
@media (pointer: coarse) {{
  button, [role=button], select, summary, #mc-form label:has(input[type=radio]) {{ min-height: 44px; }}
}}
@media (max-width: 768px) {{ button {{ min-height: 44px; }} }}
@media (max-width: 600px) {{
  #mc-form, #mc-result-col, .mc-panel {{ padding: 16px !important; }}
  .mc-result .mc-table th, .mc-result .mc-table td {{ padding: 8px 4px; font-size: 12.5px; overflow-wrap: break-word;
    hyphens: auto; }}
  .mc-result .mc-table td {{ white-space: nowrap; }}
  .mc-result .mc-table thead th {{ letter-spacing: 0.02em; }}
  .mc-chip {{ white-space: normal; padding: 2px 6px; }}
  .mc-pair .block {{ min-width: 100% !important; }}
  .mc-percent {{ font-size: 48px; }}
}}

/* ---- reduced motion, forced colours, more contrast, print */
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ animation-duration: 0.001ms !important; animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important; scroll-behavior: auto !important; }}
  #mc-check::before {{ animation: none !important; display: none; }}
  #mc-check:hover, .mc-examples button:hover, #mc-form textarea:focus, #mc-form input:focus {{ transform: none !important; }}
}}
@media (forced-colors: active) {{
  #mc-form, #mc-result-col, .mc-table, .mc-verdict, .mc-error, .mc-banner, .mc-empty-icon, .mc-flag,
  #mc-form textarea, #mc-form input[type=text] {{ border: 1px solid ButtonText !important; }}
  button {{ border: 2px solid ButtonText !important; forced-color-adjust: none; }}
  *:focus-visible, .skip-to-content:focus {{ outline-color: Highlight !important; }}
  .mc-range, .mc-marker, .mc-typical {{ forced-color-adjust: none; }}
}}
@media (prefers-contrast: more) {{
  #mc-form, #mc-result-col {{ border: 2px solid rgba(0, 0, 0, 0.30); }}
  #mc-form textarea, #mc-form input[type=text] {{ border-color: rgba(0, 0, 0, 0.30) !important; }}
  #mc-form .info-text, .mc-view, .mc-legend, .mc-scale, .mc-examples-label, .mc-empty, #mc-footer footer,
  .mc-result .mc-table thead th {{ color: #3D4355 !important; }}
}}
@media print {{
  #mc-form, .skip-to-content, #mc-live {{ display: none !important; }}
  #mc-main {{ display: block !important; }}
  #mc-result-col {{ background: #ffffff !important; border: none !important; box-shadow: none !important;
    -webkit-backdrop-filter: none; backdrop-filter: none; padding: 0 !important; width: 100% !important; }}
  * {{ box-shadow: none !important; animation: none !important; }}
  .mc-result, .mc-result h3, #mc-header h1 {{ color: #000000 !important; }}
  .mc-section, .mc-verdict, .mc-table {{ break-inside: avoid; }}
}}
"""


def build_demo() -> gr.Blocks:
    # delete_cache: every 5 minutes, uploads and results in Gradio's cache older than 50 minutes are removed, so
    # none stays past an hour (the page's promise).
    with gr.Blocks(title=TITLE, analytics_enabled=False, delete_cache=(300, 3000)) as demo:
        gr.HTML(
            "<a class='skip-to-content' href='#mc-main'>Skip to main content</a>"
            "<p class='mc-eyebrow'>Built on public SEC loan data</p>"
            f"<h1>{TITLE.replace(' fair?', ' <em>fair?</em>')}</h1>"
            "<p class='mc-lede'>Enter the loan offer from the dealer. MarkupCheck compares its APR with real car loans "
            "that lenders disclosed in public SEC filings, for borrowers with similar credit, cars and loan terms.</p>",
            elem_id="mc-header",
        )
        # After the header, so the skip link stays the first thing a keyboard reaches.
        with gr.Row(elem_id="mc-topbar"):
            lang = gr.Radio(i18n.LANGS, value="en", label="Language / Idioma", show_label=False, container=False,
                            elem_id="mc-lang")
        with gr.Tabs(elem_id="mc-tabs"):
          with gr.Tab("Check an offer", id="check"):
            with gr.Row(elem_id="mc-main", equal_height=False):
              with gr.Column(scale=5, min_width=300, elem_id="mc-form"):
                    gr.HTML("<h2 class='mc-form-title'>Your loan offer</h2>")
                    gr.HTML("<p class='mc-examples-label'>Try an example, or enter your own offer below:</p>")
                    with gr.Row(elem_classes="mc-examples"):
                        example_btn = gr.Button("Jordan: a fair rate", variant="secondary")
                        sam_btn = gr.Button("Sam: a rate well above similar loans", variant="secondary")
                    with gr.Row(elem_classes="mc-pair"):
                        credit_score = gr.Textbox(label=L_SCORE, lines=1, max_lines=1, elem_classes="mc-num", placeholder="e.g. 660",
                                                 info="Auto-lender FICO scores run 250 to 900.")
                        new_or_used = gr.Radio([("New", "new"), ("Used", "used")], label=L_KIND, info="As listed on the contract.")
                    with gr.Row(elem_classes="mc-pair"):
                        vehicle_model_year = gr.Textbox(label=L_YEAR, lines=1, max_lines=1, elem_classes="mc-num", placeholder="e.g. 2019",
                                                        info="On the window sticker or contract.")
                        vehicle_price = gr.Textbox(label=L_PRICE, lines=1, max_lines=1, elem_classes="mc-num", placeholder="e.g. 17500",
                                                  info="Agreed price, before taxes and fees.")
                    with gr.Row(elem_classes="mc-pair"):
                        amount_financed = gr.Textbox(label=L_FINANCED, lines=1, max_lines=1, elem_classes="mc-num", placeholder="e.g. 18500",
                                                    info="From the contract, incl. fees and add-ons.")
                        term_months = gr.Textbox(label=L_TERM, lines=1, max_lines=1, elem_classes="mc-num", placeholder="e.g. 72",
                                                 info="How many monthly payments.")
                    with gr.Row(elem_classes="mc-pair"):
                        offered_apr_pct = gr.Textbox(label=L_APR, lines=1, max_lines=1, elem_classes="mc-num", placeholder="e.g. 15.9",
                                                     info="The APR, not the payment. Blank if you only know the payment.")
                        lender = gr.Textbox(label=L_LENDER, placeholder="e.g. Santander",
                                            info="Naming one of the 10 lenders in the data gives a sharper check.", lines=1, max_lines=1)
                    with gr.Row(elem_classes="mc-pair"):
                        payment = gr.Textbox(label=L_PAYMENT, lines=1, max_lines=1, elem_classes="mc-num", placeholder="e.g. 400",
                                             info="From the contract or quote. We check it against the APR.")
                        addons = gr.Textbox(label=L_ADDONS, lines=1, max_lines=1, elem_classes="mc-num", placeholder="e.g. 2500",
                                            info="Warranty, GAP and similar items, if you know them.")
                    check_btn = gr.Button("Check my rate", variant="primary", elem_id="mc-check")
                    with gr.Accordion("Have the contract? Check its Truth-in-Lending box", open=False, elem_id="mc-tila"):
                        gr.HTML("<p class='mc-note'>Federal rules require a car-loan contract to group these numbers "
                                "together, usually in a box near the top. Type them as printed.</p>")
                        with gr.Row(elem_classes="mc-pair"):
                            tl_amount = gr.Textbox(label="Amount Financed ($)", placeholder="e.g. 18500", lines=1,
                                                   max_lines=1, elem_classes="mc-num")
                            tl_charge = gr.Textbox(label="Finance Charge ($)", placeholder="e.g. 10320", lines=1,
                                                   max_lines=1, elem_classes="mc-num")
                        with gr.Row(elem_classes="mc-pair"):
                            tl_total = gr.Textbox(label="Total of Payments ($)", placeholder="e.g. 28820", lines=1,
                                                  max_lines=1, elem_classes="mc-num")
                            tl_n = gr.Textbox(label="Number of payments", placeholder="e.g. 72", lines=1, max_lines=1,
                                              elem_classes="mc-num")
                        with gr.Row(elem_classes="mc-pair"):
                            tl_apr = gr.Textbox(label="Annual Percentage Rate (%)", placeholder="e.g. 15.9", lines=1,
                                                max_lines=1, elem_classes="mc-num")
                        tl_btn = gr.Button("Check the box", variant="secondary")
                        tl_out = gr.HTML(elem_id="mc-tila-panel")
              with gr.Column(scale=7, min_width=300, elem_id="mc-result-col"):
                    result = gr.HTML(render_empty(), elem_id="mc-result-panel")

          with gr.Tab("Compare offers", id="compare"):
            with gr.Column(elem_classes="mc-panel", elem_id="mc-compare-form"):
                gr.HTML("<h2 class='mc-form-title'>Compare up to three offers</h2><p class='mc-section-intro'>Uses the "
                        "credit score, car and amount financed from <strong>Check an offer</strong>. Add each quote "
                        "you have, for example the dealer's and a credit union's.</p>")
                offer_boxes = []
                for i, (name_hint, apr_hint) in enumerate([("Dealer", "15.9"), ("Credit union", "9.5"), ("Bank", "11")], 1):
                    with gr.Row(elem_classes="mc-pair"):
                        offer_boxes += [
                            gr.Textbox(label=f"Offer {i} name", placeholder=f"e.g. {name_hint}", lines=1, max_lines=1),
                            gr.Textbox(label=f"Offer {i} APR (%)", placeholder=f"e.g. {apr_hint}", lines=1, max_lines=1,
                                       elem_classes="mc-num"),
                            gr.Textbox(label=f"Offer {i} term (months)", placeholder="e.g. 60", lines=1, max_lines=1,
                                       elem_classes="mc-num")]
                compare_btn = gr.Button("Compare offers", variant="primary", elem_classes="mc-go")
                compare_out = gr.HTML(elem_id="mc-compare-panel")
          with gr.Tab("Refinance", id="refinance"):
            with gr.Column(elem_classes="mc-panel", elem_id="mc-refi-form"):
                gr.HTML("<h2 class='mc-form-title'>Already have a car loan?</h2><p class='mc-section-intro'>See how "
                        "your current rate compares with similar loans, and what a lower rate could save.</p>")
                with gr.Row(elem_classes="mc-pair"):
                    rf_score = gr.Textbox(label="Credit score now", placeholder="e.g. 680", lines=1, max_lines=1, elem_classes="mc-num")
                    rf_year = gr.Textbox(label="Car's model year", placeholder="e.g. 2021", lines=1, max_lines=1, elem_classes="mc-num")
                with gr.Row(elem_classes="mc-pair"):
                    rf_balance = gr.Textbox(label="Balance left ($)", placeholder="e.g. 14000", lines=1, max_lines=1, elem_classes="mc-num")
                    rf_apr = gr.Textbox(label="Current APR (%)", placeholder="e.g. 15.9", lines=1, max_lines=1, elem_classes="mc-num")
                with gr.Row(elem_classes="mc-pair"):
                    rf_months = gr.Textbox(label="Months left", placeholder="e.g. 48", lines=1, max_lines=1, elem_classes="mc-num")
                    rf_value = gr.Textbox(label="Car's value now ($, optional)", placeholder="e.g. 16000", lines=1,
                                          max_lines=1, elem_classes="mc-num")
                with gr.Row(elem_classes="mc-pair"):
                    rf_offer = gr.Textbox(label="Rate a lender offered you (%, optional)", placeholder="e.g. 9.5",
                                          lines=1, max_lines=1, elem_classes="mc-num")
                refi_btn = gr.Button("Check refinancing", variant="primary", elem_classes="mc-go")
                refi_out = gr.HTML(elem_id="mc-refi-panel")
          with gr.Tab("Batch check", id="batch"):
            with gr.Column(elem_classes="mc-panel"):
                gr.HTML("<h2 class='mc-form-title'>Check many loans at once</h2><p class='mc-section-intro'>For credit "
                        "counselors, legal aid and researchers: upload a CSV with one loan per row (up to 500). Start "
                        "from the template. Files are used only for this check and deleted within an hour.</p>")
                gr.DownloadButton("Download the CSV template", value=str(APP_DIR / "batch_template.csv"),
                                  variant="secondary", elem_classes="mc-go")
                batch_file = gr.File(label="Your CSV file", file_types=[".csv"], file_count="single")
                batch_btn = gr.Button("Check every row", variant="primary", elem_classes="mc-go")
                batch_out = gr.HTML(elem_id="mc-batch-panel")
                batch_download = gr.File(label="Results (CSV)", interactive=False)
          with gr.Tab("Explore the data", id="explore"):
            with gr.Column(elem_classes="mc-panel"):
                gr.HTML(explore.states_html())
                with gr.Row(elem_classes="mc-pair"):
                    trk_tier = gr.Dropdown([(v, k) for k, v in explore.TIER_LABELS.items()], value="prime",
                                           label="Credit tier")
                    trk_kind = gr.Radio([("New", "new"), ("Used", "used")], value="used", label="New or used")
                trk_out = gr.HTML(explore.tracker_html("prime", "used"))
          with gr.Tab("For teachers", id="teach"):
            with gr.Column(elem_classes="mc-panel"):
                gr.HTML(teacher.teacher_html())
          with gr.Tab("Use the API", id="api"):
            with gr.Column(elem_classes="mc-panel"):
                gr.HTML(API_DOCS)

        gr.HTML(FOOTER, elem_id="mc-footer")

        inputs = [credit_score, new_or_used, vehicle_model_year, vehicle_price,
                  amount_financed, term_months, offered_apr_pct, lender, payment, addons]

        def in_lang(fn):
            """Run fn on every input but the last (the language) and translate its HTML for that language."""
            def run(*args):
                try:
                    out = fn(*args[:-1])
                except Exception as exc:
                    ref = _log_error(getattr(fn, "__name__", "handler"), exc)
                    out = render_errors([(None, "Something went wrong on our side, not with your entries. Try "
                                                "again in a moment.")], heading="We couldn't check this", ref=ref)
                    if fn is batch_handler:
                        out = (out, None)
                if isinstance(out, tuple):
                    return (i18n.translate_html(out[0], args[-1]), *out[1:])
                return i18n.translate_html(out, args[-1]) if isinstance(out, str) else out
            return run

        # Gradio's default trigger_mode ("once") drops a click or Enter while a check is still running, so a quick
        # edit would leave the verdict showing the old inputs; "always_last" runs the newest one when the first ends.
        check_btn.click(in_lang(check_offer), inputs=inputs + [lang], outputs=result,
                        trigger_mode="always_last").then(None, js=SHOW_VERDICT_JS)
        for box in (credit_score, vehicle_model_year, vehicle_price, amount_financed, term_months, offered_apr_pct,
                    lender, payment, addons):
            box.submit(in_lang(check_offer), inputs=inputs + [lang], outputs=result,
                       trigger_mode="always_last").then(None, js=SHOW_VERDICT_JS)
        example_btn.click(lambda: (*jordan_example(), "", ""), inputs=None, outputs=inputs).then(
            in_lang(check_offer), inputs=inputs + [lang], outputs=result).then(None, js=SHOW_VERDICT_JS)
        sam_btn.click(lambda: (*sam_example(), "", ""), inputs=None, outputs=inputs).then(
            in_lang(check_offer), inputs=inputs + [lang], outputs=result).then(None, js=SHOW_VERDICT_JS)
        demo.load(None, None, inputs, js=LOAD_FROM_LINK_JS).then(None, js=RUN_FROM_LINK_JS)

        profile = [credit_score, new_or_used, vehicle_model_year, vehicle_price, amount_financed]
        compare_btn.click(in_lang(lambda *v: tabs.compare_offers(*v[:5], [tuple(v[5 + 3 * i: 8 + 3 * i]) for i in range(3)])),
                          inputs=profile + offer_boxes + [lang], outputs=compare_out, scroll_to_output=True,
                          trigger_mode="always_last")
        refi_btn.click(in_lang(tabs.refinance_check),
                       inputs=[rf_score, rf_year, rf_balance, rf_apr, rf_months, rf_value, rf_offer, lang],
                       outputs=refi_out, scroll_to_output=True, trigger_mode="always_last")
        batch_btn.click(in_lang(batch_handler), inputs=[batch_file, lang], outputs=[batch_out, batch_download])
        tl_btn.click(in_lang(tabs.contract_box_check), inputs=[tl_amount, tl_charge, tl_total, tl_n, tl_apr, lang],
                     outputs=tl_out, trigger_mode="always_last")
        for box in (trk_tier, trk_kind):
            box.change(in_lang(explore.tracker_html), inputs=[trk_tier, trk_kind, lang], outputs=trk_out)

        # Language switch: every fixed label, help line, placeholder, button, tab, choice and HTML block is kept
        # in English here and translated on each switch; results are re-run (check, tracker) or cleared (the rest).
        panels = [result, compare_out, refi_out, batch_out, batch_download, trk_out, tl_out]
        fixed = [b for b in demo.blocks.values() if b is not lang and all(b is not x for x in panels)
                 and isinstance(b, (gr.Textbox, gr.Radio, gr.Dropdown, gr.Button, gr.DownloadButton, gr.File,
                                    gr.HTML, gr.Tab, gr.Accordion))]
        english = [_english_props(b) for b in fixed]

        def set_language(lang_value, *form):
            ups = [gr.update(**_localized(props, lang_value)) for props in english]
            values, tier, kind = form[:10], form[10], form[11]
            main = check_offer(*values) if not all(_blank(v) for v in values) else render_empty()
            return [*ups, i18n.translate_html(main, lang_value), "", "", "", None,
                    i18n.translate_html(explore.tracker_html(tier, kind), lang_value), ""]

        lang.change(set_language, inputs=[lang, *inputs, trk_tier, trk_kind], outputs=fixed + panels)
        lang.change(None, inputs=lang, outputs=None,
                    js="(l) => { document.documentElement.lang = l; document.title = l === 'es' ? "
                       f"{json.dumps(i18n.t(TITLE, 'es'))} : {json.dumps(TITLE)}; }}")
        gr.api(check_api, api_name="check")
        # The page's own handlers stay callable (the page itself uses them) but out of the API docs, so the
        # documented API is only check. Set inside the Blocks context, before Gradio writes its config.
        for fn in demo.fns.values():
            if fn.api_name != "check" and fn.api_visibility == "public":
                fn.api_visibility = "undocumented"
    return demo


demo = build_demo()
markupcheck_model._load()  # load the 38 model files once at startup, not on the first visitor's click

# Fonts are served from the app itself, and every response gets the security headers and rate limit.
APP_KWARGS = {
    "routes": [Mount("/mc-fonts", app=StaticFiles(directory=FONT_DIR), name="mc-fonts")],
    "middleware": [Middleware(web_security.SecurityHeaders)],
}

# Gradio's run history is on by default: it keeps every check in the browser and lists it at /gradio_api/runs,
# so on a shared computer the next person could open the last buyer's offer. The page promises nothing is stored.
LAUNCH_KWARGS = dict(theme=THEME, css=CSS, head=HEAD, favicon_path=str(FAVICON), app_kwargs=APP_KWARGS,
                     max_file_size="5mb", run_history=False)

if __name__ == "__main__":
    demo.launch(**LAUNCH_KWARGS)
