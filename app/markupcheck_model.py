"""MarkupCheck model interface (see CONTRACT.md): predict(offer) -> result dict.

Loads the trained quantile models from app/model/ (written by notebooks/MarkupCheck.ipynb):
  model/A  whole-market view (never sees the lender)
  model/B  same-lender view (used when the buyer names a lender that is in the data)
If those files don't exist yet, it returns clearly labelled placeholder output (stub=True).
The scoring math (quantile grid, percentile, flag, payments) lives in scoring.py, shared with the notebook.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import re

import numpy as np
from threadpoolctl import threadpool_limits

import scoring
from scoring import monthly_payment  # noqa: F401  (part of this module's interface)

MODEL_DIR = pathlib.Path(__file__).resolve().parent / "model"
_CACHE: dict = {}


def _load():
    if "meta" in _CACHE:
        return _CACHE
    meta_path = MODEL_DIR / "meta.json"
    if not meta_path.exists():
        return None
    import joblib
    meta = json.loads(meta_path.read_text())
    models = {}
    for view, info in meta["views"].items():
        models[view] = {float(a): joblib.load(MODEL_DIR / info["dir"] / f"q{int(round(float(a) * 100)):02d}.joblib")
                        for a in meta["alphas"]}
    extras_path = MODEL_DIR / "extras.json"  # written by src/build_extras.py; the checks need it
    extras = json.loads(extras_path.read_text()) if extras_path.exists() else None
    rule_path = MODEL_DIR / "rule_of_thumb.json"  # written by src/build_rule_of_thumb.py
    if extras is not None and rule_path.exists():
        extras = {**extras, "rule_of_thumb": json.loads(rule_path.read_text())}
    forward_path = MODEL_DIR / "forward_summary.json"  # src/build_forward_summary.py
    if extras is not None and forward_path.exists():
        extras = {**extras, "forward_test": json.loads(forward_path.read_text())}
    rates_path = MODEL_DIR / "rates_extra.json"  # src/fetch_g19.py and src/fetch_ncua_callreport.py
    if extras is not None and rates_path.exists():
        extras = {**extras, "rates_extra": json.loads(rates_path.read_text())}
    _CACHE.update({"meta": meta, "models": models, "extras": extras})
    return _CACHE


def features_from_offer(offer: dict, current_year: int, lender_code=None) -> dict:
    """Same feature definitions as src/mc.py add_features() (tests/test_mc_synthetic.py checks they agree)."""
    lo, hi = scoring.VEHICLE_AGE_CLIP
    row = {
        "credit_score": float(offer["credit_score"]),
        "is_used": 1 if offer["new_or_used"] == "used" else 0,
        "vehicle_age": float(min(max(current_year - int(offer["vehicle_model_year"]), lo), hi)),
        "amount_financed": float(offer["amount_financed"]),
        "ltv": float(offer["amount_financed"]) / float(offer["vehicle_price"]),
        "term_months": float(offer["term_months"]),
    }
    if lender_code is not None:
        row["lender_code"] = lender_code
    return row


def _stub(offer: dict) -> dict:
    typical, low, high = 11.0, 8.5, 13.5
    apr = offer["offered_apr_pct"]
    pay_offer = monthly_payment(offer["amount_financed"], apr, offer["term_months"])
    pay_typical = monthly_payment(offer["amount_financed"], typical, offer["term_months"])
    return {
        "stub": True, "view": "placeholder", "range_low_pct": low, "range_high_pct": high, "typical_pct": typical,
        "range_coverage_pct": 80.0,
        "percentile": 50.0, "flag": "typical" if apr <= high else ("likely marked up" if apr >= high + 1.0 else "high"),
        "monthly_payment_offer": round(pay_offer, 2), "monthly_payment_typical": round(pay_typical, 2),
        "extra_cost_usd": round((pay_offer - pay_typical) * offer["term_months"], 2),
        "reasons": ["Stub reason 1", "Stub reason 2", "Stub reason 3"], "same_lender": None, "market": None,
        "weak_spots": ["Stub: the real model is not trained yet."], "data_note": "Stub: no data loaded.",
    }


def _grids(models: dict, rows: list, features: list) -> np.ndarray:
    import pandas as pd
    return scoring.predict_grid(models, pd.DataFrame(rows)[features])


def _recal(meta, view, lender):
    """A lender's monthly recalibration of the same-lender view (src/recalibrate.py), or None."""
    return (meta["views"][view].get("recalibrated") or {}).get(lender) if view == "same_lender" and lender else None


def _assess(meta, view, grid, spread, bounds, bench=None, lender=None):
    """Range, typical, percentile and flag for one view, all in spread points and all inside `bounds`
    (the spreads that correspond to the lowest and highest APR in the data), so the range bar, the
    flag and the percentile always describe the same numbers. A recalibrated lender's prices are re-centred
    and its range re-widened from that lender's newest filings."""
    info = meta["views"][view]
    alphas = sorted(float(a) for a in meta["alphas"])
    r = _recal(meta, view, lender)
    grid = np.asarray(grid) + (float(r["shift_points"]) if r else 0.0)
    g = np.clip(grid, *bounds)
    i_lo, i_mid, i_hi = (scoring.col(alphas, a) for a in (meta["lo"], 0.5, meta["hi"]))
    qhat, delta = float(r["qhat"] if r else info["conformal_qhat"]), float(info["flag_delta"])
    low, high = max(g[i_lo] - qhat, bounds[0]), min(g[i_hi] + qhat, bounds[1])
    clipped = bool(np.any(grid != g) or grid[i_lo] - qhat < bounds[0] or grid[i_hi] + qhat > bounds[1])
    return {"grid": g, "i_mid": i_mid, "low": low, "high": high, "typical": g[i_mid], "clipped": clipped,
            "percentile": scoring.percentile(g, alphas, spread),
            # With bench, the flag compares against the range end as the page prints it (2 decimals), so the
            # badge and the sentence under it never disagree; without it (the notebook), the exact value.
            "flag": scoring.flag(spread, high if bench is None else round(high + bench, 2) - bench, delta)}


# Words that can sit next to a carmaker's name in its finance arm's name ("Ford Motor Credit Company LLC").
FINANCE_WORDS = {"acceptance", "america", "american", "auto", "automotive", "bank", "capital", "co", "company", "corp",
                 "corporation", "credit", "finance", "financial", "financing", "inc", "llc", "lp", "motor", "motors",
                 "na", "service", "services", "the", "usa"}


def _lender_key(meta, lender_text):
    """Match whole words, or two or three adjacent words written together ("Car Max", "CARMAX", "Chrysler
    Capital"), so a name that merely contains the letters "ally" (e.g. "Tally Credit Union") doesn't match.
    A credit union never matches, even one named after a carmaker ("Honda Federal Credit Union"), and a carmaker's
    bare name ("Ford") matches only with finance words around it, not as part of a dealer's name ("Bill Currie Ford")."""
    words = re.findall(r"[a-z]+", (lender_text or "").lower())
    joined = {"".join(words[i:j]) for i in range(len(words)) for j in range(i + 1, min(i + 3, len(words)) + 1)}
    if "creditunion" in joined or "fcu" in words:
        return None
    for key, lender in scoring.LENDERS.items():
        if any(alias in joined for alias in lender["aliases"]):
            return key
        brand = lender.get("brand")
        if brand and brand in words and all(w == brand or w in FINANCE_WORDS for w in words):
            return key
    return None


def predict(offer: dict, detail: bool = True, grid: bool = True) -> dict:
    """`detail=False` skips the per-lender table, the what-if checks and the slider grid (batch checks);
    `grid=False` skips only the slider grid, which the page needs and the API doesn't (about 70 ms instead of 120)."""
    loaded = _load()
    if loaded is None:
        return _stub(offer)
    # One row per click: scikit-learn's thread pool costs more to start than it saves here (~6-9x slower).
    with threadpool_limits(limits=1):
        return _predict(loaded["meta"], loaded["models"], offer, loaded.get("extras"), detail, grid)


# What-if sizes for the checks. They are questions, not claims about how far scores or values differ.
SCORE_SHIFT = 30  # VantageScore and FICO, or two FICO versions, can disagree by this much or more
VALUE_SHIFT = 0.05  # a car valued 5% lower, e.g. at invoice rather than sticker price

LIMITS = [
    "The data has no race, sex or age and no dealer details, so the tool can show how far a price is from "
    "similar loans, but not why.",
    "Credit unions and banks that don't sell their loans into public bonds appear only as national averages, "
    "not loan by loan.",
]
# src/later_deals.py: on Hyundai's 210 test loans the all-lenders view missed by 0.35 points more than the rule of
# thumb (95% interval 0.21 to 0.49) and the same-lender view by 0.13 less, so a buyer without a lender is told.
NO_LENDER_LIMIT = ("Without a lender, this compares with all lenders at once. In our test that was less accurate than "
                   "a simple rule of thumb for loans from Hyundai Capital America; naming the lender on the contract "
                   "fixed it.")


def _month(ym: str) -> str:
    return datetime.datetime.strptime(ym, "%Y-%m").strftime("%B %Y")  # "2026-01" -> "January 2026"


def _summary(a: dict, bench: float) -> dict:
    return {"typical_pct": round(float(a["typical"] + bench), 2), "range_low_pct": round(float(a["low"] + bench), 2),
            "range_high_pct": round(float(a["high"] + bench), 2), "percentile": round(float(a["percentile"]), 1),
            "flag": a["flag"]}


def _similar_count(extras: dict, offer: dict) -> int:
    """Loans in the data with the same new/used, a credit score within about 20 points and a term within
    about 6 months (whole bins of the extras table)."""
    sc = extras["similar_counts"]
    grid = sc["counts_by_used_score_term"][1 if offer["new_or_used"] == "used" else 0]
    s, t = int(offer["credit_score"]), int(offer["term_months"])
    s0, s1 = (max(0, (s - 20 - sc["score_low"]) // sc["score_bin"]),
              min(len(grid) - 1, (s + 20 - sc["score_low"]) // sc["score_bin"]))
    t0, t1 = (max(0, (t - 6 - sc["term_low"]) // sc["term_bin"]),
              min(len(grid[0]) - 1, (t + 6 - sc["term_low"]) // sc["term_bin"]))
    return int(sum(grid[i][j] for i in range(s0, s1 + 1) for j in range(t0, t1 + 1)))


def _credit_union_rate(extras: dict, offer: dict) -> dict:
    """NCUA's closest product: new 48 or 60 months, used 36 or 48 months."""
    kind, term = offer["new_or_used"], int(offer["term_months"])
    rows = [r for r in extras["ncua"]["rows"] if r["new_or_used"] == kind]
    row = min(rows, key=lambda r: abs(r["term_months"] - term))
    return {**row, "rate_date": extras["ncua"]["rate_date"], "source_url": extras["ncua"]["source_url"]}


def _fresh_rates(extras: dict | None, offer: dict) -> dict | None:
    """Newer reference rates than the NCUA averages: credit unions' posted rates from the Call Report (one per credit
    union, not tied to a score or term) and, for new cars, the Federal Reserve's G.19 bank and finance-company rates."""
    rates = (extras or {}).get("rates_extra")
    if not rates:
        return None
    kind = "used" if offer["new_or_used"] == "used" else "new"
    cr = rates["ncua_callreport"]
    stats = cr["national"][kind]
    out = {"new_or_used": kind, "as_of": cr["as_of"], "n": stats["n"], "median_pct": stats["median"],
           "p25_pct": stats["p25"], "p75_pct": stats["p75"], "g19": []}
    if kind == "new":
        out["g19"] = [{k: s[k] for k in ("label", "value_pct", "period", "preliminary")}
                      for s in rates["g19"].values()]
    return out


def _rule_of_thumb(extras: dict | None, offer: dict, bench: float) -> dict | None:
    """The B1 rule for this offer: its credit tier and new/used cell from the training months, plus the Treasury."""
    rule = (extras or {}).get("rule_of_thumb")
    if not rule:
        return None
    tier = scoring.tier(float(offer["credit_score"]))
    used = 1 if offer["new_or_used"] == "used" else 0
    cell = rule["table"].get(f"{tier}|{used}", rule["b0"])
    return {"tier": tier, "new_or_used": offer["new_or_used"], "typical_pct": round(cell["q50"] + bench, 2),
            "range_low_pct": round(cell["q_lo"] + bench, 2), "range_high_pct": round(cell["q_hi"] + bench, 2),
            "test": rule["test"]}


def _predict(meta, all_models, offer, extras=None, detail=True, grid=True):
    year = int(meta["offer_benchmark_month"][:4])
    bench = float(meta["offer_benchmark_pct"])
    apr = float(offer["offered_apr_pct"])
    spread = apr - bench
    apr_lo, apr_hi = float(meta["apr_observed_min"]), float(meta["apr_observed_max"])
    bounds = (apr_lo - bench, apr_hi - bench)

    key = _lender_key(meta, offer.get("lender"))
    view_key = "market" if key is None else "same_lender"
    info = meta["views"][view_key]
    row_a = features_from_offer(offer, year)
    row_main = row_a if key is None else features_from_offer(offer, year, scoring.LENDERS[key]["code"])

    # Plain-language reasons: change one input at a time to the typical training value and see how much
    # the predicted typical rate moves (a one-at-a-time comparison, not causation). The lender isn't
    # included; its effect is shown separately as the same-lender vs whole-market difference.
    ref = meta["reference_profile"]
    changed = [f for f in info["features"] if f != "lender_code"]
    # One pass: the offer, each one-input variant, then every input at the reference value (the waterfall's start).
    rows = [row_main] + [{**row_main, f: ref[f]} for f in changed] + [{**row_main, **{f: ref[f] for f in changed}}]
    grids = _grids(all_models[view_key], rows, info["features"])
    main = _assess(meta, view_key, grids[0], spread, bounds, bench, key)
    main_grid = grids[0]
    rc = _recal(meta, view_key, key)
    shift = float(rc["shift_points"]) if rc else 0.0
    ref_typical = float(np.clip(grids[-1][main["i_mid"]] + shift, *bounds))
    market = main if key is None else _assess(
        meta, "market", _grids(all_models["market"], [row_a], meta["views"]["market"]["features"])[0], spread, bounds, bench)

    effects = sorted(((f, main["typical"] - float(np.clip(g[main["i_mid"]] + shift, *bounds))) for f, g in zip(changed, grids[1:-1])),
                     key=lambda t: abs(t[1]), reverse=True)
    reasons = [f"{_describe(f, row_main[f])} {'raises' if eff > 0 else 'lowers'} the typical rate by about "
               f"{abs(eff):.1f} points compared with {_describe(f, ref[f], typical=True)}."
               for f, eff in effects[:3] if abs(eff) >= 0.1]  # an input this close to typical explains nothing
    if len(reasons) < 3:
        reasons.append("Your other details are close to a typical loan in the data, so they barely change the typical rate.")

    typical = main["typical"] + bench
    n, term = float(offer["amount_financed"]), int(offer["term_months"])
    pay_offer, pay_typical = monthly_payment(n, apr, term), monthly_payment(n, typical, term)

    same, market_out = None, None
    if key is not None:
        same = {"lender": scoring.LENDERS[key]["name"], "typical_pct": round(typical, 2),
                "difference_pts": round(main["typical"] - market["typical"], 2),
                "n_loans": int(info["n_loans_by_lender"].get(key, 0)),
                # None: no extras built, so nothing to say; {"loans": 0}: the lender had no loans in the test months.
                "test": None if not (extras or {}).get("lender_tests") else extras["lender_tests"].get(key, {"loans": 0})}
        market_out = {"typical_pct": round(market["typical"] + bench, 2), "range_low_pct": round(market["low"] + bench, 2),
                      "range_high_pct": round(market["high"] + bench, 2), "percentile": round(market["percentile"], 1),
                      "flag": market["flag"]}

    group = f"{scoring.tier(row_a['credit_score'])}|{row_a['is_used']}"
    cov = info["coverage_by_group"].get(group, info["coverage_overall"])
    if rc:  # measured on that lender's newer months, not the original test months
        cov = float(rc["coverage_expected"])

    rare = []  # inputs the data has few loans like
    if main["clipped"] or market["clipped"]:
        rare.append(f"Part of the range was capped at the lowest or highest APR seen in the data "
                    f"({apr_lo:.2f}%–{apr_hi:.2f}%).")
    if n > float(meta["amount_max_train"]):
        rare.append("This loan amount is larger than any loan the model learned from.")
    if row_a["credit_score"] < 540:
        rare.append("Very few loans in public bond pools have credit scores this low.")
    if row_a["ltv"] > 1.4:
        rare.append("The loan is much larger than the car's value (often add-ons like warranties or GAP); "
                    "such loans are rare in the data.")
    if row_a["vehicle_age"] > 12:
        rare.append("Cars this old are rare in the data.")
    if term > 84:
        rare.append("Terms longer than 84 months are rare in the data.")

    if extras is None:  # model files without src/build_extras.py output: the original list, no checks
        weak = list(meta["weak_spots_always"]) + rare
        if key is None:
            weak.insert(0, "Add the lender named on your contract (if it's one of the 10 lenders in the data) for a "
                           "sharper same-lender comparison.")
        lenders = checks = evidence = risk = credit_union = None
    else:
        weak = list(LIMITS) + ([NO_LENDER_LIMIT] if key is None else [])

        # The same offer at each lender in the data (same-lender model), named lender marked.
        b_info = meta["views"]["same_lender"]
        lenders = checks = None
        if detail:
            rows_l = [features_from_offer(offer, year, lender["code"]) for lender in scoring.LENDERS.values()]
            lenders = [{"key": k, "lender": lender["name"], "yours": k == key,
                        "n_loans": int(b_info["n_loans_by_lender"].get(k, 0)),
                        **_summary(_assess(meta, "same_lender", g, spread, bounds, bench, k), bench)}
                       for (k, lender), g in zip(scoring.LENDERS.items(),
                                                 _grids(all_models["same_lender"], rows_l, b_info["features"]))]

            # What-if checks on the main view: does the verdict survive each doubt about the inputs or the data?
            variants = []  # (name, question, row)
            s = float(offer["credit_score"])
            lo_s, hi_s = scoring.INPUT_DOMAIN["credit_score"]
            for sign, word in ((-1, "lower"), (1, "higher")):
                alt = min(max(s + sign * SCORE_SHIFT, lo_s), hi_s)
                if alt != s:
                    variants.append(("score_" + word, f"If the score your lender used is {SCORE_SHIFT} points {word} "
                                     f"({alt:.0f})", {**row_main, "credit_score": alt}))
            if offer["new_or_used"] == "new" and int(offer["vehicle_model_year"]) < year - 1:
                variants.append(("as_used", "If this car is really used (a 'new' car this old is unusual)",
                                 {**row_main, "is_used": 1}))
            if offer["new_or_used"] == "new":
                variants.append(("value_lower", f"If your lender valued the car {VALUE_SHIFT:.0%} lower (for example "
                                 "at invoice, as some lenders report new cars)",
                                 {**row_main, "ltv": row_main["ltv"] / (1 - VALUE_SHIFT)}))
            checks = []
            if variants:
                v_grids = _grids(all_models[view_key], [r for _, _, r in variants], info["features"])
                checks = [{"name": name, "question": q, **_summary(_assess(meta, view_key, g, spread, bounds, bench, key), bench)}
                          for (name, q, _), g in zip(variants, v_grids)]
            # A recalibrated lender's prices were last measured in its newest recalibration month, so start there.
            since = rc["months"][-1] if rc else extras["treasury_newest_month"]
            old_bench = float(extras["treasury_by_month"][since]) if rc else float(extras["treasury_newest_pct"])
            if abs(old_bench - bench) >= 0.05:
                old_bounds = (apr_lo - old_bench, apr_hi - old_bench)
                checks.append({"name": "rates_unchanged",
                               "question": f"If car-loan rates haven't moved since {_month(since)} "
                                           f"(we assume they followed the 5-year Treasury, {old_bench:.2f}% then and "
                                           f"{bench:.2f}% in {_month(meta['offer_benchmark_month'])})",
                               **_summary(_assess(meta, view_key, main_grid, apr - old_bench, old_bounds, old_bench, key), old_bench)})
            for c in checks:
                c["same_flag"] = c["flag"] == main["flag"]

        evidence = {"n_similar": _similar_count(extras, offer), "n_loans": int(extras["n_loans"]), "rare": rare}
        groups = extras["repayment"]["by_group"]
        risk = {"months": extras["repayment"]["months_observed_median"],
                "rows": [{"lender": scoring.LENDERS[k]["name"], "yours": k == key,
                          "bad_rate_high": groups[k]["bad_rate_high"], "bad_rate_other": groups[k]["bad_rate_other"]}
                         for k in scoring.LENDERS if k in groups and (key is None or k == key)]}
        credit_union = _credit_union_rate(extras, offer)

    return {
        "stub": False, "view": "whole market" if key is None else f"same lender: {scoring.LENDERS[key]['name']}",
        "range_low_pct": round(float(main["low"] + bench), 2), "range_high_pct": round(float(main["high"] + bench), 2),
        "typical_pct": round(float(typical), 2), "percentile": round(main["percentile"], 1), "flag": main["flag"],
        "range_coverage_pct": round(100 * float(cov), 1),
        # float(): NumPy floats reach API clients as strings through gradio_client.
        "monthly_payment_offer": round(float(pay_offer), 2), "monthly_payment_typical": round(float(pay_typical), 2),
        "extra_cost_usd": round(float(pay_offer - pay_typical) * term, 2),
        "reasons": reasons, "same_lender": same, "market": market_out, "weak_spots": weak, "data_note": meta["data_note"],
        "data_months": {"newest_loans": rc["months"][-1] if rc else meta["newest_origination_month"],
                        "rate_benchmark": meta["offer_benchmark_month"]},
        "recalibrated": ({"lender": scoring.LENDERS[key]["name"], "months": rc["months"], "loans": rc["loans"],
                          "shift_points": round(float(rc["shift_points"]), 2)} if rc else None),
        "rule_of_thumb": _rule_of_thumb(extras, offer, bench),
        "fresh_rates": _fresh_rates(extras, offer),
        "forward_test": None if rc else (extras or {}).get("forward_test"),  # the recalibration answers it
        "lenders": lenders, "checks": checks, "evidence": evidence, "risk": risk, "credit_union": credit_union,
        "quantiles": [(round(a, 2), round(float(q + bench), 2)) for a, q in zip(sorted(float(x) for x in meta["alphas"]),
                                                                           main["grid"])],
        "waterfall": {"start_pct": round(ref_typical + bench, 2), "end_pct": round(float(typical), 2),
                      "steps": [(_short(f, row_main[f]), round(float(eff), 4)) for f, eff in effects if abs(eff) >= 0.05]},
        "whatif": _whatif(meta, all_models[view_key], info["features"], view_key, row_main, offer, spread, bounds, bench,
                          extras)
        if detail and grid else None,
    }


WHATIF_SCORE_STEPS = range(-60, 61, 10)
WHATIF_TERMS = (36, 48, 60, 72, 84)
WHATIF_DOWN = (0.0, 0.05, 0.10, 0.15, 0.20)  # extra down payment, as a share of the car's price


THIN = 500  # fewer similar loans than this in the data: the page says to treat the figure with care


def _whatif(meta, models, features, view_key, row_main, offer, spread, bounds, bench, extras=None) -> dict:
    """Typical APR, range, verdict and similar-loan count for a grid of changes the buyer could make (score,
    term, extra down payment), computed once so the page's sliders answer instantly without the server."""
    lo_s, hi_s = scoring.INPUT_DOMAIN["credit_score"]
    lo_t, hi_t = scoring.INPUT_DOMAIN["term_months"]
    s0, t0 = int(offer["credit_score"]), int(offer["term_months"])
    price, amount = float(offer["vehicle_price"]), float(offer["amount_financed"])
    scores = sorted({min(max(s0 + d, lo_s), hi_s) for d in WHATIF_SCORE_STEPS})
    terms = sorted({t for t in (*WHATIF_TERMS, t0) if lo_t <= t <= hi_t})
    downs = [d for d in WHATIF_DOWN if d == 0 or amount - d * price > 1000]  # always keep the offer itself
    rows = [{**row_main, "credit_score": float(sc), "term_months": float(t),
             "amount_financed": amount - d * price, "ltv": (amount - d * price) / price}
            for sc in scores for t in terms for d in downs]
    grid = _grids(models, rows, features)
    lender = _lender_key(meta, offer.get("lender"))
    counts = {}  # the evidence count depends on score and term only
    cells = []
    for row, g in zip(rows, grid):
        a = _assess(meta, view_key, g, spread, bounds, bench, lender)
        key = (int(row["credit_score"]), int(row["term_months"]))
        if extras is not None and key not in counts:
            counts[key] = _similar_count(extras, {**offer, "credit_score": key[0], "term_months": key[1]})
        cells.append([round(float(a["typical"] + bench), 4), round(float(a["low"] + bench), 2),
                      round(float(a["high"] + bench), 2), a["flag"], counts.get(key)])
    return {"scores": scores, "terms": terms, "downs": downs, "price": price, "amount": amount,
            "offer_apr": float(offer["offered_apr_pct"]), "start": [s0, t0, 0.0], "thin": THIN, "cells": cells}


def _short(feature: str, value: float) -> str:
    """Short waterfall label for one input of the offer."""
    if feature == "credit_score":
        return f"Credit score {value:.0f}"
    if feature == "is_used":
        return "Used car" if value >= 0.5 else "New car"
    if feature == "vehicle_age":
        return "This year's model" if value <= 0 else f"Car {value:.0f} year{'s' if value != 1 else ''} old"
    if feature == "amount_financed":
        return f"Borrowing ${value:,.0f}"
    if feature == "ltv":
        return f"Loan {value:.0%} of car value"
    if feature == "term_months":
        return f"{value:.0f}-month term"
    return feature


def _describe(feature: str, value: float, typical: bool = False) -> str:
    if feature == "credit_score":
        return f"a typical credit score of {value:.0f}" if typical else f"Your credit score of {value:.0f}"
    if feature == "is_used":
        word = "used" if value >= 0.5 else "new"
        return f"buying {word}" if typical else f"Buying {word}"
    if feature == "vehicle_age":
        return f"a typical {value:.0f}-year-old car" if typical else f"A car {value:.0f} years old"
    if feature == "amount_financed":
        return f"borrowing a typical ${value:,.0f}" if typical else f"Borrowing ${value:,.0f}"
    if feature == "ltv":
        return f"a typical {value:.0%} of the car's value" if typical else f"Borrowing {value:.0%} of the car's value"
    if feature == "term_months":
        return f"a typical {value:.0f}-month term" if typical else f"A {value:.0f}-month term"
    return f"{feature} = {value}"
