"""Logic for three extra tabs: compare up to three loan offers, check a refinance, and check a CSV file of
offers in one go. Each function returns the HTML for its result panel (the batch check also returns the
path of its results file). app.py wires them into the page; this module never imports app.py, so app.py
can import it.
"""
from __future__ import annotations

import csv
import datetime
import html
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid

import finance
import inputs
import markupcheck_model
import scoring
from fmt import FLAG_TEXT, _esc, _flag_chip, _pct, _usd, percentile_text

DISCLAIMER = "This project is a prototype and is not financial advice."
MAX_OFFERS = 3
REFI_MIN_BALANCE = 1000.0
REFI_MAX_MONTHS = 96
# The Refinance tab's own labels for the two profile fields inputs.validate() names by the Check tab's labels.
REFI_LABELS = {inputs.L_SCORE: "Credit score now", inputs.L_YEAR: "Car's model year"}
BATCH_MAX_ROWS = 500
BATCH_PREVIEW_ROWS = 25
BATCH_REQUIRED = ("credit_score", "new_or_used", "model_year", "vehicle_price", "amount_financed", "term_months", "apr")
BATCH_NEW_COLUMNS = ("typical_apr", "range_low", "range_high", "percentile", "verdict", "error")
RESULTS_NAME = "markupcheck_results.csv"

STUB_BANNER = ('<div class="mc-banner" role="note"><strong>Placeholder numbers.</strong> The trained model is not '
               "connected yet, so every comparison with similar loans below is a placeholder.</div>")


def _disclaimer() -> str:
    return f'<p class="mc-disclaimer">{DISCLAIMER}</p>'


def _errors(messages, heading: str = "Please check these entries", fields=(), err_id: str | None = None) -> str:
    """`messages` must already be HTML-safe: user values are escaped where they were put into the text. `fields` are
    the labels of the inputs at fault; the page script marks them aria-invalid and points them at this message."""
    items = "".join(f"<li>{m}</li>" for m in messages)
    named = "|".join(dict.fromkeys(f for f in fields if f))
    attrs = (f' id="{err_id}"' if err_id else "") + (f' data-invalid="{_esc(named)}"' if named else "")
    return (f'<div class="mc-result"><div class="mc-error"{attrs} role="alert"><h3>{heading}</h3>'
            f"<ul>{items}</ul></div></div>")


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _credit_union_section(products) -> str:
    """NCUA's national averages for each distinct closest product among `products` (credit_union dicts)."""
    lines = []
    for cu in products:
        kind = "new-car" if cu["new_or_used"] == "new" else "used-car"
        lines.append(f"<p>On {_esc(cu['rate_date'])}, credit unions reported an average of "
                     f"<strong>{_pct(cu['credit_union_pct'])}</strong> and banks <strong>{_pct(cu['bank_pct'])}</strong> "
                     f"for a {int(cu['term_months'])}-month {kind} loan (NCUA).</p>")
    if not lines:
        return ""
    return ('<section class="mc-section"><h3>Credit unions and banks</h3>' + "".join(lines)
            + "<p class='mc-note'>These are national averages, not adjusted for credit score, so your own rate "
              "can be higher or lower.</p></section>")


# ---------------------------------------------------------------- compare offers


def _with_label(label: str, message: str) -> str:
    return f"{label}: {message[:1].lower()}{message[1:]}"


def compare_offers(score, kind, year, price, financed, offers) -> str:
    """Rank up to three offers (name, apr, term) for the same car and buyer by total interest."""
    # Valid placeholder APR and term, so only the buyer's own fields can fail here.
    _, profile_errors = inputs.validate(score, kind, year, price, financed, 60, 10.0, None)
    messages = [m for _, m in profile_errors]
    fields = []
    filled = []
    for i, row in enumerate(list(offers or [])[:MAX_OFFERS], start=1):
        name, apr, term = (tuple(row or ()) + (None, None, None))[:3]
        if _blank(apr) and _blank(term):
            continue
        label = f"Offer {i}"
        offer, errors = inputs.validate(score, kind, year, price, financed, term, apr, None)
        messages += [_with_label(label, m) for field, m in errors if field in (inputs.L_APR, inputs.L_TERM)]
        fields += [f"{label} APR (%)" if field == inputs.L_APR else f"{label} term (months)"
                   for field, _ in errors if field in (inputs.L_APR, inputs.L_TERM)]
        filled.append((label if _blank(name) else str(name).strip(), offer))
    if len(filled) < 2:
        messages.append("Enter at least two offers to compare, each with an APR and a loan term.")
    if messages:
        return _errors(messages, fields=fields, err_id="mc-error-compare")

    rows = []
    for name, offer in filled:
        amount, apr, term = offer["amount_financed"], offer["offered_apr_pct"], offer["term_months"]
        rows.append({"name": name, "apr": apr, "term": term, "monthly": finance.monthly_payment(amount, apr, term),
                     "interest": finance.total_paid(amount, apr, term) - amount,
                     "result": markupcheck_model.predict(offer, detail=False)})
    rows.sort(key=lambda r: (r["interest"], r["apr"]))
    cheapest = rows[0]

    parts = ['<div class="mc-result">']
    if any(r["result"].get("stub") for r in rows):
        parts.append(STUB_BANNER)
    body = []
    for r in rows:
        mark, tag = (' class="mc-row-yours"', ' <span class="mc-yours">cheapest</span>') if r is cheapest else ("", "")
        body.append(
            f"<tr{mark}><th scope='row'>{_esc(r['name'])}{tag}<span class='mc-sub'>{r['term']} months</span></th>"
            f"<td>{_pct(r['apr'])}</td><td>{_usd(r['monthly'], cents=True)}</td><td>{_usd(r['interest'])}</td>"
            f"<td>{_flag_chip(r['result']['flag'])}"
            f"<span class='mc-sub'>Typical {_pct(r['result']['typical_pct'])}</span></td></tr>")
    sentences = []
    for r in rows[1:]:
        gap = r["interest"] - cheapest["interest"]
        if gap < 0.5:
            sentences.append(f"{_esc(cheapest['name'])} and {_esc(r['name'])} cost about the same in interest.")
        else:
            sentences.append(f"{_esc(cheapest['name'])} costs <strong>{_usd(gap)} less</strong> in interest "
                             f"than {_esc(r['name'])}.")
    parts.append(
        '<section class="mc-section"><h3>Your offers, cheapest first</h3>'
        '<table class="mc-table"><thead><tr><th scope="col">Offer</th><th scope="col">APR</th>'
        '<th scope="col">Monthly</th><th scope="col">Total interest</th><th scope="col">Versus similar loans</th>'
        f"</tr></thead><tbody>{''.join(body)}</tbody></table>"
        f"<p class='mc-cost'>{' '.join(sentences)}</p>"
        f"<p class='mc-note'>Total interest is what you pay on top of the {_usd(filled[0][1]['amount_financed'])} "
        "you borrow, if you make every payment on time. Versus similar loans compares each APR with loans like "
        "yours from all lenders in our data, for that offer's term; Typical is their usual APR.</p>")
    if len({r["term"] for r in rows}) > 1:
        parts.append("<p class='mc-note'>Your offers have different terms. A longer term lowers the monthly "
                     "payment, but you usually pay more interest in total.</p>")
    parts.append("</section>")

    products = {}
    for r in rows:
        cu = r["result"].get("credit_union")
        if cu:
            products.setdefault((cu["new_or_used"], int(cu["term_months"])), cu)
    parts.append(_credit_union_section(products.values()))
    parts.append(_disclaimer())
    parts.append("</div>")
    return "".join(parts)


# ---------------------------------------------------------------- refinance


def _saving_text(saving: float, cents: bool) -> str:
    if saving > 0.5:
        return f"You'd save {_usd(saving, cents)}"
    if saving < -0.5:
        return f"You'd pay {_usd(saving, cents)} more"
    return "About the same"


def _add_months(d: datetime.date, n: int) -> datetime.date:
    y, m = divmod(d.month - 1 + n, 12)
    year, month = d.year + y, m + 1
    last = (datetime.date(year + (month == 12), month % 12 + 1, 1) - datetime.timedelta(days=1)).day
    return datetime.date(year, month, min(d.day, last))


def reminder_ics(today: datetime.date | None = None) -> str:
    """Two all-day calendar reminders, 6 and 12 months out, to check the rate again. No numbers from the check."""
    today = today or datetime.date.today()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//MarkupCheck//Refinance reminder//EN", "CALSCALE:GREGORIAN"]
    for n in (6, 12):
        day = _add_months(today, n)
        lines += ["BEGIN:VEVENT", f"UID:{uuid.uuid4().hex}@markupcheck", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + datetime.timedelta(days=1):%Y%m%d}",
                  "SUMMARY:Recheck your car-loan rate / Revisa la tasa de tu préstamo de auto",
                  "DESCRIPTION:Your credit score and market rates may have changed. Open MarkupCheck's Refinance "
                  "tab to compare your rate with similar loans. / Tu puntaje y las tasas pueden haber cambiado. Abre "
                  "la pestaña Refinanciar de MarkupCheck.",
                  "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def _reminder_section() -> str:
    href = "data:text/calendar;charset=utf-8," + urllib.parse.quote(reminder_ics())
    return ("<section class='mc-section'><h3>Check again later</h3>"
            "<p>Rates and credit scores change. Add two reminders to your calendar, 6 and 12 months from today, to "
            "check again. The file holds no numbers from this check.</p>"
            f"<p><a class='mc-btn mc-ics' download='markupcheck-reminders.ics' href=\"{href}\">Add reminders to your "
            "calendar</a></p></section>")


def refinance_check(score, year, balance, current_apr, months_left, car_value, offered_rate=None) -> str:
    """How the current APR compares with similar loans, and what a new loan at the typical APR, or at a rate a
    lender offered, would change for the months that are left."""
    dom = scoring.INPUT_DOMAIN
    # Placeholder values that always pass, so only the score and the model year can fail here.
    profile, profile_errors = inputs.validate(score, "used", year, 10000, 10000, 60, 10.0, None)
    messages = [m for _, m in profile_errors]
    fields = [REFI_LABELS.get(f) for f, _ in profile_errors]

    owed = inputs._number(balance)
    if owed is None:
        messages.append("Enter what you still owe on the loan, in dollars (more than $1,000).")
        fields.append("Balance left ($)")
    elif owed <= REFI_MIN_BALANCE:
        messages.append(f"This check works for balances over $1,000. You entered {_esc(balance)}.")
        fields.append("Balance left ($)")

    apr = inputs._number(current_apr)
    if apr is None:
        messages.append("Enter your current APR, for example 14.5.")
        fields.append("Current APR (%)")
    elif not 0 <= apr <= dom["apr_pct_max"]:
        messages.append(f"Your current APR should be from 0% to {dom['apr_pct_max']:.0f}%. You entered {_esc(current_apr)}.")
        fields.append("Current APR (%)")

    months = inputs._number(months_left)
    if months is None:
        messages.append("Enter how many monthly payments you have left, for example 40.")
        fields.append("Months left")
    elif not 1 <= months <= REFI_MAX_MONTHS or months != int(months):
        messages.append(f"Months left should be a whole number from 1 to {REFI_MAX_MONTHS}. "
                        f"You entered {_esc(months_left)}.")
        fields.append("Months left")

    value = None if _blank(car_value) else inputs._number(car_value)
    if not _blank(car_value) and (value is None or value <= 0):
        messages.append("Enter your car's value in dollars (more than $0), or leave it blank.")
        fields.append("Car's value now ($, optional)")
    offered = None if _blank(offered_rate) else inputs._number(offered_rate)
    if not _blank(offered_rate) and (offered is None or not 0 <= offered <= dom["apr_pct_max"]):
        messages.append(f"Enter the rate you were offered as a percent from 0% to {dom['apr_pct_max']:.0f}%, or "
                        "leave it blank.")
        fields.append("Rate a lender offered you (%, optional)")
        offered = None
    if messages:
        return _errors(messages, fields=fields, err_id="mc-error-refi")

    months = int(months)
    assumed_value = value is None
    value = owed if assumed_value else value
    model_term = max(dom["term_months"][0], months)
    offer = {"credit_score": profile["credit_score"], "new_or_used": "used",
             "vehicle_model_year": profile["vehicle_model_year"], "vehicle_price": float(value),
             "amount_financed": float(owed), "term_months": model_term, "offered_apr_pct": float(apr), "lender": None}
    result = markupcheck_model.predict(offer, detail=False)
    typical = float(result["typical_pct"])
    cu = result.get("credit_union")
    # Savings only at the typical rate for loans like this one: NCUA's national average isn't adjusted for
    # credit score or term, so a saving computed from it would overstate what this buyer could get.
    options = [("Typical for similar loans", typical)]
    if offered is not None:  # a rate the buyer was actually quoted, so the difference is theirs if approved
        options.append(("If approved at the rate you were offered", float(offered)))

    parts = ['<div class="mc-result">']
    if result.get("stub"):
        parts.append(STUB_BANNER)
    parts.append(
        '<section class="mc-section"><h3>Your current rate</h3>'
        f"<p>Your current APR of <strong>{_pct(apr)}</strong>, compared with similar loans: "
        f"{_flag_chip(result['flag'])}</p>"
        f"<p>Similar used-car loans typically got <strong>{_pct(typical)}</strong>, and most got between "
        f"{_pct(result['range_low_pct'])} and {_pct(result['range_high_pct'])}. Your APR is higher than "
        f"{percentile_text(result['percentile'])} of them.</p></section>")

    current = finance.refinance(owed, months, apr, apr)["current_payment"]
    body = []
    for label, new_apr in options:
        refi = finance.refinance(owed, months, apr, new_apr)
        body.append(f"<tr><th scope='row'>{label}<span class='mc-sub'>{_pct(new_apr)}</span></th>"
                    f"<td>{_usd(refi['new_payment'], cents=True)}</td>"
                    f"<td>{_saving_text(refi['monthly_saving'], cents=True)}</td>"
                    f"<td>{_saving_text(refi['total_saving'], cents=False)}</td></tr>")
    month_word = "month" if months == 1 else "months"
    parts.append(
        '<section class="mc-section"><h3>If you refinanced</h3>'
        f"<p class='mc-section-intro'>At {_pct(apr)}, paying off {_usd(owed)} over {months} {month_word} works out "
        f"to about {_usd(current, cents=True)} a month. Here is the same balance and time at other rates.</p>"
        '<table class="mc-table"><thead><tr><th scope="col">New rate</th><th scope="col">New payment</th>'
        f'<th scope="col">Each month</th><th scope="col">Over {months} {month_word}</th></tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></section>")

    parts.append(_credit_union_section([cu] if cu else []))

    notes = ["We compared your loan with used-car loans, since a car you already own counts as used."]
    if assumed_value:
        notes.append(f"You left the car's value blank, so we assumed it is worth what you owe, {_usd(owed)}.")
    if months < model_term:
        notes.append(f"Loans in our data run at least {model_term} months, so we compared your rate with "
                     f"{model_term}-month loans. The payments above still use your {months} {month_word} left.")
    if offered is not None:
        notes.append("The offered rate is the one a lender quoted you. The difference assumes you are approved at it.")
    notes += ["Our data is loans made when people bought their cars. Refinance loans can be priced differently.",
              "Refinancing can have fees, such as a loan or title fee. They aren't included here.",
              "Check the exact payoff amount with your lender. It can differ from the balance on your statement."]
    parts.append('<section class="mc-section"><h3>Keep in mind</h3>'
                 + "".join(f"<p class='mc-note'>{n}</p>" for n in notes) + "</section>")
    parts.append(_reminder_section())
    parts.append(_disclaimer())
    parts.append("</div>")
    return "".join(parts)


# ---------------------------------------------------------------- batch check

FILE_HEADING = "Please check this file"
UNREADABLE = ("We couldn't read this file. In Excel or Google Sheets, save it as CSV (UTF-8) and try again. "
              "The template shows the columns it needs.")


def _remove_old_results(max_age_s: int = 3600) -> None:
    """Delete batch result folders older than an hour, so the page's promise that files aren't kept holds."""
    root = tempfile.gettempdir()
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if name.startswith("markupcheck_") and os.path.isdir(path) and time.time() - os.path.getmtime(path) > max_age_s:
            shutil.rmtree(path, ignore_errors=True)


def batch_check(file_path) -> tuple[str, str | None]:
    """Check every row of a CSV file of offers. Returns (summary HTML, results CSV path or None).
    Never raises: a file it can't use gives an error box and None."""
    try:
        return _batch_check(file_path)
    except Exception:  # undecodable bytes, a broken CSV, an unreadable path: all the same to the buyer
        return _errors([UNREADABLE], FILE_HEADING), None


def _batch_check(file_path):
    path = getattr(file_path, "name", file_path)  # older Gradio versions pass a tempfile wrapper, not a path
    if _blank(path):
        return _errors(["Choose a CSV file to check. The template shows the columns it needs."], FILE_HEADING), None

    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next((cells for cells in reader if any(c.strip() for c in cells)), None)
        if header is None:
            return _errors(["This file is empty. Start from the template, which shows the columns it needs."],
                           FILE_HEADING), None
        keys = [c.strip().lower() for c in header]
        missing = [c for c in BATCH_REQUIRED if c not in keys]
        if missing:
            names = ", ".join(f"<code>{_esc(c)}</code>" for c in missing)
            return _errors([f"The first row must name the columns. These are missing: {names}. "
                            "The template shows them all."], FILE_HEADING), None
        rows, capped = [], False
        for cells in reader:
            if not any(c.strip() for c in cells):
                continue
            if len(rows) == BATCH_MAX_ROWS:
                capped = True
                break
            rows.append(cells)
    if not rows:
        return _errors(["This file has column names but no rows to check."], FILE_HEADING), None

    col = {k: keys.index(k) for k in (*BATCH_REQUIRED, "lender") if k in keys}
    kept = [i for i, k in enumerate(keys) if k not in BATCH_NEW_COLUMNS]  # old results are replaced, not doubled
    out_rows, preview, any_stub = [], [], False
    counts = {flag: 0 for flag in FLAG_TEXT}
    n_errors = 0
    for n, raw in enumerate(rows, start=1):
        cells = (list(raw) + [""] * len(header))[:len(header)]

        def cell(key):
            return cells[col[key]] if key in col else ""

        problems, result, offer = [], None, None
        if any(c.strip() for c in raw[len(header):]):
            # An unquoted "17,500" splits into two cells and shifts every value after it.
            problems.append("This row has more values than there are columns. If a number has a comma, like "
                            "17,500, remove the comma or put the number in quotes.")
        else:
            offer, errors = inputs.validate(cell("credit_score"), cell("new_or_used"), cell("model_year"),
                                            cell("vehicle_price"), cell("amount_financed"), cell("term_months"),
                                            cell("apr"), cell("lender"))
            problems += [m for _, m in errors]
        if not problems:
            try:
                result = markupcheck_model.predict(offer, detail=False)
            except Exception as exc:
                # Logged by type only, as app.py does: the message could quote the row's numbers.
                print(f'{{"level": "error", "scope": "batch_check", "row": {n}, "message": "{type(exc).__name__}"}}',
                      file=sys.stderr)
                problems.append("Something went wrong on our side while checking this row.")

        if problems:
            n_errors += 1
            added = ["", "", "", "", "", "; ".join(html.unescape(p) for p in problems)]
        else:
            any_stub = any_stub or bool(result.get("stub"))
            counts[result["flag"]] = counts.get(result["flag"], 0) + 1
            added = [f"{result['typical_pct']:.2f}", f"{result['range_low_pct']:.2f}",
                     f"{result['range_high_pct']:.2f}", f"{result['percentile']:.1f}",
                     FLAG_TEXT.get(result["flag"], (str(result["flag"]),))[0], ""]
        out_rows.append([cells[i] for i in kept] + added)

        if n <= BATCH_PREVIEW_ROWS:
            if problems:
                preview.append(f"<tr><th scope='row'>{n}</th><td>{_esc(cell('apr'))}</td>"
                               f"<td colspan='2'>{' '.join(problems)}</td></tr>")
            else:
                preview.append(f"<tr><th scope='row'>{n}</th><td>{_pct(offer['offered_apr_pct'])}</td>"
                               f"<td>{_pct(result['typical_pct'])}</td><td>{_flag_chip(result['flag'])}</td></tr>")

    _remove_old_results()
    out_path = os.path.join(tempfile.mkdtemp(prefix="markupcheck_"), RESULTS_NAME)
    # utf-8-sig so Excel opens the file with any accented lender names intact.
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([header[i] for i in kept] + list(BATCH_NEW_COLUMNS))
        writer.writerows(out_rows)
    # Gradio copies the file into its own cache (cleared by delete_cache) as soon as this returns, so the original,
    # which holds every uploaded row, is removed a minute later instead of waiting for the next batch check.
    cleanup = threading.Timer(60, shutil.rmtree, args=(os.path.dirname(out_path),), kwargs={"ignore_errors": True})
    cleanup.daemon = True
    cleanup.start()

    parts = ['<div class="mc-result">']
    if any_stub:
        parts.append(STUB_BANNER)
    row_word = "row" if len(rows) == 1 else "rows"
    intro = f"We checked <strong>{len(rows)}</strong> {row_word}."
    if capped:
        intro += (f" Your file has more than {BATCH_MAX_ROWS} rows, so we checked the first {BATCH_MAX_ROWS}. "
                  "The results file has only those rows.")
    tally = "".join(f"<tr><th scope='row'>{_esc(FLAG_TEXT[flag][0])}</th><td>{counts[flag]}</td></tr>"
                    for flag in FLAG_TEXT)
    tally += f"<tr><th scope='row'>Couldn't check</th><td>{n_errors}</td></tr>"
    parts.append(
        '<section class="mc-section"><h3>Your file, checked</h3>'
        f"<p>{intro}</p>"
        '<table class="mc-table mc-kv"><thead><tr><th scope="col">Versus similar loans</th>'
        f'<th scope="col">Rows</th></tr></thead><tbody>{tally}</tbody></table></section>')
    shown = min(len(rows), BATCH_PREVIEW_ROWS)
    parts.append(
        f'<section class="mc-section"><h3>{"All rows" if shown == len(rows) else f"First {shown} rows"}</h3>'
        '<table class="mc-table"><thead><tr><th scope="col">Row</th><th scope="col">APR</th>'
        '<th scope="col">Typical</th><th scope="col">Verdict</th></tr></thead>'
        f"<tbody>{''.join(preview)}</tbody></table>"
        "<p class='mc-note'>Row 1 is the first row under the column names. The results file has every row: your "
        "columns plus typical_apr, range_low, range_high, percentile, verdict and error.</p>"
        "<p class='mc-note'>Rows that name one of the 10 lenders in the data are compared with that lender's own "
        "similar loans; the rest with similar loans from all lenders.</p></section>")
    parts.append(_disclaimer())
    parts.append("</div>")
    return "".join(parts), out_path


# ---------------------------------------------------------------- contract box check

def contract_box_check(amount_financed, finance_charge, total_of_payments, n_payments, apr) -> str:
    """Check the federal Truth-in-Lending box on a contract against itself (no model, only arithmetic)."""
    amount, charge, total = (inputs._number(v) for v in (amount_financed, finance_charge, total_of_payments))
    n, rate = inputs._number(n_payments), inputs._number(apr)
    messages, fields = [], []
    if amount is None or amount <= 0:
        messages.append("Enter the Amount Financed from the box, in dollars.")
        fields.append("Amount Financed ($)")
    if charge is None or charge < 0:
        messages.append("Enter the Finance Charge from the box, in dollars.")
        fields.append("Finance Charge ($)")
    if total is None or total <= 0:
        messages.append("Enter the Total of Payments from the box, in dollars.")
        fields.append("Total of Payments ($)")
    if n is None or n != int(n) or not 1 <= n <= REFI_MAX_MONTHS:
        messages.append(f"Enter the number of payments, a whole number from 1 to {REFI_MAX_MONTHS}.")
        fields.append("Number of payments")
    if rate is None or not 0 <= rate <= scoring.INPUT_DOMAIN["apr_pct_max"]:
        messages.append("Enter the Annual Percentage Rate from the box, for example 15.9.")
        fields.append("Annual Percentage Rate (%)")
    if messages:
        return _errors(messages, fields=fields, err_id="mc-error-tila")
    c = finance.tila_check(amount, charge, total, int(n), rate)
    lines = []
    if c["sum_ok"]:
        lines.append(f"The Amount Financed plus the Finance Charge equals the Total of Payments ({_usd(total, cents=True)}).")
    else:
        lines.append(f"The Amount Financed plus the Finance Charge is {_usd(amount + charge, cents=True)}, but the Total "
                     f"of Payments says {_usd(total, cents=True)}, a difference of {_usd(c['sum_gap'], cents=True)}. "
                     "Ask the dealer why they don't add up.")
    pay = f"{int(n)} payments of about {_usd(c['payment'], cents=True)}"
    if c["implied_apr_pct"] is None:
        lines.append(f"{pay} can't repay {_usd(amount)} at any APR from 0% to 60%. Check the numbers you typed.")
    elif c["apr_ok"]:
        lines.append(f"{pay} on {_usd(amount)} works out to an APR of {_pct(c['implied_apr_pct'])}, which matches the "
                     f"{_pct(rate)} in the box within the federal tolerance of one eighth of a point.")
    else:
        lines.append(f"{pay} on {_usd(amount)} works out to an APR of {_pct(c['implied_apr_pct'])}, but the box says "
                     f"{_pct(rate)}. A first payment due later than a month after signing can explain a small "
                     "difference; ask the dealer to show how the APR was worked out.")
    ok = c["sum_ok"] and c["apr_ok"]
    return (
        "<div class='mc-result'><section class='mc-section mc-first'><h3>"
        + ("The box adds up" if ok else "Something in the box doesn't add up") + "</h3>"
        + "".join(f"<p>{line}</p>" for line in lines)
        + "<p class='mc-note'>To see whether the APR itself is fair, enter the Amount Financed and the APR in the "
          "check above.</p></section>" + _disclaimer() + "</div>"
    )
