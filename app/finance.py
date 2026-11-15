"""Loan arithmetic for the app's money features: no model, no data, just the standard fixed-rate formula
(scoring.monthly_payment) and its inverse.
"""
from __future__ import annotations

from scoring import monthly_payment

APR_SEARCH_MAX = 60.0  # above any APR the app accepts (40%), so a payment that implies more is reported, not clipped
PAYMENT_TOLERANCE = 1.00  # dollars a month: rounding and odd first-payment dates stay below this


def apr_from_payment(principal: float, payment: float, term_months: int) -> float | None:
    """The APR (%) at which `payment` repays `principal` over `term_months`. None if the payment is below
    the zero-interest payment (impossible for a loan) or would need an APR above APR_SEARCH_MAX."""
    if principal <= 0 or term_months <= 0 or payment <= 0:
        return None
    if payment < principal / term_months - 0.005:
        return None
    if payment > monthly_payment(principal, APR_SEARCH_MAX, term_months):
        return None
    lo, hi = 0.0, APR_SEARCH_MAX
    for _ in range(80):  # bisection: the payment rises with the APR, so this converges to well under 0.0001%
        mid = (lo + hi) / 2
        if monthly_payment(principal, mid, term_months) < payment:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 4)


def payment_check(principal: float, term_months: int, apr_pct: float, quoted_payment: float) -> dict:
    """Compare a quoted payment with what the quoted APR should cost. A payment well above it usually
    means something else is in the payment (add-ons, fees) or the APR or amount shown is not the real one."""
    expected = monthly_payment(principal, apr_pct, term_months)
    extra = quoted_payment - expected
    return {"expected_payment": round(expected, 2), "quoted_payment": round(quoted_payment, 2),
            "extra_per_month": round(extra, 2), "extra_total": round(extra * term_months, 2),
            "implied_apr_pct": apr_from_payment(principal, quoted_payment, term_months),
            "status": "higher" if extra > PAYMENT_TOLERANCE else "lower" if extra < -PAYMENT_TOLERANCE else "matches"}


def total_paid(principal: float, apr_pct: float, term_months: int) -> float:
    return monthly_payment(principal, apr_pct, term_months) * term_months


def addon_cost(addon_amount: float, apr_pct: float, term_months: int) -> dict:
    """What add-ons financed inside the loan really cost: their price plus the interest charged on them."""
    monthly = monthly_payment(addon_amount, apr_pct, term_months)
    total = monthly * term_months
    return {"price": round(addon_amount, 2), "monthly": round(monthly, 2), "total": round(total, 2),
            "interest": round(total - addon_amount, 2)}


def cost_per_point(principal: float, apr_pct: float, term_months: int) -> float:
    """Extra paid over the whole loan for one more percentage point of APR."""
    return round(total_paid(principal, apr_pct + 1.0, term_months) - total_paid(principal, apr_pct, term_months), 2)


def cumulative_interest(principal: float, apr_pct: float, term_months: int) -> list[float]:
    """Interest paid so far at the end of each month, 1..term (an amortization schedule)."""
    pay, balance, rate = monthly_payment(principal, apr_pct, term_months), principal, apr_pct / 100 / 12
    paid, out = 0.0, []
    for _ in range(term_months):
        interest = balance * rate
        paid += interest
        balance -= pay - interest
        out.append(round(paid, 2))
    return out


def refinance(balance: float, months_left: int, current_apr: float, new_apr: float) -> dict:
    """Monthly and total difference from replacing the rest of a loan with one at `new_apr` for the same
    number of months (fees for a new loan are not included)."""
    now, new = monthly_payment(balance, current_apr, months_left), monthly_payment(balance, new_apr, months_left)
    return {"current_payment": round(now, 2), "new_payment": round(new, 2), "monthly_saving": round(now - new, 2),
            "total_saving": round((now - new) * months_left, 2)}


APR_TOLERANCE = 0.125  # 12 CFR 1026.22(a)(2): a disclosed APR is accurate within 1/8 of a percentage point
SUM_TOLERANCE = 1.00  # dollars: the box's figures are rounded to the cent, so their sum can be off by pennies


def tila_check(amount_financed: float, finance_charge: float, total_of_payments: float, n_payments: int,
               apr_pct: float) -> dict:
    """Check a contract's federal Truth-in-Lending box against itself: the total of payments should equal the amount
    financed plus the finance charge, and the APR should match the one those payments imply (equal monthly
    payments, the first a month after signing; a later first payment can explain a small difference)."""
    sum_gap = total_of_payments - (amount_financed + finance_charge)
    payment = total_of_payments / n_payments
    implied = apr_from_payment(amount_financed, payment, n_payments)
    apr_gap = None if implied is None else apr_pct - implied
    return {"payment": round(payment, 2), "sum_gap": round(sum_gap, 2), "sum_ok": abs(sum_gap) <= SUM_TOLERANCE,
            "implied_apr_pct": implied, "apr_gap": None if apr_gap is None else round(apr_gap, 3),
            "apr_ok": apr_gap is not None and abs(apr_gap) <= APR_TOLERANCE}
