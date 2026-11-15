"""Shared definitions and scoring math for MarkupCheck.

Both the app (app/markupcheck_model.py, app/app.py) and the notebook (src/mc.py adds app/ to its path)
import this module, so the numbers the notebook evaluates come from the same code the app runs.
It lives in app/ because the Hugging Face Space ships only that folder.
"""
from __future__ import annotations

import numpy as np

# Inputs the model was trained on. clean() in src/mc.py keeps only loans inside these ranges and the app
# rejects offers outside them. Lenders report FICO Auto scores, which run 250-900.
INPUT_DOMAIN = {"credit_score": (250, 900), "term_months": (12, 96), "apr_pct_max": 40.0, "model_year_min": 1990}
VEHICLE_AGE_CLIP = (-1, 30)

# Experian's credit-score bands, with the top band stretched to 900 for FICO Auto scores.
TIER_BINS = [249, 500, 600, 660, 780, 900]
TIER_ORDER = ["deep subprime", "subprime", "near-prime", "prime", "super-prime"]

# The lenders in the data: model code, display name, and the names a buyer might type (compared as whole words or
# adjacent words written together). Brands that the same lender's trusts finance: Chrysler Capital (Santander), Lexus
# Financial Services (Toyota), Acura Financial Services (Honda), Kia Finance and Genesis Finance (Hyundai Capital;
# the Hyundai pools hold Kia and Genesis loans), Infiniti Financial Services (Nissan), Lincoln Automotive Financial
# (Ford). AmeriCredit is GM Financial's subprime brand and its loans are in other trusts, so it isn't matched here.
LENDERS = {
    "carmax": {"code": 0, "name": "CarMax Auto Finance", "aliases": ["carmax"]},
    "ally": {"code": 1, "name": "Ally", "aliases": ["ally"]},
    "santander": {"code": 2, "name": "Santander Consumer", "aliases": ["santander", "chryslercapital"]},
    "toyota": {"code": 3, "name": "Toyota Financial Services",
               "aliases": ["toyotafinancial", "toyotamotorcredit", "lexusfinancial"], "brand": "toyota"},
    "honda": {"code": 4, "name": "American Honda Finance",
              "aliases": ["americanhonda", "hondafinancial", "acurafinancial"], "brand": "honda"},
    "hyundai": {"code": 5, "name": "Hyundai Capital America",
                "aliases": ["hyundaicapital", "hyundaimotorfinance", "kiafinance", "kiamotorsfinance", "genesisfinance"],
                "brand": "hyundai"},
    "nissan": {"code": 6, "name": "Nissan Motor Acceptance",
               "aliases": ["nmac", "nissanmotoracceptance", "infinitifinancial"], "brand": "nissan"},
    "ford": {"code": 7, "name": "Ford Credit",
             "aliases": ["fordcredit", "fordmotorcredit", "lincolnautomotivefinancial"], "brand": "ford"},
    "gmf": {"code": 8, "name": "GM Financial", "aliases": ["gmfinancial", "generalmotorsfinancial"]},
    "capone": {"code": 9, "name": "Capital One", "aliases": ["capitalone"]},
}


def tier(score: float) -> str:
    for upper, name in zip(TIER_BINS[1:], TIER_ORDER):
        if score <= upper:
            return name
    return TIER_ORDER[-1]


def monthly_payment(principal: float, apr_pct: float, term_months: int) -> float:
    r = apr_pct / 100 / 12
    if r == 0:
        return principal / term_months
    return principal * r / (1 - (1 + r) ** -term_months)


def predict_grid(models: dict, X) -> np.ndarray:
    """Predictions of every quantile model (sorted by quantile) for the rows of DataFrame X, sorted
    within each row so quantiles never cross."""
    return np.sort(np.column_stack([models[a].predict(X) for a in sorted(models)]), axis=1)


def col(alphas, a) -> int:
    """Column of the grid that holds quantile a."""
    return int(np.argmin(np.abs(np.asarray(sorted(alphas)) - a)))


def percentile(grid_row: np.ndarray, alphas, value: float) -> float:
    """Where value falls in one row's predicted distribution (0-100). Values outside the 5%-95%
    quantiles are placed halfway into the tail (2.5 or 97.5)."""
    a = np.asarray(sorted(alphas))
    return float(np.interp(value, grid_row, a, left=a[0] / 2, right=1 - (1 - a[-1]) / 2) * 100)


def flag(spread: float, upper: float, delta: float) -> str:
    """'high' above the calibrated range; 'likely marked up' (shown as 'well above') more than delta above it."""
    if spread > upper + delta:
        return "likely marked up"
    return "high" if spread > upper else "typical"
