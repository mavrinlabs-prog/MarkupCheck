"""Result-page sections for the money features: payment check, add-ons, cost of a point, charts, ways to a
lower rate (with instant sliders), the dealer card with print and share link, and questions about the result.
Every number comes from the model's result or from finance.py; nothing here estimates anything new.
"""
from __future__ import annotations

import datetime
import html
import json
import urllib.parse
import uuid

import charts
import finance
import markupcheck_model
from fmt import CHIP_TEXT, FLAG_TEXT, _esc, _flag_chip, _pct, _usd


def _uid() -> str:
    return "c" + uuid.uuid4().hex[:8]


def both(fn, *args, **kwargs) -> str:
    """The wide chart and its compact phone version; CSS shows one of them by screen width."""
    return fn(*args, **kwargs) + fn(*args, compact=True, **kwargs)


def derived_apr_note(apr: float, payment: float) -> str:
    return (f"<p class='mc-note mc-derived'>You entered a payment, not an APR. A {_usd(payment, cents=True)} payment on "
            f"this loan works out to an APR of <strong>{_pct(apr)}</strong>, so that is what we checked.</p>")


def payment_section(offer: dict, payment: float) -> str:
    """The quoted payment against what the quoted APR should cost (a payment that is too high usually means
    something else is folded into it)."""
    c = finance.payment_check(offer["amount_financed"], offer["term_months"], offer["offered_apr_pct"], payment)
    if c["status"] == "matches":
        body = (f"<p>Your payment of {_usd(payment, cents=True)} matches a {_pct(offer['offered_apr_pct'])} APR on "
                f"{_usd(offer['amount_financed'])} over {offer['term_months']} months.</p>")
    elif c["status"] == "higher":
        implied = (f" It matches an APR of about <strong>{_pct(c['implied_apr_pct'])}</strong> instead."
                   if c["implied_apr_pct"] is not None else "")
        body = (f"<div class='mc-banner mc-alert-pay' role='note'><strong>Your payment is {_usd(c['extra_per_month'], cents=True)} "
                f"a month more than the APR explains</strong> ({_usd(c['extra_total'])} over the loan). A "
                f"{_pct(offer['offered_apr_pct'])} APR on {_usd(offer['amount_financed'])} over {offer['term_months']} "
                f"months should cost {_usd(c['expected_payment'], cents=True)} a month.{implied} Ask what else is in "
                "the payment, such as add-ons or fees, and whether the APR and amount on the contract are final.</div>")
    else:
        body = (f"<p>Your payment of {_usd(payment, cents=True)} is {_usd(-c['extra_per_month'], cents=True)} a month "
                f"less than a {_pct(offer['offered_apr_pct'])} APR on {_usd(offer['amount_financed'])} over "
                f"{offer['term_months']} months should cost ({_usd(c['expected_payment'], cents=True)}). Check that the "
                "amount financed and the term match the contract.</p>")
    return f"<section class='mc-section'><h3>Your payment</h3>{body}</section>"


def addons_section(offer: dict, addons: float) -> str:
    c = finance.addon_cost(addons, offer["offered_apr_pct"], offer["term_months"])
    return (
        "<section class='mc-section'><h3>Add-ons in your loan</h3>"
        f"<p>The {_usd(addons)} of add-ons you entered cost <strong>{_usd(c['total'])}</strong> by the end of the loan: "
        f"{_usd(c['interest'])} of that is interest, because they are financed at {_pct(offer['offered_apr_pct'])}. "
        f"They add {_usd(c['monthly'], cents=True)} to each payment.</p>"
        "<p class='mc-note'>Extended warranties, GAP coverage and similar products are usually optional. Ask for each "
        "price in writing, and whether you can buy it later, elsewhere, or not at all.</p></section>"
    )


def whole_deal_section(result: dict, offer: dict) -> str:
    """Price, what is financed beyond it, interest and the total, from the buyer's own numbers; the car's price
    itself is the buyer's, and nothing here judges it."""
    price, amount, term = float(offer["vehicle_price"]), float(offer["amount_financed"]), offer["term_months"]
    apr, typical = offer["offered_apr_pct"], float(result["typical_pct"])
    paid = finance.total_paid(amount, apr, term)
    # From the stated extra cost, not typical_pct, which is rounded to 2 decimals and would differ by a few dollars.
    paid_typical = paid - float(result["extra_cost_usd"])
    rows = [("Car price", _usd(price))]
    if amount > price + 0.5:
        rows.append(("Financed beyond the price (taxes, fees or add-ons)", _usd(amount - price)))
    elif price > amount + 0.5:
        rows.append(("Paid up front (down payment or trade-in)", _usd(price - amount)))
    rows += [(f"Interest over {term} months at {_pct(apr)}", _usd(paid - amount)),
             ("Total of your payments", _usd(paid))]
    up_front = max(price - amount, 0.0)
    body = "".join(f"<tr><th scope='row'>{label}</th><td>{value}</td></tr>" for label, value in rows)
    return (
        "<section class='mc-section'><h3>The whole deal</h3>"
        f"<table class='mc-table mc-deal'><tbody>{body}</tbody></table>"
        f"<p>All in, this car costs you about <strong>{_usd(paid + up_front)}</strong>. At the typical "
        f"{_pct(typical)}, the interest would be {_usd(paid_typical - amount)}.</p>"
        "<p class='mc-note'>Taxes and fees paid up front aren't included unless they are in the amount financed.</p>"
        "</section>"
    )


def cost_per_point_line(offer: dict) -> str:
    per = finance.cost_per_point(offer["amount_financed"], offer["offered_apr_pct"], offer["term_months"])
    return (f"<p class='mc-note'>Each percentage point of APR on this loan is worth about <strong>{_usd(per)}</strong> "
            f"over {offer['term_months']} months, so every point you negotiate off saves about that much.</p>")


def distribution_chart(result: dict, offer: dict) -> str:
    if not result.get("quantiles"):
        return ""
    svg = both(charts.distribution_svg, [tuple(q) for q in result["quantiles"]], offer["offered_apr_pct"],
               float(result["range_low_pct"]), float(result["range_high_pct"]), float(result["typical_pct"]), _uid())
    return f"<figure class='mc-figure'>{svg}<figcaption class='mc-note'>How the APRs of similar loans spread out, with " \
           "the range most of them got shaded.</figcaption></figure>"


def timeline_chart(result: dict, offer: dict) -> str:
    amount, term = offer["amount_financed"], offer["term_months"]
    # No credit-union line: NCUA's national average isn't adjusted for credit score or this term.
    series = [("Your offer", finance.cumulative_interest(amount, offer["offered_apr_pct"], term)),
              ("Typical", finance.cumulative_interest(amount, float(result["typical_pct"]), term))]
    svg = both(charts.timeline_svg, series, _uid(), highlight="Your offer")
    return (f"<figure class='mc-figure'>{svg}<figcaption class='mc-note'>Interest paid so far, month by month, on "
            f"{_usd(amount)} over {term} months.</figcaption></figure>")


def waterfall_chart(result: dict) -> str:
    w = result.get("waterfall")
    if not w:
        return ""
    start_label = "Typical loan in the data"
    svg = both(charts.waterfall_svg, start_label, float(w["start_pct"]), [tuple(s) for s in w["steps"]],
               "Typical for you", float(w["end_pct"]), _uid())
    return (f"<figure class='mc-figure'>{svg}<figcaption class='mc-note'>Each bar changes one of your details from a "
            "typical loan's value to yours; the bars are one-at-a-time comparisons, not proof of cause.</figcaption></figure>")


# ---------------------------------------------------------------- ways to a lower rate + sliders

def _cell(w: dict, score: int, term: int, down: float):
    si, ti, di = w["scores"].index(score), w["terms"].index(term), w["downs"].index(down)
    return w["cells"][(si * len(w["terms"]) + ti) * len(w["downs"]) + di]


def better_rate_section(result: dict, offer: dict) -> str:
    w = result.get("whatif")
    if not w:
        return ""
    s0, t0 = int(offer["credit_score"]), int(offer["term_months"])
    price, amount = float(offer["vehicle_price"]), float(offer["amount_financed"])
    base = _cell(w, s0, t0, 0.0)
    base_interest = finance.total_paid(amount, base[0], t0) - amount
    shorter = [t for t in w["terms"] if t < t0]
    options = []  # (label, score, term, down)
    if shorter:
        options.append((f"Choose a {shorter[-1]}-month term instead of {t0}", s0, shorter[-1], 0.0))
    if 0.10 in w["downs"]:
        options.append((f"Put {_usd(0.10 * price)} more down (10% of the price)", s0, t0, 0.10))
    if s0 + 20 in w["scores"]:
        options.append(("If your credit score were 20 points higher (paying card balances down can help)",
                        s0 + 20, t0, 0.0))
    thin = w.get("thin", 0)

    def row(label, sc, t, d):
        cell = _cell(w, sc, t, d)
        new_amount = amount - d * price
        interest = finance.total_paid(new_amount, cell[0], t) - new_amount
        drop = base[0] - cell[0]
        enough = cell[4] is None or cell[4] >= thin  # a figure from few loans isn't offered as advice
        return drop, enough, (f"<li><strong>{_esc(label)}:</strong> typical {_pct(cell[0])} "
                              f"({'down' if drop >= 0 else 'up'} {abs(drop):.1f} points), payment "
                              f"{_usd(finance.monthly_payment(new_amount, cell[0], t), cents=True)}, about "
                              f"{_usd(base_interest - interest)} {'less' if interest <= base_interest else 'more'} "
                              "interest than the typical rate for your loan now.</li>")

    scored = [(opt, *row(*opt)) for opt in options]
    shown = [(opt, drop, html_row) for opt, drop, enough, html_row in scored if enough and drop >= 0.1]
    if len(shown) >= 2:
        combo = ("All of these together", max(o[1] for o, _, _ in shown), min(o[2] for o, _, _ in shown),
                 max(o[3] for o, _, _ in shown))
        drop, enough, html_row = row(*combo)
        if enough and drop >= 0.1:
            shown.append((combo, drop, html_row))
    rows = sorted(((drop, html_row) for _, drop, html_row in shown), key=lambda r: -r[0])
    useful = [html_row for _, html_row in rows]
    intro = ("These changes lower the typical rate for a loan like yours the most:" if useful else
             "None of these changes moves the typical rate for a loan like yours by much:")
    items = "".join(useful or [h for _, enough, h in (s[1:] for s in scored) if enough])
    return (f"<section class='mc-section'><h3>Ways to a lower rate</h3><p>{intro}</p><ul class='mc-list'>{items}</ul>"
            + whatif_widget(result, offer) + "</section>")


def whatif_widget(result: dict, offer: dict) -> str:
    """Sliders over the precomputed grid; the page script answers each move without a server round trip."""
    w = result["whatif"]
    s0, t0 = int(offer["credit_score"]), int(offer["term_months"])
    si, ti = w["scores"].index(s0), w["terms"].index(t0)
    first = _cell(w, s0, t0, 0.0)
    data = html.escape(json.dumps({**w, "labels": CHIP_TEXT, "classes": {k: v[1] for k, v in FLAG_TEXT.items()}}),
                       quote=True)
    pay = finance.monthly_payment(float(offer["amount_financed"]), first[0], t0)
    few = (" Few loans in the data are like this, so treat it with care."
           if first[4] is not None and first[4] < w.get("thin", 0) else "")
    return (
        f"<div class='mc-whatif' data-whatif=\"{data}\"><h4>Try it yourself</h4>"
        "<div class='mc-wi-controls'>"
        f"<label class='mc-wi-row'><span>Credit score <output class='mc-wi-score-out'>{s0}</output></span>"
        f"<input type='range' class='mc-wi-score' aria-label='Credit score' min='0' max='{len(w['scores']) - 1}' step='1' value='{si}' "
        f"aria-valuetext='{s0}'></label>"
        f"<label class='mc-wi-row'><span>Term <output class='mc-wi-term-out'>{t0} months</output></span>"
        f"<input type='range' class='mc-wi-term' aria-label='Term' min='0' max='{len(w['terms']) - 1}' step='1' value='{ti}' "
        f"aria-valuetext='{t0} months'></label>"
        "<label class='mc-wi-row'><span>Extra down payment <output class='mc-wi-down-out'>$0</output></span>"
        f"<input type='range' class='mc-wi-down' aria-label='Extra down payment' min='0' max='{len(w['downs']) - 1}' step='1' value='0' "
        "aria-valuetext='$0'></label></div>"
        f"<p class='mc-wi-result' aria-live='polite'>Typical {_pct(first[0])}, most between {_pct(first[1])} and "
        f"{_pct(first[2])}. Your {_pct(w['offer_apr'])} would be {_flag_chip(first[3])}. Payment at the typical rate: "
        f"{_usd(pay, cents=True)}.{few}</p></div>"
    )


# ---------------------------------------------------------------- dealer card, share link, questions

def share_hash(offer: dict, payment, addons) -> str:
    """The offer as a URL fragment: browsers never send the part after # to the server."""
    def num(v):  # exact to the cent: ":g" would round 120000.55 to 120001
        return f"{float(v):.2f}".rstrip("0").rstrip(".")

    fields = {"s": offer["credit_score"], "k": offer["new_or_used"], "y": offer["vehicle_model_year"],
              "p": num(offer["vehicle_price"]), "a": num(offer["amount_financed"]), "t": offer["term_months"],
              "r": num(offer["offered_apr_pct"]), "l": offer.get("lender") or "",
              "m": num(payment) if payment else "", "o": num(addons) if addons else ""}
    return "#" + urllib.parse.urlencode(fields)


def dealer_card(result: dict, offer: dict, payment, addons) -> str:
    typical, low, high = float(result["typical_pct"]), float(result["range_low_pct"]), float(result["range_high_pct"])
    yours = next((r for r in (result.get("lenders") or []) if r["yours"]), None)
    cu = result.get("credit_union")
    lines = [
        f"<li><strong>My offer:</strong> {_pct(offer['offered_apr_pct'])} APR, {offer['term_months']} months, "
        f"{_usd(offer['amount_financed'])} financed, {_usd(result['monthly_payment_offer'], cents=True)} a month.</li>",
        f"<li><strong>Similar real loans (SEC filings):</strong> typical {_pct(typical)}, most between {_pct(low)} and "
        f"{_pct(high)}.</li>",
    ]
    if yours:
        lines.append(f"<li><strong>At {_esc(yours['lender'])}:</strong> typical {_pct(yours['typical_pct'])} for "
                     "similar loans.</li>")
    if cu:
        lines.append(f"<li><strong>Credit unions (NCUA, {_esc(cu['rate_date'])}):</strong> {_pct(cu['credit_union_pct'])} "
                     f"average for a {cu['term_months']}-month {cu['new_or_used']}-car loan.</li>")
    flag = str(result["flag"])
    lines.append(f"<li><strong>Verdict:</strong> {_esc(FLAG_TEXT.get(flag, (flag,))[0])}.</li>")
    extra, term = float(result["extra_cost_usd"]), offer["term_months"]
    if extra > 0.5:
        cost = f"about {_usd(extra)} more over {term} months than at the typical rate"
    elif extra < -0.5:
        cost = f"about {_usd(extra)} less over {term} months than at the typical rate"
    else:
        cost = f"about the same as at the typical rate over {term} months"
    lines.append(f"<li><strong>Cost:</strong> {cost}.</li>")
    checks, ev = result.get("checks") or [], result.get("evidence") or {}
    sure = []
    if checks:
        sure.append(f"the verdict holds in {sum(1 for c in checks if c['same_flag'])} of {len(checks)} checks")
    if ev:
        sure.append(f"{int(ev['n_similar']):,} loans in the data are like mine")
    if sure:
        lines.append(f"<li><strong>How sure:</strong> {'; '.join(sure)}.</li>")
    months = result.get("data_months")
    if months:
        lines.append(f"<li><strong>Data:</strong> real loans up to {_month_name(months['newest_loans'])}; rates "
                     f"adjusted to the {_month_name(months['rate_benchmark'])} Treasury average.</li>")
    asks = ["What buy rate did the lender approve before any dealer markup?"]
    if offer["offered_apr_pct"] > typical + 0.05:
        asks.append(f"Can you bring my rate to {_pct(typical)}, the typical rate for loans like mine?")
    asks.append("What is included in the amount financed, and which items are optional?")
    d = datetime.date.today()
    today = f"{d:%B} {d.day}, {d.year}"
    link = share_hash(offer, payment, addons)
    return (
        "<section class='mc-section mc-card' id='mc-card'><h3>Take this to the dealer</h3>"
        f"<ul class='mc-card-facts'>{''.join(lines)}</ul>"
        f"<p><strong>Questions to ask:</strong></p><ol class='mc-list'>{''.join(f'<li>{_esc(a)}</li>' for a in asks)}</ol>"
        "<p class='mc-note'>This compares my offer with similar loans; it can't show whether a markup was added.</p>"
        # The page script fills in the full address, so a printed card carries the link, not just its # part.
        f"<p class='mc-note mc-card-link'>Link to this check: <span class='mc-share-url' data-share=\"{_esc(link)}\">"
        "</span></p>"
        f"<p class='mc-note'>Checked with MarkupCheck on {today}. MarkupCheck is a student prototype, not financial "
        "advice.</p>"
        "<div class='mc-card-actions'><button type='button' class='mc-btn mc-print'>Print or save as PDF</button>"
        f"<button type='button' class='mc-btn mc-copy' data-share=\"{_esc(link)}\">Copy a link to this check</button>"
        "<span class='mc-copy-status' role='status'></span></div>"
        "<p class='mc-note'>The link holds your numbers after the # sign, which browsers don't send to our server; "
        "anyone you send it to can see them.</p></section>"
    )


def _month_name(ym: str) -> str:
    return datetime.datetime.strptime(ym, "%Y-%m").strftime("%B %Y")  # "2026-01" -> "January 2026"


def pushback_section(result: dict, offer: dict) -> str:
    """Fixed replies for what a finance office commonly says, filled with the buyer's own numbers. No AI, and no
    line claims a markup was found or promises a saving."""
    typical, low, high = float(result["typical_pct"]), float(result["range_low_pct"]), float(result["range_high_pct"])
    apr, term = offer["offered_apr_pct"], offer["term_months"]
    paid = finance.total_paid(float(offer["amount_financed"]), apr, term)
    pairs = [
        ("That's the rate the bank approved.", "Can you show me the lender's approval and the buy rate in writing?"),
        ("This rate is only good today.", "I'd like time to compare it with a pre-approval from a credit union or bank."),
    ]
    if apr > typical + 0.05:
        pairs.append(("With your credit, this rate is normal.",
                      f"Similar loans to mine mostly got {_pct(low)} to {_pct(high)}, typical {_pct(typical)}. "
                      f"Can you get closer to {_pct(typical)}?"))
    pairs += [
        ("Let's just focus on the monthly payment.",
         f"I'd like to compare the APR and the total I'd pay: {_usd(paid)} over "
         f"{term} months at {_pct(apr)}, against {_usd(paid - float(result['extra_cost_usd']))} at the typical "
         f"{_pct(typical)}."),
        ("The warranty or GAP coverage is required for the loan.",
         "Can you show me in writing that the lender requires it? If it's optional, I'd like the price without it."),
        ("We can lower your payment with a longer term.", "What would the APR and the total I pay be on the longer term?"),
    ]
    rows = "".join(f"<dt>{_esc(they)}</dt><dd>{_esc(you)}</dd>" for they, you in pairs)
    return (
        "<section class='mc-section' id='mc-pushback'><h3>If the dealer pushes back</h3>"
        "<p>Calm replies you can use at the finance desk:</p>"
        f"<dl class='mc-pushback'>{rows}</dl>"
        "<p class='mc-note'>If nothing moves, you can say \"Thank you, I'll compare my offers and come back.\" "
        "Nothing is final until you sign.</p></section>"
    )


def jump_links() -> str:
    """Links to the parts a buyer at the desk needs most; on a phone the dealer card is many screens down."""
    links = [("mc-card", "Dealer card"), ("mc-pushback", "If they push back"), ("mc-quote", "Written offers"),
             ("mc-state", "Your state")]
    return ("<nav class='mc-jump' aria-label='Jump to'>"
            + "".join(f"<a href='#{i}'>{_esc(t)}</a>" for i, t in links) + "</nav>")


def state_section(offer: dict) -> str:
    """The buyer picks a state in the page; the browser shows that state's same-lender price gap (Explore tab data)
    and its credit unions' posted rates (NCUA Call Report) from the numbers below, with no server call."""
    loaded = markupcheck_model._load()
    extras = (loaded or {}).get("extras") or {}
    states = (extras.get("states") or {}).get("by_state") or {}
    rates = extras.get("rates_extra")
    if not states or not rates:
        return ""
    kind = "used" if offer["new_or_used"] == "used" else "new"
    cu = rates["ncua_callreport"]["by_state"]
    data = {}
    for code in sorted(charts.STATE_NAMES):
        g, c = states.get(code), (cu.get(code) or {}).get(kind)
        data[code] = [g["gap"] if g else None, g["holds"] if g else None, g["loans"] if g else None,
                      c["median"] if c else None, c["n"] if c else None]
    as_of = datetime.datetime.strptime(rates["ncua_callreport"]["as_of"], "%Y-%m-%d")
    options = "".join(f'<option value="{code}">{_esc(name)}</option>'
                      for code, name in sorted(charts.STATE_NAMES.items(), key=lambda kv: kv[1]))
    return (
        f"<section class='mc-section mc-state' id='mc-state' data-kind='{kind}' "
        f"data-states=\"{html.escape(json.dumps(data, separators=(',', ':')), quote=True)}\">"
        "<h3>Your state</h3>"
        "<p>Choose your state to see how prices there compared at the same lender, and what credit unions based "
        f"there were offering on {as_of:%B} {as_of.day}, {as_of.year}.</p>"
        "<label class='mc-state-label'><span>State</span> <select class='mc-state-select'>"
        f"<option value=\"\">Choose a state</option>{options}</select></label>"
        "<p class='mc-state-out' aria-live='polite'></p></section>"
    )


def quote_request_section(offer: dict) -> str:
    """A message the buyer sends themselves to the dealer and to lenders, so every quote is for the same loan."""
    kind = "used" if offer["new_or_used"] == "used" else "new"
    message = (f"Hello. I'm buying a {offer['vehicle_model_year']} {kind} car for {_usd(offer['vehicle_price'])} and "
               f"want to finance {_usd(offer['amount_financed'])} over {offer['term_months']} months. Could you send "
               "me your APR for this loan in writing, with any fees and add-ons listed separately? I'm comparing "
               "written offers before I sign.")
    return (
        "<section class='mc-section' id='mc-quote'><h3>Ask for written offers</h3>"
        "<p>Send this to the dealer and to two or three banks or credit unions, so every APR you compare is for "
        "the same loan:</p>"
        f"<p class='mc-quote-text'>{_esc(message)}</p>"
        "<div class='mc-card-actions'><button type='button' class='mc-btn mc-copy-text'>Copy this message</button>"
        "<span class='mc-copy-status' role='status'></span></div></section>"
    )


def questions_section(result: dict, offer: dict) -> str:
    flag = str(result["flag"])
    name = FLAG_TEXT.get(flag, (flag,))[0]
    apr, typical = offer["offered_apr_pct"], float(result["typical_pct"])
    low, high = float(result["range_low_pct"]), float(result["range_high_pct"])
    per = finance.cost_per_point(offer["amount_financed"], apr, offer["term_months"])
    ev = result.get("evidence") or {}
    checks = result.get("checks") or []
    held = sum(1 for c in checks if c["same_flag"])
    w = result.get("waterfall") or {}
    top = [s for s in (w.get("steps") or []) if abs(s[1]) >= 0.1][:2]
    why = ("; ".join(f"{s[0].lower()} {'adds' if s[1] > 0 else 'takes off'} about {abs(s[1]):.1f} points" for s in top)
           if top else "your details are close to a typical loan's")
    sure = []
    if ev:
        sure.append(f"{int(ev['n_similar']):,} loans in the data are like yours")
    if checks:
        sure.append(f"the verdict holds in {held} of {len(checks)} checks")
    sure.append(f"the range held for {float(result.get('range_coverage_pct', 80)):.0f}% of similar buyers in our test")
    qa = [
        ("Is my offer marked up?",
         f"We can't tell for one loan. Your {_pct(apr)} is rated <strong>{_esc(name)}</strong> next to similar loans "
         f"(most got {_pct(low)} to {_pct(high)}). A price above the range can come from a dealer markup or from risk "
         "the data can't see, so ask for the buy rate."),
        ("What is the buy rate, and how do I ask for it?",
         "It's the rate the lender approved before the dealer adds anything. Ask: \"What buy rate did the lender "
         "approve, and how much is being added?\" Some dealers will tell you; asking shows you know how it works."),
        ("How much would a lower rate save me?",
         f"About {_usd(per)} for every percentage point over {offer['term_months']} months. At the typical "
         f"{_pct(typical)} you'd pay {_usd(result['monthly_payment_typical'], cents=True)} a month."),
        ("Why is the typical rate for me where it is?", f"Compared with a typical loan in the data, {why}."),
        ("How sure is this?", "; ".join(sure).capitalize() + "."),
        ("Which credit score should I enter?",
         "The one your lender pulled, if you know it. Car lenders often use a FICO Auto Score, which runs 250 to "
         "900; free apps often show a different kind of score, and the two can differ. The checks under \"How sure "
         "is this?\" show your verdict with a score 30 points lower and 30 points higher."),
        ("Where do the numbers come from?", _esc(result.get("data_note", ""))),
        ("Is this financial advice?", "No. MarkupCheck is a student prototype. It shows how your offer compares with "
                                      "real loans; the decision is yours."),
    ]
    items = "".join(f"<details class='mc-faq'><summary>{_esc(q)}</summary><p>{a}</p></details>" for q, a in qa)
    return f"<section class='mc-section'><h3>Questions about your result</h3>{items}</section>"
