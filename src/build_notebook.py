"""Write notebooks/MarkupCheck.ipynb from the cells below.
Run: .venv/bin/python src/build_notebook.py
then: .venv/bin/jupyter nbconvert --to notebook --execute --inplace notebooks/MarkupCheck.ipynb
"""
import pathlib

import nbformat as nbf

ROOT = pathlib.Path(__file__).resolve().parent.parent
cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip()))  # noqa: E731
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip()))  # noqa: E731

md("""
# MarkupCheck — is a car-loan rate fair for someone like me?

**Track:** Finance · Veritas AI International High School Hackathon 2026

A buyer at a dealership is offered an APR. MarkupCheck compares it with real auto loans that were packaged into public bonds, whose loan-level data lenders must file with the SEC (Regulation AB II, Form ABS-EE, exhibit EX-102). It shows the range similar loans received, where the offer falls, what the difference costs, and whether the offer is above or well above similar loans.

**This project is a prototype and is not financial advice.**

**How to run in Google Colab:** clone this project's GitHub repository (`!git clone` followed by its URL, then `%cd` into the folder), run `!pip install -r requirements.txt`, restart the runtime (Runtime → Restart session) so the pinned numpy and pandas load, then run all cells. The parsed loan tables in `data/parquet/` are produced by the scripts in `data/raw/<lender>/` from SEC EDGAR.
""")

code("""
import sys, json, pathlib
import numpy as np, pandas as pd
ROOT = pathlib.Path.cwd().parent if pathlib.Path.cwd().name == "notebooks" else pathlib.Path.cwd()
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "app"))
import mc
pd.set_option("display.width", 180); pd.set_option("display.max_columns", 40)
RESULTS = {}
""")

md("""
## 1. Data: every loan in each deal's first pool filing

Each bond deal files its whole pool of loans once, before the deal is sold, and then a monthly update. Monthly files drop loans that were paid off or charged off, which would hide the riskiest, highest-APR loans, so we use only each deal's **first pool filing**. The manifests record which filing that is and why.
""")

code("""
raw = mc.load_raw()
manifests = {p.parent.name: json.loads(p.read_text()) for p in sorted((ROOT / "data" / "parquet").glob("*/manifest.json"))}
deal_rows = []
for issuer, m in manifests.items():
    for dl in m["deals"]:
        deal_rows.append({"issuer": issuer, "deal": dl["deal"], "filing_date": dl["filing_date"],
                          "loans_written": dl["rows_written"], "origination_months": f"{dl['origination_month_min']} to {dl['origination_month_max']}"})
deals = pd.DataFrame(deal_rows)
display(deals)
print("loans loaded:", len(raw))
codes = {c: raw[c].astype(str).value_counts().head(8).to_dict() for c in ["subvented", "interest_rate_type_code", "new_used_code", "credit_score_type"]}
codes
""")

md("""
## 2. Cleaning — every removed row is counted

Promotional (subvented) loans are removed because a manufacturer-subsidised rate is not a market price. Only fixed-rate loans with a consumer credit-bureau score are kept, and only loans originated within 12 months before their deal's first pool filing (older loans still in a pool are survivors of years of payoffs and defaults).
""")

code("""
bench = mc.load_benchmark()
clean, drops = mc.clean(raw, bench)
display(drops)
d = mc.add_features(clean, bench)
RESULTS["n_loans_parsed"] = int(len(raw)); RESULTS["n_loans_used"] = int(len(d))
RESULTS["drops"] = drops.to_dict(orient="records")
d[["apr_pct", "treasury_5y_pct", "spread", "credit_score", "amount_financed", "ltv", "term_months", "vehicle_age"]].describe().round(2)
""")

md("""
## 3. Target and time split

**Target:** the loan's APR minus the average 5-year US Treasury yield in its origination month (the "spread"). This removes market-wide rate moves, so loans from different months can be compared.

**Split by time, never at random:** the earliest origination months train the model, the next block calibrates it, and the latest months are the test set it never sees. The calibration months are split in two at random: one half sets the width of the range (and the percentile correction), the other half sets the flag threshold and was used to choose between the two models in section 7b.
""")

code("""
split = mc.time_split(d)
d = mc.apply_split(d, split)
for k, v in split.items():
    print(f"{k:6s} {v[0]} to {v[-1]} ({len(v)} months)")
display(pd.crosstab(d["origination_month"].str[:4], d["issuer"]))
display(pd.crosstab(d["set"], d["issuer"], margins=True))
per_month = d[d.set == "test"].groupby("origination_month")["issuer"].nunique()
print("test months with fewer than 2 lenders:", list(per_month[per_month < 2].index))
RESULTS["split"] = {k: [v[0], v[-1], len(v)] for k, v in split.items()}
RESULTS["n_by_set"] = d["set"].value_counts().to_dict()
assert not set(mc.FEATURES) & set(mc.NOT_INPUTS), "an audit-only or leaking column is a model input"
""")

md("""
## 4. Baselines and the model

* **B0:** one overall range for everybody (the 10th, 50th and 90th percentile spread in the training months).
* **B1:** the range for your credit tier (Experian's five bands) and new vs used — the rule of thumb a buyer gets from a rate table.
* **Model:** gradient-boosted quantile regression (scikit-learn `HistGradientBoostingRegressor`, quantile loss) at 19 quantiles from 5% to 95%, using credit score, new/used, vehicle age, amount financed, loan-to-value and term. Payment-to-income is **not** used: the payment depends on the APR, so it would leak the answer. State and lender are **not** used: they are kept for the fairness checks.
* **Settings:** fixed values in `src/mc.py` (learning rate 0.06, up to 400 trees with 31 leaves, at least 200 loans per leaf, L2 penalty 1.0). They were not tuned: there is no search over settings anywhere in the code. Early stopping holds out a random 10% of the training loans, not the latest months.
""")

code("""
train, cal_w, cal_f, test = (d[d.set == s] for s in ["train", "cal_width", "cal_flag", "test"])
b0 = mc.baseline_b0(train); b1 = mc.baseline_b1(train)
display(b1.round(2))
models = mc.fit_quantile_models(train)
alphas = sorted(models)
iL, iM, iH = mc.col(alphas, mc.LO), mc.col(alphas, 0.5), mc.col(alphas, mc.HI)
print("fitted", len(models), "quantile models on", len(train), "loans")
""")

md("""
## 5. Results on the unseen test months

Conformal calibration widens the model's 10%–90% range by a fixed amount (`qhat`) learned on calibration loans, so that about 80% of calibration loans fall inside. Whether that still holds on the later test months is **measured** below, not assumed.
""")

code("""
qw = mc.predict_grid(models, cal_w)
qhat = mc.conformal_qhat(qw[:, iL], qw[:, iH], cal_w["spread"].to_numpy())
qt = mc.predict_grid(models, test)
y = test["spread"].to_numpy()
pb1 = mc.predict_b1(b1, b0, test)
n = len(y)
rows = []
for name, lo, mid, hi in [
    ("B0 one range for everyone", np.full(n, b0[mc.LO]), np.full(n, b0[0.5]), np.full(n, b0[mc.HI])),
    ("B1 credit tier x new/used", pb1.q_lo.to_numpy(), pb1.q50.to_numpy(), pb1.q_hi.to_numpy()),
    ("Model, before calibration", qt[:, iL], qt[:, iM], qt[:, iH]),
    ("Model + conformal calibration", qt[:, iL] - qhat, qt[:, iM], qt[:, iH] + qhat)]:
    im = mc.interval_metrics(y, lo, hi)
    rows.append({"method": name, "MAE_points": np.mean(np.abs(y - mid)), "pinball_10": mc.pinball(y, lo, mc.LO),
                 "pinball_50": mc.pinball(y, mid, 0.5), "pinball_90": mc.pinball(y, hi, mc.HI),
                 "coverage_of_80pct_range": im["coverage"], "mean_width_points": im["mean_width"]})
metrics = pd.DataFrame(rows)
display(metrics.round(3))
print(f"qhat = {qhat:.3f} points; test loans = {n}")
RESULTS["qhat"] = qhat; RESULTS["metrics_test"] = metrics.to_dict(orient="records")
""")

md("""
### Is the "percentile" honest?

For every test loan we compute where its real APR falls in the predicted distribution. If the percentiles are honest, about 10% of loans should land at or below the 10th percentile, 50% at or below the 50th, and so on. We also tried a correction fitted on the calibration loans (map each raw percentile to the share of calibration loans at or below it). On the test months it made things **worse**, because prices drifted between the calibration and test months, so the app uses the raw percentile. The raw percentile is close to honest in the upper tail (where markup questions live) but too low in the lower tail: in late 2025, more loans were priced at the cheap end than the model expected.
""")

code("""
pct_raw = mc.percentile_from_grid(qt, alphas, y)
raw_cal = mc.percentile_from_grid(qw, alphas, cal_w["spread"].to_numpy())
recal_x, recal_y = mc.percentile_recal_table(raw_cal)
pct_model = np.interp(pct_raw, recal_x, recal_y)
b1_sorted = {k: np.sort(g["spread"].to_numpy()) for k, g in train.groupby(["tier", "is_used"], observed=True)}
all_sorted = np.sort(train["spread"].to_numpy())
def b1_pct(row_tier, row_used, v):
    arr = b1_sorted.get((row_tier, row_used), all_sorted)
    return 100 * np.searchsorted(arr, v) / len(arr)
pct_b1 = np.array([b1_pct(t, u, v) for t, u, v in zip(test["tier"], test["is_used"], y)])
ps = [10, 25, 50, 75, 90]
pit = pd.DataFrame({"percentile p": ps,
                    "share at or below p — model raw": [np.mean(pct_raw <= p) for p in ps],
                    "share — model corrected": [np.mean(pct_model <= p) for p in ps],
                    "share — B1 rule": [np.mean(pct_b1 <= p) for p in ps]})
display(pit.round(3))
pit_err = {c: float(np.mean(np.abs(pit[c] - pit["percentile p"] / 100))) for c in pit.columns[1:]}
print("mean absolute error vs ideal:", {k: round(v, 3) for k, v in pit_err.items()})
RESULTS["pit"] = pit.to_dict(orient="records"); RESULTS["pit_error"] = pit_err
""")

md("""
## 6. Can a buyer detect a markup from public data alone? (injection test)

We don't observe dealer markups directly, so we test detection power: add +1.0, +2.0 or +2.5 percentage points to a random 10% of test loans (fixed seed) and count how many the flag catches (recall) and how many flags are right (precision).

The app has two levels. **"High"** means above the calibrated range. **"Well above similar loans"** means more than `delta` points above it, where `delta` is the smallest margin that flags no more than 2.5% of ordinary calibration loans (a false-alarm budget set before looking at test loans).

Two honesty checks:
* **Baseline:** the same test for the B1 rule (flag when above the tier × new/used 90th percentile, with its own `delta` chosen the same way).
* **Recall on new catches:** some loans are above the range even without a markup. "recall_new" counts only marked-up loans that were not already flagged before the markup was added.

Two assumptions to keep in mind:
* **Real loans may already carry a markup.** "Typical" means typical of real loans, markups included. The test asks whether an *extra* markup stands out, and some "false alarms" may be real markups. CarMax is both the dealer and the lender on its own loans, so the classic dealer markup may work differently there.
* **The markup sizes (+1, +2, +2.5 points) and the 10% share are our assumptions**, chosen to span commonly quoted dealer-markup sizes; no official source gives a typical size. Section 7d repeats the test at the caps a 2016 federal order set for Toyota Motor Credit (1.25 and 1.00 points). Section 7c shows how precision changes if more or fewer loans are marked up.
""")

code("""
qf = mc.predict_grid(models, cal_f)
upper_f = qf[:, iH] + qhat
delta = mc.tune_delta_false_alarm(cal_f["spread"].to_numpy(), upper_f, target=0.025)
pb1_f = mc.predict_b1(b1, b0, cal_f)
delta_b1 = mc.tune_delta_false_alarm(cal_f["spread"].to_numpy(), pb1_f.q_hi.to_numpy(), target=0.025)
print(f"delta (model) = {delta} points; delta (B1 rule) = {delta_b1} points")
upper_t = qt[:, iH] + qhat
inj = []
for method, up, dl in [("B1 rule: well above tier range", pb1.q_hi.to_numpy(), delta_b1),
                       ("Model: 'high' (above range)", upper_t, 0.0),
                       ("Model: 'well above' (range + delta)", upper_t, delta)]:
    for size in [1.0, 2.0, 2.5]:
        r = mc.injection_run(y, up, dl, size)
        inj.append({"method": method, "markup_points": size, "precision": r["precision"], "recall": r["recall"],
                    "recall_new": r["recall_new"], "untouched_loans_flagged": r["untouched_flagged_share"]})
inj = pd.DataFrame(inj)
display(inj.round(3))
by_group = []
r = mc.injection_run(y, upper_t, delta, 2.0)
tmp = pd.DataFrame({"tier": test["tier"].astype(str).to_numpy(), "used": test["is_used"].map({0: "new", 1: "used"}).to_numpy(),
                    "inj": r["_injected"], "flag": r["_flagged"], "before": r["_before"]})
for (tier, used), g in tmp.groupby(["tier", "used"]):
    by_group.append({"tier": tier, "new_or_used": used, "loans": len(g), "injected": int(g.inj.sum()),
                     **mc.detection_scores(g.inj, g.flag, g.before)})
by_group = pd.DataFrame(by_group)
by_group["tier"] = pd.Categorical(by_group["tier"], mc.TIER_ORDER, ordered=True)
by_group = by_group.sort_values(["tier", "new_or_used"]).reset_index(drop=True)
print("Model 'well above', +2.0 points, by credit tier and new/used:"); display(by_group.round(3))
RESULTS.update({"delta": delta, "delta_b1": delta_b1, "injection": inj.to_dict(orient="records"),
                "injection_by_group_2pts": by_group.astype({"tier": str}).to_dict(orient="records")})
""")

md("""
## 7. Fairness on groups the model never sees, and reliability by credit tier

The SEC files contain **no race, sex or age**, so protected groups can't be audited directly. Two groups are deliberately kept out of the model so they can be audited: the borrower's **state**, and the **lender**. For each loan, the residual is its real spread minus the model's typical (median) spread for its profile. We report each group's **gap versus the average loan**: its mean residual minus the overall mean residual, so a positive gap means that group paid more than similar borrowers on average. Confidence intervals come from 500 bootstrap resamples.

Separately, we check whether the tool is equally **reliable** for every credit tier (coverage and width of its range). Credit score is a model input, so this is a reliability check, not the non-input fairness check.
""")

code("""
inside = (y >= qt[:, iL] - qhat) & (y <= qt[:, iH] + qhat)
tr = test.assign(resid=y - qt[:, iM], inside=inside)
print(f"overall mean residual on test (model A): {tr.resid.mean():.3f} points")
issuer_tbl = mc.centered_group_table(tr, "issuer", "resid", 1)
state_tbl = mc.centered_group_table(tr, "state", "resid", 300)
print("By lender (not a model input):"); display(issuer_tbl.round(3))
print("By state, states with at least 300 test loans (not a model input):"); display(state_tbl.round(3))
rel = []
for (tier, used), g in tr.assign(b1_mid=pb1.q50.to_numpy(), b1_lo=pb1.q_lo.to_numpy(), b1_hi=pb1.q_hi.to_numpy(),
                                 lo=qt[:, iL] - qhat, hi=qt[:, iH] + qhat, mid=qt[:, iM]).groupby(["tier", "is_used"], observed=True):
    rel.append({"tier": tier, "new_or_used": "used" if used else "new", "loans": len(g),
                "model_coverage": g["inside"].mean(), "model_mean_width": (g.hi - g.lo).mean(),
                "B1_coverage": ((g.spread >= g.b1_lo) & (g.spread <= g.b1_hi)).mean(), "B1_mean_width": (g.b1_hi - g.b1_lo).mean(),
                "model_MAE": (g.spread - g.mid).abs().mean(), "B1_MAE": (g.spread - g.b1_mid).abs().mean()})
rel = pd.DataFrame(rel); display(rel.round(3))
RESULTS.update({"fairness_issuer": issuer_tbl.to_dict(orient="records"), "fairness_state": state_tbl.to_dict(orient="records"),
                "reliability_by_tier": rel.astype({"tier": str}).to_dict(orient="records"), "mean_residual_test_A": float(tr.resid.mean())})
""")

md("""
## 7b. One measured improvement: compare with the same lender

A dealer markup is added on top of the rate a **specific lender** approved, so the sharper test compares an offer with that lender's own similar loans. Model B adds the lender as an input; the app uses it only when the buyer names the lender on the contract (Model A, the whole-market view, never sees the lender, so it stays usable for the lender check above).

**How the choice was made, honestly:** we first compared the two on the test months while building, which is a form of peeking. To check the choice properly, the first table compares them on the calibration-flag half (loans neither model trained on, from before the test months). The second table is the final test-month evaluation.

The state check is repeated with Model B: state gaps that remain after accounting for the lender can't be explained by which lenders operate in which states.
""")

code("""
assert not (set(mc.FEATURES_B) - {"lender_code"}) & set(mc.NOT_INPUTS)
modelsB = mc.fit_quantile_models(train, features=mc.FEATURES_B)
qwB = mc.predict_grid(modelsB, cal_w, mc.FEATURES_B)
qhatB = mc.conformal_qhat(qwB[:, iL], qwB[:, iH], cal_w["spread"].to_numpy())
qfB = mc.predict_grid(modelsB, cal_f, mc.FEATURES_B)
qtB = mc.predict_grid(modelsB, test, mc.FEATURES_B)
deltaB = mc.tune_delta_false_alarm(cal_f["spread"].to_numpy(), qfB[:, iH] + qhatB, target=0.025)
yf = cal_f["spread"].to_numpy()
sel, cmp_rows = [], []
for name, qc, qtt, qh, dl in [("A: whole market", qf, qt, qhat, delta), ("B: same lender", qfB, qtB, qhatB, deltaB)]:
    imc = mc.interval_metrics(yf, qc[:, iL] - qh, qc[:, iH] + qh)
    rc = mc.injection_run(yf, qc[:, iH] + qh, 0.0, 2.0)
    sel.append({"model": name, "MAE_points": np.mean(np.abs(yf - qc[:, iM])), "pinball_50": mc.pinball(yf, qc[:, iM], 0.5),
                "coverage_of_80pct_range": imc["coverage"], "mean_width_points": imc["mean_width"],
                "recall_new_2pt_above_range": rc["recall_new"], "precision_2pt_above_range": rc["precision"]})
    im = mc.interval_metrics(y, qtt[:, iL] - qh, qtt[:, iH] + qh)
    rt = mc.injection_run(y, qtt[:, iH] + qh, dl, 2.0)
    cmp_rows.append({"model": name, "MAE_points": np.mean(np.abs(y - qtt[:, iM])), "coverage_of_80pct_range": im["coverage"],
                     "mean_width_points": im["mean_width"], "qhat": qh, "delta": dl, "untouched_loans_flagged_well_above": rt["untouched_flagged_share"],
                     "precision_2pt_well_above": rt["precision"], "recall_2pt_well_above": rt["recall"], "recall_new_2pt_well_above": rt["recall_new"]})
sel = pd.DataFrame(sel); cmp = pd.DataFrame(cmp_rows)
print("Selection evidence — calibration-flag half (before the test months):"); display(sel.round(3))
print("Final evaluation — test months:"); display(cmp.round(3))
rec = []
for name, qtt, qh, dl in [("A: whole market", qt, qhat, delta), ("B: same lender", qtB, qhatB, deltaB)]:
    rt = mc.injection_run(y, qtt[:, iH] + qh, dl, 2.0)
    t2 = pd.DataFrame({"tier": test["tier"].astype(str).to_numpy(), "i": rt["_injected"], "f": rt["_flagged"], "b": rt["_before"]})
    for t, g in t2.groupby("tier"):
        s = mc.detection_scores(g.i, g.f, g.b)
        rec.append({"model": name, "tier": t, "recall_2pt": s["recall"], "recall_new_2pt": s["recall_new"],
                    "precision_2pt": s["precision"]})
rec = pd.DataFrame(rec); rec["tier"] = pd.Categorical(rec["tier"], mc.TIER_ORDER, ordered=True)
rec = rec.sort_values(["tier", "model"]).reset_index(drop=True); display(rec.round(3))
trB = test.assign(residB=y - qtB[:, iM])
print(f"overall mean residual on test (model B): {trB.residB.mean():.3f} points")
sB = mc.centered_group_table(trB, "state", "residB", 300).rename(columns={"gap_vs_average_points": "gap_same_lender", "ci_low": "ci_low_B", "ci_high": "ci_high_B"})
state_both = state_tbl.rename(columns={"gap_vs_average_points": "gap_whole_market"})[["state", "loans", "gap_whole_market"]].merge(sB.drop(columns="loans"), on="state")
state_both = state_both.sort_values("gap_same_lender").reset_index(drop=True)
display(state_both.round(3))
print("range of state gaps (max minus min): whole market", round(state_both.gap_whole_market.max() - state_both.gap_whole_market.min(), 3),
      "| same lender", round(state_both.gap_same_lender.max() - state_both.gap_same_lender.min(), 3))
RESULTS.update({"qhatB": qhatB, "deltaB": deltaB, "selection_cal": sel.to_dict(orient="records"), "compare_A_B": cmp.to_dict(orient="records"),
                "recall_by_tier_A_B": rec.astype({"tier": str}).to_dict(orient="records"), "state_both": state_both.to_dict(orient="records")})
""")

md("""
## 7c. How sure are these numbers?

Single numbers can hide luck. These checks add uncertainty and answer the questions a reviewer would ask:

1. **By month and by lender.** Does the model beat the rule of thumb in every test month and at every lender, or only on average? The lender mix shifts across the test months (Santander's share rises), so the headline error depends partly on which lender dominates.
2. **Paired bootstrap** (1,000 resamples of test loans) for the error differences. Loans from the same dealer and month aren't independent, so these intervals are too narrow; the month-by-month consistency is the stronger evidence.
3. **The injection test over 50 random seeds**, so the result doesn't hang on one random draw.
4. **Markup detection at the same false-alarm rate.** The model and the rule were each given a 2.5% false-alarm budget on calibration loans, but on the test months they flag different shares of ordinary loans. Here each method's threshold is set on the test months to flag exactly the same share, for comparison only (the app doesn't use these thresholds).
5. **Precision if more or fewer loans are marked up.** Precision depends on how common markups are; the test assumed 10%.
6. **Trees vs a straight line.** A linear quantile model on the same six inputs separates the gain from the trees from the gain from the extra inputs. Both are fitted on the same 30,000 training loans (the linear solver is slow on all of them).
7. **39 state gaps at once.** About 2 of 39 intervals would miss zero by chance alone, so we apply a Holm correction (normal approximation for each state's mean).
8. **Do car-loan rates move point for point with the Treasury rate?** The app assumes so when today's Treasury rate is outside the data's months. Within each lender × credit tier × new/used group, we measure how much the average APR moved per point of Treasury rate across months, with a bootstrap over months. Other changes over time (lenders tightening credit, for example) also move rates, so this is a rough check.
""")

code("""
from scipy.stats import norm
from sklearn.linear_model import QuantileRegressor
rng = np.random.default_rng(mc.SEED)
err_A, err_B, err_1 = np.abs(y - qt[:, iM]), np.abs(y - qtB[:, iM]), np.abs(y - pb1.q50.to_numpy())
frame = pd.DataFrame({"month": test["origination_month"].to_numpy(), "lender": test["issuer"].to_numpy(),
                      "eA": err_A, "eB": err_B, "e1": err_1, "inside": inside})
agg = dict(loans=("eA", "size"), model_MAE=("eA", "mean"), same_lender_MAE=("eB", "mean"), B1_rule_MAE=("e1", "mean"), model_coverage=("inside", "mean"))
by_month = frame.groupby("month").agg(**agg).reset_index()
by_month["santander_share"] = by_month["month"].map(pd.crosstab(frame.month, frame.lender, normalize="index").get("santander", 0))
by_lender = frame.groupby("lender").agg(**agg).reset_index()
print("By test month:"); display(by_month.round(3))
print("By lender:"); display(by_lender.round(3))
months_A_beats_B1 = int((by_month.model_MAE < by_month.B1_rule_MAE).sum())
months_B_beats_A = int((by_month.same_lender_MAE < by_month.model_MAE).sum())
print(f"model beats the B1 rule in {months_A_beats_B1} of {len(by_month)} months; same-lender model beats the model in {months_B_beats_A} of {len(by_month)}")

diffs = np.column_stack([err_1 - err_A, err_A - err_B])
boots = np.empty((1000, 2))
for b in range(1000):
    boots[b] = diffs[rng.integers(0, n, n)].mean(axis=0)
lo_ci, hi_ci = np.percentile(boots, [2.5, 97.5], axis=0)
paired = pd.DataFrame({"difference": ["B1 rule error minus model error", "model error minus same-lender model error"],
                       "points": diffs.mean(axis=0), "ci_low": lo_ci, "ci_high": hi_ci})
display(paired.round(3))

seed_runs = pd.DataFrame([{k: mc.injection_run(y, upper_t, delta, 2.0, seed=s)[k] for k in ("precision", "recall", "recall_new")}
                          for s in range(50)])
seeds = pd.DataFrame({"measure": seed_runs.columns, "mean": seed_runs.mean().to_numpy(),
                      "low_2.5pct": seed_runs.quantile(0.025).to_numpy(), "high_97.5pct": seed_runs.quantile(0.975).to_numpy()})
print("Model 'well above', +2.0 points, 50 random seeds:"); display(seeds.round(3))

up_B = qtB[:, iH] + qhatB
fa_model = float(np.mean(y > upper_t + delta))
matched = []
for fa in sorted({0.01, 0.02, round(fa_model, 4), 0.05, 0.10}):
    for name, up in [("B1 rule", pb1.q_hi.to_numpy()), ("Model (whole market)", upper_t), ("Same-lender model", up_B)]:
        r = mc.injection_run(y, up, float(np.quantile(y - up, 1 - fa)), 2.0)
        matched.append({"false_alarm_rate": fa, "method": name, "recall_new_2pt": r["recall_new"], "precision_2pt": r["precision"]})
matched = pd.DataFrame(matched)
print(f"Matched false-alarm rates (the model's own 'well above' rate on test is {fa_model:.3f}):"); display(matched.round(3))

r2 = mc.injection_run(y, upper_t, delta, 2.0)
prevalence = pd.DataFrame([{"share_of_loans_marked_up": p,
                            "precision_2pt": r2["recall"] * p / (r2["recall"] * p + r2["untouched_flagged_share"] * (1 - p))}
                           for p in [0.02, 0.05, 0.10, 0.30]])
display(prevalence.round(3))

lin_train = train.sample(30000, random_state=mc.SEED)
lin_rows = []
lin_fits = {"Linear quantile (same 6 inputs)": {a: QuantileRegressor(quantile=a, alpha=0.0, solver="highs").fit(lin_train[mc.FEATURES], lin_train["spread"])
                                                for a in (mc.LO, 0.5, mc.HI)},
            "Trees (same 6 inputs)": mc.fit_quantile_models(lin_train, alphas=[mc.LO, 0.5, mc.HI])}
for name, ms in lin_fits.items():
    pw = {a: ms[a].predict(cal_w[mc.FEATURES]) for a in ms}
    qh_ = mc.conformal_qhat(pw[mc.LO], pw[mc.HI], cal_w["spread"].to_numpy())
    pt = {a: ms[a].predict(test[mc.FEATURES]) for a in ms}
    im_ = mc.interval_metrics(y, pt[mc.LO] - qh_, pt[mc.HI] + qh_)
    lin_rows.append({"method": name + ", 30,000 training loans", "MAE_points": float(np.mean(np.abs(y - pt[0.5]))),
                     "coverage_of_80pct_range": im_["coverage"], "mean_width_points": im_["mean_width"]})
lin_rows.append({"method": "Trees, all training loans (the app's model)", "MAE_points": float(err_A.mean()),
                 "coverage_of_80pct_range": float(inside.mean()), "mean_width_points": float(np.mean(qt[:, iH] - qt[:, iL] + 2 * qhat))})
linear = pd.DataFrame(lin_rows); display(linear.round(3))

def holm(p):
    order, m = np.argsort(p), len(p)
    adj, run = np.empty(m), 0.0
    for rank, i in enumerate(order):
        run = max(run, (m - rank) * p[i]); adj[i] = min(1.0, run)
    return adj
multi = []
for view, fr, rc in [("whole market", tr, "resid"), ("same lender", trB, "residB")]:
    g = fr.groupby("state")[rc].agg(["size", "mean", "std"]); g = g[g["size"] >= 300]
    p = 2 * norm.sf(np.abs((g["mean"] - fr[rc].mean()) / (g["std"] / np.sqrt(g["size"]))))
    raw, adj = g.index[p < 0.05], g.index[holm(p) < 0.05]
    multi.append({"view": view, "states_tested": len(g), "expected_by_chance": round(0.05 * len(g), 1), "significant_raw": len(raw),
                  "significant_after_holm": len(adj), "dropped_by_holm": ", ".join(sorted(set(raw) - set(adj))) or "none",
                  "AL_and_CT_remain": bool({"AL", "CT"} <= set(adj))})
multi = pd.DataFrame(multi); display(multi)

gm = (d.assign(bench=d.apr_pct - d.spread)
       .groupby(["issuer", "tier", "is_used", "origination_month"], observed=True)
       .agg(apr=("apr_pct", "mean"), bench=("bench", "mean"), loans=("apr_pct", "size")).reset_index())
gm = gm[gm.loans >= 50].assign(key=lambda f: f.issuer.astype(str) + "|" + f.tier.astype(str) + "|" + f.is_used.astype(str))
def passthrough(f):
    x = f.bench - f.groupby("key").bench.transform("mean"); v = f.apr - f.groupby("key").apr.transform("mean")
    return float((x * v).sum() / (x * x).sum())
by_m = {m_: f for m_, f in gm.groupby("origination_month")}
months_ = list(by_m)
pt_boot = [passthrough(pd.concat([by_m[m_] for m_ in rng.choice(months_, len(months_))], ignore_index=True)) for _ in range(500)]
treasury = {"apr_points_per_treasury_point": passthrough(gm), "ci_low": float(np.percentile(pt_boot, 2.5)),
            "ci_high": float(np.percentile(pt_boot, 97.5)), "group_months": int(len(gm)), "months": len(months_)}
print("Car-loan APR change per 1-point change in the 5-year Treasury rate (within lender x tier x new/used):",
      {k: round(v, 3) if isinstance(v, float) else v for k, v in treasury.items()})
RESULTS.update({"robust_by_month": by_month.to_dict(orient="records"), "robust_by_lender": by_lender.to_dict(orient="records"),
                "months_model_beats_B1": months_A_beats_B1, "months_same_lender_beats_model": months_B_beats_A, "n_test_months": len(by_month),
                "paired_bootstrap": paired.to_dict(orient="records"), "injection_50_seeds": seeds.to_dict(orient="records"),
                "matched_false_alarm": matched.to_dict(orient="records"), "model_false_alarm_test": fa_model,
                "precision_by_prevalence": prevalence.to_dict(orient="records"), "linear_baseline": linear.to_dict(orient="records"),
                "state_multiple_testing": multi.to_dict(orient="records"), "treasury_passthrough": treasury})
""")

md("""
## 7d. Markup sizes from a real enforcement order

Section 6 assumed markups of +1, +2 or +2.5 points. A public anchor for a realistic size: in February 2016 the CFPB and the Justice Department settled with Toyota Motor Credit over dealer markups with discriminatory effects. The order capped the markup a dealer could add to Toyota's rate at **1.25 percentage points for loans of 5 years (60 months) or less and 1.00 point for longer loans**; before, Toyota had allowed up to 2.5 points ([CFPB press release, Feb 2 2016](https://www.consumerfinance.gov/about-us/newsroom/cfpb-and-doj-reach-resolution-with-toyota-motor-credit-to-address-loan-pricing-policies-with-discriminatory-effects/)). The orders ended early in 2018 and Toyota then raised its caps ([F&I and Showroom, May 17 2018](https://www.fi-magazine.com/news/freed-from-cfpb-order-toyota-financial-to-raise-markup-caps)), so these caps are a low, rule-bound markup, not a typical one.

Here each marked-up loan gets the cap for its own term. Everything else is unchanged: the same 10% of test loans (same seed, so the same loans as the +2.0 test), the same thresholds from sections 6 and 7b, and, for the matched comparison, the model's own "well above" rate on the test months as in 7c. The +2.0 rows are recomputed next to them as a check that they match the tables above.
""")

code("""
cap_size = np.where(test["term_months"].to_numpy() <= 60, 1.25, 1.00)
print(f"test loans with term of 60 months or less (cap 1.25): {np.mean(cap_size == 1.25):.3f}; longer (cap 1.00): {np.mean(cap_size == 1.00):.3f}")
cap_rows = []
for method, up, dl in [("B1 rule: well above tier range", pb1.q_hi.to_numpy(), delta_b1),
                       ("Model: 'high' (above range)", upper_t, 0.0),
                       ("Model: 'well above' (range + delta)", upper_t, delta),
                       ("Same-lender model: 'well above' (range + delta)", up_B, deltaB)]:
    for label, size in [("Toyota-order cap (1.25 or 1.00)", cap_size), ("+2.0", 2.0)]:
        r_cap = mc.injection_run(y, up, dl, size)
        cap_rows.append({"method": method, "markup": label, "precision": r_cap["precision"], "recall": r_cap["recall"],
                         "recall_new": r_cap["recall_new"], "untouched_loans_flagged": r_cap["untouched_flagged_share"]})
caps = pd.DataFrame(cap_rows)
display(caps.round(3))
for _, cr in caps[caps.markup == "+2.0"].iterrows():
    ref = inj[(inj.method == cr.method) & (inj.markup_points == 2.0)]
    if len(ref):
        assert np.allclose(ref[["precision", "recall", "recall_new"]].to_numpy()[0], cr[["precision", "recall", "recall_new"]].to_numpy(float)), cr.method
same_two = caps[(caps.markup == "+2.0") & caps.method.str.startswith("Same-lender")][["precision", "recall", "recall_new"]].to_numpy(float)[0]
assert np.allclose(same_two, cmp.loc[1, ["precision_2pt_well_above", "recall_2pt_well_above", "recall_new_2pt_well_above"]].to_numpy(float))

cap_matched = []
for name, up in [("B1 rule", pb1.q_hi.to_numpy()), ("Model (whole market)", upper_t), ("Same-lender model", up_B)]:
    thr = float(np.quantile(y - up, 1 - round(fa_model, 4)))
    r_cap, r_two = mc.injection_run(y, up, thr, cap_size), mc.injection_run(y, up, thr, 2.0)
    cap_matched.append({"false_alarm_rate": round(fa_model, 4), "method": name, "recall_new_caps": r_cap["recall_new"],
                        "precision_caps": r_cap["precision"], "recall_new_2pt": r_two["recall_new"], "precision_2pt": r_two["precision"]})
cap_matched = pd.DataFrame(cap_matched)
assert np.allclose(cap_matched[["recall_new_2pt", "precision_2pt"]].to_numpy(float),
                   matched[matched.false_alarm_rate == round(fa_model, 4)][["recall_new_2pt", "precision_2pt"]].to_numpy(float))
print(f"Matched false-alarm rate {round(fa_model, 4)} (the model's own 'well above' rate on test):"); display(cap_matched.round(3))

r_cap = mc.injection_run(y, upper_t, delta, cap_size)
cap_term = pd.DataFrame({"term": np.where(cap_size == 1.25, "60 months or less (+1.25)", "over 60 months (+1.00)"),
                         "i": r_cap["_injected"], "f": r_cap["_flagged"], "b": r_cap["_before"]})
cap_by_term = pd.DataFrame([{"term": t, "loans": len(g), "injected": int(g.i.sum()), **mc.detection_scores(g.i, g.f, g.b)}
                            for t, g in cap_term.groupby("term")])
print("Model 'well above', Toyota-order caps, by term:"); display(cap_by_term.round(3))

cap_seed_runs = pd.DataFrame([{k: mc.injection_run(y, upper_t, delta, cap_size, seed=s)[k] for k in ("precision", "recall", "recall_new")}
                              for s in range(50)])
cap_seeds = pd.DataFrame({"measure": cap_seed_runs.columns, "mean": cap_seed_runs.mean().to_numpy(),
                          "low_2.5pct": cap_seed_runs.quantile(0.025).to_numpy(), "high_97.5pct": cap_seed_runs.quantile(0.975).to_numpy()})
print("Model 'well above', Toyota-order caps, 50 random seeds:"); display(cap_seeds.round(3))
RESULTS["injection_toyota_caps"] = {
    "caps_points": {"term_60_months_or_less": 1.25, "term_over_60_months": 1.00},
    "source": "https://www.consumerfinance.gov/about-us/newsroom/cfpb-and-doj-reach-resolution-with-toyota-motor-credit-to-address-loan-pricing-policies-with-discriminatory-effects/",
    "share_test_loans_term_60_or_less": float(np.mean(cap_size == 1.25)),
    "by_method": caps.to_dict(orient="records"), "matched_false_alarm": cap_matched.to_dict(orient="records"),
    "model_well_above_by_term": cap_by_term.to_dict(orient="records"), "model_well_above_50_seeds": cap_seeds.to_dict(orient="records")}
""")

md("""
## 8. Where it fails

The five test loans with the largest gap between the real spread and the model's typical spread, with the most likely reason.
""")

code("""
fail = tr.assign(abs_err=np.abs(tr["resid"])).sort_values("abs_err", ascending=False).head(5)
def reason(r):
    why = []
    if r.credit_score < 540: why.append("very low credit score (few such loans to learn from)")
    if r.ltv > 1.4: why.append("loan far above the car's value (add-ons)")
    if r.vehicle_age > 12: why.append("very old car")
    if r.term_months > 84: why.append("very long term")
    if not why: why.append("price driven by something the data doesn't show (e.g. the dealer, a co-signer, or the buyer's full credit file)")
    return "; ".join(why)
fail = fail.assign(likely_reason=fail.apply(reason, axis=1))
cols = ["issuer", "origination_month", "credit_score", "is_used", "vehicle_age", "amount_financed", "ltv", "term_months", "apr_pct", "resid", "likely_reason"]
display(fail[cols].round(2))
RESULTS["failures"] = fail[cols].round(3).to_dict(orient="records")
""")

md("""
## 9. Which inputs matter most (permutation importance on test loans)
""")

code("""
from sklearn.inspection import permutation_importance
sample = test.sample(min(5000, len(test)), random_state=mc.SEED)
pi = permutation_importance(models[0.5], sample[mc.FEATURES], sample["spread"], n_repeats=5, random_state=mc.SEED, scoring="neg_mean_absolute_error")
imp = pd.DataFrame({"feature": mc.FEATURES, "MAE increase when shuffled (points)": pi.importances_mean}).sort_values(by="MAE increase when shuffled (points)", ascending=False)
display(imp.round(3))
RESULTS["importance"] = imp.to_dict(orient="records")
""")

md("""
## 10. Does a high price go with worse repayment?

The three 2024 deals' loans were followed for 12 monthly filings (`data/parquet/<lender>/perf_*.parquet`). Loans are matched on **deal and asset number together** (asset numbers repeat across deals). These loans fall in the training months, so to keep the test fair each loan's "typical 90th percentile" comes from a model that never saw that loan (5-fold cross-fitting on these loans only). We compare how often loans priced above that line later went 30+ days late or were charged off, overall, by lender, and within credit tier and term.

A higher bad rate for high-priced loans would mean part of a high price reflects risk the data can't see. It could also mean a markup itself raises the payment and makes default more likely, so this test can't fully separate the two.
""")

code("""
perf_parts, unreadable = [], []
for f in sorted((ROOT / "data" / "parquet").glob("*/perf_*.parquet")):
    try:
        p = pd.read_parquet(f)
    except Exception as e:  # a file still being written by a data session
        unreadable.append(f"{f.name}: {type(e).__name__}"); continue
    issuer = f.parent.name; suffix = f.stem.split("_")[-1]
    perf_parts.append(p.assign(issuer=issuer, deal_suffix=suffix))
if unreadable:
    print("skipped unreadable performance files:", unreadable)
if not perf_parts:
    print("Repayment test not run: no monthly performance files were parsed.")
    RESULTS["repayment_test"] = "not run"
else:
    perf = pd.concat(perf_parts, ignore_index=True)
    status = pd.to_numeric(perf["current_delinquency_status"], errors="coerce")
    charged = pd.to_numeric(perf["chargedoff_principal_amount"], errors="coerce").fillna(0)
    perf["bad"] = (status.fillna(0) >= 30) | (charged > 0)
    key = ["issuer", "deal_suffix", "asset_number"]
    outcome = perf.groupby(key).agg(bad=("bad", "max"), months_seen=("reporting_period_end", "nunique")).reset_index()
    d["deal_suffix"] = d["deal"].str.split().str[-1]
    allp = d.merge(outcome, on=key, how="inner").reset_index(drop=True)
    print(f"loans matched to repayment history: {len(allp)} (from deals {sorted(allp.deal.unique())})")
    print("missing delinquency status rows in performance files:", int(status.isna().sum()))
    oof90 = mc.crossfit_quantile(allp, mc.FEATURES, alpha=0.9, folds=5)
    allp["high_priced"] = allp["spread"].to_numpy() > oof90
    allp["term_bucket"] = pd.cut(allp["term_months"], [0, 60, 72, 96])
    def rate_ci(mask):
        return mc.bootstrap_mean_ci(allp.loc[mask, "bad"].astype(float).to_numpy())
    rep_rows = []
    for name, sub in [("all lenders", np.ones(len(allp), bool))] + [(i, (allp.issuer == i).to_numpy()) for i in sorted(allp.issuer.unique())]:
        hi_m, hi_lo, hi_hi = rate_ci(sub & allp.high_priced.to_numpy())
        ot_m, ot_lo, ot_hi = rate_ci(sub & ~allp.high_priced.to_numpy())
        rep_rows.append({"group": name, "high_priced_loans": int((sub & allp.high_priced).sum()), "bad_rate_high": hi_m, "ci_high": f"{hi_lo:.3f}-{hi_hi:.3f}",
                         "other_loans": int((sub & ~allp.high_priced).sum()), "bad_rate_other": ot_m, "ci_other": f"{ot_lo:.3f}-{ot_hi:.3f}"})
    rep = pd.DataFrame(rep_rows); display(rep.round(3))
    # The pooled gap mixes lenders (Santander has both more high-priced loans and higher bad rates),
    # so also report the within-lender gaps averaged with each lender's share of loans as weights.
    gaps = rep[rep.group != "all lenders"].set_index("group").eval("bad_rate_high - bad_rate_other")
    lender_weighted_gap = float((gaps * allp.issuer.value_counts(normalize=True).reindex(gaps.index)).sum())
    pooled_gap = float(rep.bad_rate_high.iloc[0] - rep.bad_rate_other.iloc[0])
    print(f"bad-rate gap, high-priced minus other: pooled {pooled_gap:.3f}; within-lender, weighted by lender size {lender_weighted_gap:.3f}")
    # A month with no reported status counts as current. Check: drop loans with any month missing a status.
    perf["status_missing"] = status.isna()
    miss_share = {k: float(v) for k, v in perf.groupby("issuer")["status_missing"].mean().items()}
    any_missing = perf.groupby(key)["status_missing"].any().rename("any_missing").reset_index()
    keep = ~allp[key].merge(any_missing, on=key, how="left")["any_missing"].eq(True).to_numpy()
    hp = allp.high_priced.to_numpy()
    no_missing = {"loans_kept": int(keep.sum()), "bad_rate_high": float(allp.loc[keep & hp, "bad"].mean()),
                  "bad_rate_other": float(allp.loc[keep & ~hp, "bad"].mean())}
    print("share of monthly rows with no status, by lender:", {k: round(v, 3) for k, v in miss_share.items()})
    print("without loans that have any month missing a status:", {k: round(v, 3) for k, v in no_missing.items()})
    comp = allp.groupby(["tier", "term_bucket", "high_priced"], observed=True)["bad"].agg(["size", "mean"]).unstack()
    display(comp.round(3))
    comp_flat = comp.copy()
    comp_flat.columns = [f"{stat}_{'high' if h else 'other'}" for stat, h in comp_flat.columns]
    comp_flat = comp_flat.reset_index().astype({"tier": str, "term_bucket": str})
    RESULTS["repayment_test"] = {"by_group": rep.to_dict(orient="records"), "n_matched": int(len(allp)),
                                 "months_observed_median": float(allp.months_seen.median()),
                                 "pooled_gap": pooled_gap, "lender_weighted_gap": lender_weighted_gap,
                                 "missing_status_share_by_lender": miss_share, "without_missing_status": no_missing,
                                 "by_tier_term": comp_flat.to_dict(orient="records")}
""")

md("""
## 11. Save the model for the app, then run the demo examples through the app's own code
""")

code("""
import joblib
import scoring
MODEL_DIR = ROOT / "app" / "model"; MODEL_DIR.mkdir(parents=True, exist_ok=True)
for sub, ms in [("A", models), ("B", modelsB)]:
    (MODEL_DIR / sub).mkdir(exist_ok=True)
    for a, m in ms.items():
        joblib.dump(m, MODEL_DIR / sub / f"q{int(round(a * 100)):02d}.joblib")
bm = pd.read_csv(ROOT / "data" / "benchmark" / "treasury_5y_monthly.csv")
full = bm[bm.n_days >= 15].iloc[-1]
data_months = bm[bm.month.isin(d.origination_month.unique())]
names = {k: v["name"] for k, v in scoring.LENDERS.items()}
ref ={f: float(train[f].median()) for f in mc.FEATURES}
ref["is_used"] = float(train["is_used"].mode()[0])
def coverage_by_group(q, qh):
    ins = (y >= q[:, iL] - qh) & (y <= q[:, iH] + qh)
    g = pd.DataFrame({"tier": test["tier"].astype(str).to_numpy(), "used": test["is_used"].to_numpy(), "ins": ins})
    return {f"{t}|{u}": float(v) for (t, u), v in g.groupby(["tier", "used"])["ins"].mean().items()}
meta = {
    "alphas": [float(a) for a in alphas], "lo": mc.LO, "hi": mc.HI,
    "views": {
        "market": {"dir": "A", "features": mc.FEATURES, "conformal_qhat": qhat, "flag_delta": delta,
                   "coverage_by_group": coverage_by_group(qt, qhat),
                   "coverage_overall": float(cmp.loc[0, "coverage_of_80pct_range"])},
        "same_lender": {"dir": "B", "features": mc.FEATURES_B, "conformal_qhat": qhatB, "flag_delta": deltaB,
                        "coverage_by_group": coverage_by_group(qtB, qhatB),
                        "coverage_overall": float(cmp.loc[1, "coverage_of_80pct_range"]),
                        "n_loans_by_lender": {k: int(v) for k, v in d["issuer"].value_counts().items()}},
    },
    "offer_benchmark_month": full["month"], "offer_benchmark_pct": float(full["five_year_pct"]),
    "data_benchmark_min": float(data_months.five_year_pct.min()), "data_benchmark_max": float(data_months.five_year_pct.max()),
    "apr_observed_min": float(d.apr_pct.min()), "apr_observed_max": float(d.apr_pct.max()),
    "amount_max_train": float(train.amount_financed.max()), "newest_origination_month": d.origination_month.max(),
    "reference_profile": ref,
    "data_note": (f"Compared with {len(d):,} loans from {d.deal.nunique()} SEC-filed bond deals ({', '.join(sorted(names.get(i, i) for i in d.issuer.unique()))}), "
                  f"originated {d.origination_month.min()} to {d.origination_month.max()}. Prices are compared after removing the 5-year Treasury rate; "
                  f"your offer uses the {full['month']} average of {full['five_year_pct']:.2f}%."),
    "weak_spots_always": [
        "Only loans that lenders sold into public bonds are included; credit unions and many banks aren't.",
        "Your credit app may show a VantageScore, while lenders often use FICO; the two can differ.",
        "The data has no race, sex or age, and no information about the dealer, so some price differences can't be explained.",
        "A high APR can also reflect risk the data doesn't show, not only a markup."],
}
mc.save_json(meta, MODEL_DIR / "meta.json")
import importlib, markupcheck_model; importlib.reload(markupcheck_model); markupcheck_model._CACHE.clear()
# Parity check: the app's code, loading the saved files, must give the same quantile grid as the notebook.
loaded = markupcheck_model._load()
probe = test.head(200)
app_grid = markupcheck_model._grids(loaded["models"]["market"], probe[mc.FEATURES].to_dict("records"), mc.FEATURES)
assert np.allclose(app_grid, qt[:200]), "app and notebook disagree on the quantile grid"
print("parity check passed: the app's saved models reproduce the notebook's grid on 200 test loans")
jordan = {"credit_score": 660, "new_or_used": "used", "vehicle_model_year": 2019, "vehicle_price": 17500,
          "amount_financed": 18500, "term_months": 72, "offered_apr_pct": 15.9, "lender": None}
# The page-only slider grid (325 cells) is left out of the saved examples.
slim = lambda r: {k: v for k, v in r.items() if k != "whatif"}
jr = slim(markupcheck_model.predict(jordan))
assert jr["stub"] is False
print("Jordan, lender not given (whole-market view):")
for k, v in jr.items(): print(f"  {k}: {v}")
jr_s = slim(markupcheck_model.predict({**jordan, "lender": "Santander Consumer USA"}))
print("\\nJordan, lender named as Santander (same-lender view):")
for k in ["view", "range_low_pct", "range_high_pct", "typical_pct", "percentile", "flag", "range_coverage_pct", "same_lender", "market"]:
    print(f"  {k}: {jr_s[k]}")
# A second demo buyer: the lowest APRs (in 0.5-point steps) that the whole-market view calls "high" and
# "likely marked up" (shown as "well above similar loans") for this profile. Found by the model, not by hand.
sam = {"credit_score": 760, "new_or_used": "used", "vehicle_model_year": 2022, "vehicle_price": 24000,
       "amount_financed": 25000, "term_months": 60, "lender": None}
grid_aprs = np.arange(3.0, 30.01, 0.5)
# The APR doesn't change the model's output, only the comparison, so score the profile once.
bench_now = meta["offer_benchmark_pct"]
bounds = (meta["apr_observed_min"] - bench_now, meta["apr_observed_max"] - bench_now)
sam_row = markupcheck_model.features_from_offer({**sam, "offered_apr_pct": 0.0}, int(meta["offer_benchmark_month"][:4]))
sam_m = markupcheck_model._assess(meta, "market", markupcheck_model._grids(loaded["models"]["market"], [sam_row], mc.FEATURES)[0], 0.0, bounds)
sam_high = next(float(a) for a in grid_aprs if a - bench_now > sam_m["high"])
sam_apr = next(float(a) for a in grid_aprs if a - bench_now > sam_m["high"] + delta)
sr = slim(markupcheck_model.predict({**sam, "offered_apr_pct": sam_apr}))
print(f"\\nSam (score 760, used 2022 car, $25,000 for 60 months): first 'high' APR = {sam_high:.1f}%, first 'well above' APR = {sam_apr:.1f}%")
for k in ["range_low_pct", "range_high_pct", "typical_pct", "percentile", "flag", "range_coverage_pct", "extra_cost_usd", "reasons"]:
    print(f"  {k}: {sr[k]}")
RESULTS["jordan"] = jr; RESULTS["jordan_santander"] = jr_s
RESULTS["sam"] = {"offer": {**sam, "offered_apr_pct": sam_apr}, "first_high_apr": sam_high, "result": sr}
""")

md("""
## 12. Save every result

All numbers in the write-up come from `reports/results.json` and `RESULTS.md`, which this cell writes.
""")

code("""
mc.save_json(RESULTS, ROOT / "reports" / "results.json")
rt_ = RESULTS["repayment_test"]
rep_md = ("\\n".join([mc.md_table(pd.DataFrame(rt_["by_group"])), "",
                      f"Bad-rate gap, high-priced minus other: pooled {rt_['pooled_gap']:.3f}; within-lender gaps weighted by lender size {rt_['lender_weighted_gap']:.3f}.", "",
                      "Share of monthly rows with no delinquency status (counted as current): "
                      + ", ".join(f"{k} {v:.3f}" for k, v in rt_["missing_status_share_by_lender"].items()) + ". "
                      f"Without loans that have any month missing a status ({rt_['without_missing_status']['loans_kept']:,} loans): "
                      f"high-priced {rt_['without_missing_status']['bad_rate_high']:.3f} vs other {rt_['without_missing_status']['bad_rate_other']:.3f}.", "",
                      "### By credit tier and term", mc.md_table(pd.DataFrame(rt_["by_tier_term"]))])
          if isinstance(rt_, dict) else str(rt_))
tp_ = RESULTS["treasury_passthrough"]
parts = ["# MarkupCheck — full results", "", "Generated by `notebooks/MarkupCheck.ipynb`; do not edit by hand.", "",
         "## Deals", mc.md_table(deals), "", "## Cleaning", mc.md_table(drops), "",
         "## Test-month results", mc.md_table(metrics), "", f"Conformal width added (qhat): {qhat:.3f} points.", "",
         "## Percentile honesty", mc.md_table(pit), "",
         f"## Markup injection (model delta = {delta} points, B1 delta = {delta_b1} points; both set on calibration loans to flag at most 2.5% of ordinary loans)",
         mc.md_table(inj), "", "### Model 'well above', +2.0 points, by credit tier and new/used", mc.md_table(by_group), "",
         "## Fairness on groups the model never sees (gap vs the average loan)", "### By lender", mc.md_table(issuer_tbl), "",
         "### By state (300+ test loans)", mc.md_table(state_tbl), "",
         "## Reliability by credit tier and new/used", mc.md_table(rel), "",
         "## Improvement: whole market (A) vs same lender (B)", "### Selection evidence (calibration-flag half, before the test months)", mc.md_table(sel), "",
         "### Final evaluation (test months)", mc.md_table(cmp), "",
         "### Markup detection (+2.0 points) by credit tier", mc.md_table(rec), "",
         "### State gaps, whole market vs within the same lender", mc.md_table(state_both), "",
         "## How sure are these numbers?", "### By test month", mc.md_table(by_month), "", "### By lender", mc.md_table(by_lender), "",
         f"The model beats the B1 rule in {months_A_beats_B1} of {len(by_month)} test months; the same-lender model beats the model in {months_B_beats_A} of {len(by_month)}.", "",
         "### Paired bootstrap of error differences (1,000 resamples of test loans; ignores clustering by dealer and month, so too narrow)", mc.md_table(paired), "",
         "### Injection test over 50 random seeds (model 'well above', +2.0 points)", mc.md_table(seeds), "",
         f"### Markup detection at matched false-alarm rates (thresholds set on test months for comparison only; the model's own 'well above' rate on test is {fa_model:.3f})",
         mc.md_table(matched), "",
         "### Precision if a different share of loans were marked up (model 'well above', +2.0 points)", mc.md_table(prevalence), "",
         "### Trees vs a linear quantile model on the same six inputs", mc.md_table(linear), "",
         "### 39 state gaps: multiple-comparison check (Holm correction, normal approximation)", mc.md_table(multi), "",
         f"### Treasury pass-through: {tp_['apr_points_per_treasury_point']:.2f} APR points per 1-point Treasury change "
         f"(95% CI {tp_['ci_low']:.2f} to {tp_['ci_high']:.2f}; {tp_['group_months']} lender x tier x new/used group-months, bootstrap over {tp_['months']} months; rough, confounded by other changes over time)", "",
         "### Markup sizes from the 2016 Toyota order: 1.25 points for terms of 60 months or less, 1.00 for longer (same 10% of test loans; +2.0 rows repeated for comparison)",
         mc.md_table(caps), "",
         f"#### At the model's own 'well above' rate on test ({round(fa_model, 4)}) for every method", mc.md_table(cap_matched), "",
         "#### Model 'well above', Toyota-order caps, by term", mc.md_table(cap_by_term), "",
         "#### Model 'well above', Toyota-order caps, 50 random seeds", mc.md_table(cap_seeds), "",
         "## Where it fails", mc.md_table(fail[cols]), "", "## Input importance", mc.md_table(imp), "",
         "## Repayment test (out-of-fold, matched on deal + asset number)", rep_md, "",
         "## Demo examples", "### Jordan (lender not given)", "```", json.dumps(jr, indent=2), "```",
         "### Jordan (lender named as Santander)", "```", json.dumps(jr_s, indent=2), "```",
         f"### Sam (first 'high' APR {sam_high:.1f}%, first 'well above' APR {sam_apr:.1f}%)", "```", json.dumps(RESULTS["sam"], indent=2), "```"]
(ROOT / "RESULTS.md").write_text("\\n".join(parts))
print("wrote reports/results.json and RESULTS.md")
""")

nb = nbf.v4.new_notebook()
nb["cells"] = cells
nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
out = ROOT / "notebooks" / "MarkupCheck.ipynb"
out.parent.mkdir(exist_ok=True)
nbf.write(nb, out)
print("wrote", out, "with", len(cells), "cells")
