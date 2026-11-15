"""Write app/model/extras.json: the small tables the app's checks need beyond the quantile models.

- similar-loan counts: the cleaned loans the models learned from (the same 391,511 the notebook uses),
  counted by credit score (10-point bins), new/used, and term (6-month bins)
- the 5-year Treasury in the newest origination month (for the "rates haven't moved" check)
- the repayment test's late-or-charged-off rates by lender (reports/results.json)
- NCUA's credit-union and bank car-loan averages (data/benchmark/ncua_car_rates.csv, from src/fetch_ncua.py)
- each state's same-lender price gap and whether it survived the Holm correction (Explore tab map)
- median APR by month, lender, credit tier and new/used, cells of 30+ loans (Explore tab tracker)

Run after the notebook: .venv/bin/python src/build_extras.py
"""
import json
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import mc  # noqa: E402

SCORE_BIN, TERM_BIN = 10, 6
S_LO, S_HI = mc.DOMAIN["credit_score"]
T_LO, T_HI = mc.DOMAIN["term_months"]

meta = json.loads((ROOT / "app" / "model" / "meta.json").read_text())
results = json.loads((ROOT / "reports" / "results.json").read_text())

bench = mc.load_benchmark()
d, _ = mc.clean(mc.load_raw(), bench)
d = mc.add_features(d, bench)
if len(d) != results["n_loans_used"]:
    raise SystemExit(f"{len(d)} cleaned loans, but results.json used {results['n_loans_used']}; rerun the notebook first.")

s_idx = ((d["credit_score"] - S_LO) // SCORE_BIN).astype(int)
t_idx = ((d["term_months"] - T_LO) // TERM_BIN).astype(int)
counts = np.zeros((2, (S_HI - S_LO) // SCORE_BIN + 1, (T_HI - T_LO) // TERM_BIN + 1), dtype=int)
np.add.at(counts, (d["is_used"].to_numpy(), s_idx.to_numpy(), t_idx.to_numpy()), 1)
assert counts.sum() == len(d)

newest = meta["newest_origination_month"]
ncua = pd.read_csv(ROOT / "data" / "benchmark" / "ncua_car_rates.csv")
repay = results["repayment_test"]

extras = {
    "n_loans": int(len(d)), "n_deals": int(d["deal"].nunique()), "n_lenders": int(d["issuer"].nunique()),
    "similar_counts": {"score_low": S_LO, "score_bin": SCORE_BIN, "term_low": T_LO, "term_bin": TERM_BIN,
                       "counts_by_used_score_term": counts.tolist()},
    "treasury_newest_month": newest,
    "treasury_newest_pct": float(bench[newest]),
    # Months after the training data, for a recalibrated lender's "rates haven't moved" check.
    "treasury_by_month": {m: round(float(v), 4) for m, v in bench.items() if m >= newest},
    "treasury_passthrough": results["treasury_passthrough"],
    "repayment": {
        "months_observed_median": repay["months_observed_median"],
        "by_group": {g["group"].replace("all lenders", "all"): {
            "bad_rate_high": g["bad_rate_high"], "bad_rate_other": g["bad_rate_other"],
            "high_priced_loans": g["high_priced_loans"], "other_loans": g["other_loans"]} for g in repay["by_group"]},
    },
    "ncua": {"rate_date": str(ncua["rate_date"].iloc[0]), "quarter": str(ncua["quarter"].iloc[0]),
             "source_url": str(ncua["source_url"].iloc[0]),
             "rows": ncua[["new_or_used", "term_months", "credit_union_pct", "bank_pct"]].to_dict("records")},
}
# Explore tab 1: each state's same-lender price gap (results.json `state_both`). "holds" = its interval
# excludes zero and the notebook's Holm correction didn't drop it; the count must match the notebook's.
holm = next(v for v in results["state_multiple_testing"] if v["view"] == "same lender")
dropped = {x.strip() for x in holm["dropped_by_holm"].split(",") if x.strip()}
states = {}
for row in results["state_both"]:
    raw = row["ci_low_B"] > 0 or row["ci_high_B"] < 0
    states[row["state"]] = {"gap": round(row["gap_same_lender"], 3), "ci_low": round(row["ci_low_B"], 3),
                            "ci_high": round(row["ci_high_B"], 3), "loans": int(row["loans"]),
                            "holds": bool(raw and row["state"] not in dropped)}
n_raw = sum(1 for r in results["state_both"] if r["ci_low_B"] > 0 or r["ci_high_B"] < 0)
n_hold = sum(v["holds"] for v in states.values())
if (n_raw, n_hold) != (holm["significant_raw"], holm["significant_after_holm"]):
    raise SystemExit(f"state counts {n_raw}/{n_hold} don't match the notebook's "
                     f"{holm['significant_raw']}/{holm['significant_after_holm']}")
extras["states"] = {"view": "same lender", "tested": holm["states_tested"], "holds": n_hold, "by_state": states}

# Explore tab 2: median APR by origination month, lender, credit tier and new/used (cells under 30 loans left out).
MIN_CELL = 30
g = (d.assign(tier=d["tier"].astype(str))
      .groupby(["origination_month", "issuer", "tier", "is_used"], observed=True)["apr_pct"].agg(["median", "size"]))
g = g[g["size"] >= MIN_CELL]
months = sorted(d["origination_month"].unique())
tracker = {}
for (month, issuer, tier_name, used), row in g.iterrows():
    key = f"{tier_name}|{int(used)}"
    tracker.setdefault(key, {}).setdefault(issuer, [None] * len(months))[months.index(month)] = round(float(row["median"]), 2)
extras["tracker"] = {"months": months, "min_loans": MIN_CELL, "series": tracker}

out = ROOT / "app" / "model" / "extras.json"
# Each lender's held-back test loans (notebook, robust_by_lender): the same-lender view's typical-price miss next to
# the rule of thumb's, so the app can say how the check did on that lender's own loans. A lender missing here had
# no loans in the test months.
extras["lender_tests"] = {r["lender"]: {"loans": int(r["loans"]), "miss_pts": round(float(r["same_lender_MAE"]), 2),
                                        "rule_miss_pts": round(float(r["B1_rule_MAE"]), 2)}
                          for r in results["robust_by_lender"]}
# Lenders with no loans in the test months are tested instead on a later deal the model never saw
# (src/later_deals.py); a lender whose later deals hold only promotional loans is marked so the app can say why.
later_path = ROOT / "reports" / "later_deals.json"
later = json.loads(later_path.read_text())["deals"] if later_path.exists() else {}
for r in sorted(later.values(), key=lambda r: -r["loans"]):
    k = r["lender"]
    if r["loans"] and k not in extras["lender_tests"]:
        extras["lender_tests"][k] = {"loans": r["loans"], "miss_pts": round(float(r["same_lender"]["model_mae"]), 2),
                                     "rule_miss_pts": round(float(r["same_lender"]["b1_mae"]), 2), "later_deal": True}
    elif not r["loans"] and k not in extras["lender_tests"]:
        extras["lender_tests"][k] = {"loans": 0, "later_deals_all_promotional": True}
out.write_text(json.dumps(extras, indent=1))
print(f"{len(d):,} loans; Treasury {newest} = {extras['treasury_newest_pct']:.3f}%; "
      f"NCUA {extras['ncua']['rate_date']}; {out.stat().st_size:,} bytes -> {out.relative_to(ROOT)}")
