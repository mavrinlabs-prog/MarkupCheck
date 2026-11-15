"""The "For teachers" tab: a short lesson with four made-up buyers, a printable worksheet and an answer key.

The answer key is computed by the same model the page uses, when the app starts, so it always matches what students
see. Students open the buyers through links; nobody types personal information.
"""
from __future__ import annotations

import finance
import i18n
import markupcheck_model
import sections
from fmt import FLAG_TEXT, _esc, _pct, _usd

FIELDS = ["credit_score", "new_or_used", "vehicle_model_year", "vehicle_price", "amount_financed", "term_months",
          "offered_apr_pct"]
BUYERS = [  # made up; Jordan and Sam are the page's own examples
    ("Jordan", (660, "used", 2019, 17500, 18500, 72, 15.9)),
    ("Sam", (760, "used", 2022, 24000, 25000, 60, 14.5)),
    ("Alex", (780, "new", 2026, 32000, 28000, 60, 6.9)),
    ("Riley", (590, "used", 2018, 14000, 15500, 72, 21.9)),
]
QUESTIONS = [
    "Open Jordan's offer. What range of APRs did similar loans mostly get, and is Jordan's 15.9% inside it?",
    "Sam's APR (14.5%) is lower than Jordan's (15.9%). Why does MarkupCheck rate Sam's offer well above similar "
    "loans and Jordan's as typical?",
    "For Sam, how much more would the loan cost over 60 months than at the typical rate? What is each percentage point "
    "worth?",
    "Under \"Why this is the typical price\" for Sam, which detail lowers the typical rate the most?",
    "Open Alex's offer and find \"The whole deal\". How much will Alex pay in all, and how much of that is interest?",
    "MarkupCheck says it can't show whether a markup was added. Name two other reasons a price can be high.",
]


def _offer(values) -> dict:
    return {**dict(zip(FIELDS, values)), "lender": None}


def _answers() -> list[str] | None:
    if markupcheck_model._load() is None:
        return None
    res = {name: markupcheck_model.predict(_offer(v), grid=False) for name, v in BUYERS}
    off = {name: _offer(v) for name, v in BUYERS}
    jordan, sam, alex = res["Jordan"], res["Sam"], res["Alex"]
    j_name = FLAG_TEXT.get(jordan["flag"], (jordan["flag"],))[0]
    inside = jordan["range_low_pct"] <= 15.9 <= jordan["range_high_pct"]
    steps = sam["waterfall"]["steps"]
    lowest = min(steps, key=lambda s: s[1]) if steps else None
    a = off["Alex"]
    paid = finance.total_paid(a["amount_financed"], a["offered_apr_pct"], a["term_months"])
    interest = paid - a["amount_financed"]
    up_front = max(a["vehicle_price"] - a["amount_financed"], 0)
    per = finance.cost_per_point(25000, 14.5, 60)
    return [
        f"Similar loans mostly got {_pct(jordan['range_low_pct'])} to {_pct(jordan['range_high_pct'])}. Jordan's 15.9% "
        f"is {'inside' if inside else 'outside'} that range, so it is rated {_esc(j_name)}.",
        f"Sam's 760 score and newer car put the typical rate for loans like Sam's at {_pct(sam['typical_pct'])}; "
        f"Jordan's 660 score and older car put it at {_pct(jordan['typical_pct'])}. A lower APR can still be far above "
        "what similar buyers got.",
        f"About {_usd(sam['extra_cost_usd'])} more over 60 months. Each percentage point is worth about {_usd(per)}.",
        (f"{_esc(lowest[0])}: it lowers the typical rate by about {abs(lowest[1]):.1f} points." if lowest
         else "The details are close to a typical loan's."),
        f"About {_usd(paid + up_front)} in all, counting the {_usd(up_front)} paid up front; {_usd(interest)} of it "
        "is interest.",
        "Risk the data can't see (such as the buyer's full credit file), the lender, the state, or a dealer markup. "
        "The data can't tell these apart.",
    ]


def teacher_html() -> str:
    rows = "".join(
        f"<tr><th scope='row'>{_esc(name)}</th><td>{v[0]}</td><td>{'New' if v[1] == 'new' else 'Used'} {v[2]}</td>"
        f"<td>{_usd(v[4])} over {v[5]} months</td><td>{_pct(v[6])}</td>"
        f"<td><a href='?b={name.lower()}{_esc(sections.share_hash(_offer(v), None, None))}'>Open {_esc(name)}'s "
        "offer</a></td></tr>"
        for name, v in BUYERS)
    answers = _answers()
    key = ("".join(f"<li>{a}</li>" for a in answers) if answers
           else "<li>The trained model isn't loaded, so the answers can't be worked out here.</li>")
    return (
        "<div class='mc-result mc-teacher'><section class='mc-section mc-first'>"
        "<h2 class='mc-form-title'>MarkupCheck in the classroom</h2>"
        "<p>A lesson of about 30 minutes on how car-loan rates are set. Students open four made-up buyers, so nobody "
        "types personal information.</p>"
        "<h3>Students will be able to</h3><ul class='mc-list'>"
        "<li>Read an APR range and say where an offer falls.</li>"
        "<li>Explain why the same APR can be typical for one buyer and high for another.</li>"
        "<li>Work out what a higher APR costs over the loan.</li>"
        "<li>Name reasons a price can be high besides a markup.</li></ul></section>"
        "<section class='mc-section'><h3>The buyers</h3><table class='mc-table'><thead><tr><th scope='col'>Buyer</th>"
        "<th scope='col'>Credit score</th><th scope='col'>Car</th><th scope='col'>Loan</th><th scope='col'>APR</th>"
        f"<th scope='col'>Open</th></tr></thead><tbody>{rows}</tbody></table>"
        "<p class='mc-note'>Each link opens the check with that buyer's numbers filled in.</p></section>"
        "<section class='mc-section' id='mc-sheet'><h3>Worksheet</h3>"
        f"<ol class='mc-list'>{''.join(f'<li>{_esc(q)}</li>' for q in QUESTIONS)}</ol>"
        "<div class='mc-card-actions'><button type='button' class='mc-btn mc-print-sheet'>Print the worksheet</button>"
        "</div></section>"
        "<section class='mc-section'><details class='mc-faq'><summary>Answer key (for teachers)</summary>"
        f"<ol class='mc-list'>{key}</ol></details></section>"
        f"<p class='mc-disclaimer'>{i18n.DISCLAIMER_EN}</p></div>"
    )
