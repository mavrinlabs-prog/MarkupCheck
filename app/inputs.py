"""Reading and checking what a buyer typed: field labels, number parsing and validation."""
import datetime
import math
import re

import scoring
from fmt import _esc

# Field labels, shared by the form and by validation so a message can mark the field it is about.
L_SCORE, L_KIND, L_YEAR, L_PRICE = "Credit score", "New or used car", "Model year", "Vehicle price ($)"
L_FINANCED, L_TERM, L_APR, L_LENDER = "Amount financed ($)", "Loan term (months)", "Offered APR (%)", "Lender (optional)"
L_PAYMENT, L_ADDONS = "Monthly payment ($, optional)", "Add-ons in the loan ($, optional)"


def _number(value):
    """Return a finite float, or None if the field is blank or not a number."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str):
        # People type amounts the way they see them: "$17,500", "15.9%", "18 500", and on the Spanish page
        # "15,9" or "403,39", where a comma before one or two final digits is the decimal point.
        value = value.replace("$", "").replace("%", "").replace(" ", "").strip()
        if re.fullmatch(r"\d+,\d{1,2}", value):
            value = value.replace(",", ".")
        value = value.replace(",", "")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def validate(credit_score, new_or_used, vehicle_model_year, vehicle_price,
             amount_financed, term_months, offered_apr_pct, lender):
    """Return (offer, errors): errors are (field label, message) pairs; `offer` is None if there are any."""
    errors = []

    def bad(field, message):
        errors.append((field, message))

    this_year = datetime.date.today().year
    dom = scoring.INPUT_DOMAIN
    s_lo, s_hi = dom["credit_score"]
    t_lo, t_hi = dom["term_months"]

    score = _number(credit_score)
    if score is None:
        bad(L_SCORE, f"Enter your credit score (a number from {s_lo} to {s_hi}).")
    elif not s_lo <= score <= s_hi or score != int(score):
        bad(L_SCORE, f"Credit scores are whole numbers from {s_lo} to {s_hi}. You entered {_esc(credit_score)}.")

    kind = (new_or_used or "").strip().lower() if isinstance(new_or_used, str) else ""
    if kind not in ("new", "used"):
        bad(L_KIND, "Choose whether the car is new or used.")

    year = _number(vehicle_model_year)
    if year is None:
        bad(L_YEAR, "Enter the car's model year, for example 2019.")
    elif year != int(year) or year < dom["model_year_min"]:
        bad(L_YEAR, f"The model year should be a year from {dom['model_year_min']} on, like 2019. "
                      f"You entered {_esc(vehicle_model_year)}.")
    elif year > this_year + 1:
        # Next year's models go on sale during the current year, so only later years are rejected.
        bad(L_YEAR, f"A {int(year)} model year is in the future. Check the year on the window sticker or contract.")

    price = _number(vehicle_price)
    if price is None or price <= 0:
        bad(L_PRICE, "Enter the car's price in dollars (more than $0).")

    financed = _number(amount_financed)
    if financed is None or financed <= 1000:
        bad(L_FINANCED, "Enter the amount financed in dollars (more than $1,000, the smallest loans in our data). "
                        "It's on the loan contract.")

    term = _number(term_months)
    if term is None:
        bad(L_TERM, "Enter the loan term in months, for example 72.")
    elif not t_lo <= term <= t_hi or term != int(term):
        bad(L_TERM, f"The loan term should be a whole number of months from {t_lo} to {t_hi}. You entered {_esc(term_months)}.")

    apr = _number(offered_apr_pct)
    if apr is None:
        bad(L_APR, "Enter the APR you were offered (for example 15.9), or the monthly payment.")
    elif apr <= 0:
        bad(L_APR, "The APR must be more than 0%. A 0% rate is usually a carmaker promotion, which this tool can't compare.")
    elif apr > dom["apr_pct_max"]:
        bad(L_APR, f"An APR of {_esc(offered_apr_pct)}% is above {dom['apr_pct_max']:.0f}%, which is outside what this tool covers. "
                      "Check that you typed the APR, not the payment or the price.")

    if errors:
        return None, errors

    lender_text = lender.strip() if isinstance(lender, str) else ""
    offer = {
        "credit_score": int(score),
        "new_or_used": kind,
        "vehicle_model_year": int(year),
        "vehicle_price": float(price),
        "amount_financed": float(financed),
        "term_months": int(term),
        "offered_apr_pct": float(apr),
        "lender": lender_text or None,
    }
    return offer, []
