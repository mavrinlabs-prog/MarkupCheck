"""Smoke test of src/mc.py on synthetic loans shaped like CONTRACT.md (not real data).
Run: .venv/bin/python tests/test_mc_synthetic.py
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import mc  # noqa: E402

rng = np.random.default_rng(0)
n = 20000
months = pd.period_range("2023-01", "2026-06", freq="M").astype(str)
score = rng.integers(480, 840, n).astype(float)
used = rng.random(n) < 0.7
term = rng.choice([48, 60, 72, 84], n)
true_spread = 14 - 0.02 * (score - 480) + 1.5 * used + 0.02 * (term - 60)
apr = true_spread + rng.normal(0, 1.2, n) + 4.0
df = pd.DataFrame({
    "issuer": rng.choice(["carmax", "ally", "santander"], n), "deal": "synthetic", "deal_cik": "0", "source_url": "",
    "asset_number": [f"a{i}" for i in range(n)],
    "origination_month": (om := rng.choice(months, n)),
    "filing_date": [str((pd.Period(m, "M") + int(k)).start_time.date()) for m, k in zip(om, rng.integers(1, 7, n))], "original_loan_amount": rng.uniform(8000, 45000, n),
    "original_term_months": term, "apr_pct": apr, "interest_rate_type_code": "1",
    "subvented": np.where(rng.random(n) < 0.05, "1", "0"), "vehicle_make": "x", "vehicle_model": "y",
    "new_used_code": np.where(used, "2", "1"), "vehicle_model_year": rng.integers(2012, 2026, n),
    "vehicle_type_code": "1", "vehicle_value": rng.uniform(9000, 50000, n), "vehicle_value_source_code": "1",
    "credit_score_type": "Bureau", "credit_score": score, "income_verification_code": "2",
    "employment_verification_code": "2", "co_obligor": False, "pti_pct": rng.uniform(3, 20, n),
    "state": rng.choice(["FL", "TX", "CA"], n),
})

bench = mc.load_benchmark()
clean, drops = mc.clean(df, bench)
print(drops.to_string(index=False))
assert drops["rows_left"].iloc[-1] == len(clean)
d = mc.add_features(clean, bench)
split = mc.time_split(d)
d = mc.apply_split(d, split)
assert set(d["set"]) <= {"train", "cal_width", "cal_flag", "test"}
assert max(split["train"]) < min(split["cal"]) <= max(split["cal"]) < min(split["test"]), "split must be time-ordered"
train, cw, cf, test = (d[d["set"] == s] for s in ["train", "cal_width", "cal_flag", "test"])
assert not set(train.columns.intersection(mc.NOT_INPUTS)) & set(mc.FEATURES)

b0 = mc.baseline_b0(train)
b1 = mc.baseline_b1(train)
pb1 = mc.predict_b1(b1, b0, test)
models = mc.fit_quantile_models(train, alphas=[0.1, 0.5, 0.9])
al = sorted(models)
qw = mc.predict_grid(models, cw)
qhat = mc.conformal_qhat(qw[:, 0], qw[:, 2], cw["spread"].to_numpy())
qt = mc.predict_grid(models, test)
cov = mc.interval_metrics(test["spread"].to_numpy(), qt[:, 0] - qhat, qt[:, 2] + qhat)
mae_model = np.mean(np.abs(test["spread"] - qt[:, 1]))
mae_b1 = np.mean(np.abs(test["spread"] - pb1["q50"]))
print(f"qhat={qhat:.3f} coverage={cov['coverage']:.3f} width={cov['mean_width']:.2f} MAE model={mae_model:.3f} B1={mae_b1:.3f}")
assert 0.72 < cov["coverage"] < 0.88, "conformal coverage on iid synthetic data should be near 0.80"
assert mae_model < mae_b1, "model should beat the tier rule on synthetic data with a term effect"

pct = mc.percentile_from_grid(qt, al, test["spread"].to_numpy())
assert pct.min() >= 0 and pct.max() <= 100
qf = mc.predict_grid(models, cf)
delta = mc.tune_delta_false_alarm(cf["spread"].to_numpy(), qf[:, 2] + qhat)
r = mc.injection_run(test["spread"].to_numpy(), qt[:, 2] + qhat, delta, 2.0)
print(f"delta={delta} injection +2.0: precision={r['precision']:.2f} recall={r['recall']:.2f}")
assert abs(mc.scoring.monthly_payment(18500, 15.9, 72) - 400.28) < 0.01

# The app builds features from an offer with its own function; it must agree with add_features().
import markupcheck_model  # noqa: E402  (src/mc.py put app/ on the path)
sample = d.sample(300, random_state=1)
for _, row in sample.iterrows():
    offer = {"credit_score": row.credit_score, "new_or_used": "used" if row.new_used_code == "2" else "new",
             "vehicle_model_year": row.vehicle_model_year, "vehicle_price": row.vehicle_value,
             "amount_financed": row.original_loan_amount, "term_months": row.original_term_months}
    app_row = markupcheck_model.features_from_offer(offer, int(row.origination_month[:4]))
    for f in mc.FEATURES:
        assert np.isclose(app_row[f], row[f]), (f, app_row[f], row[f])
print("feature parity: app features_from_offer() matches add_features() on 300 loans")
print("ALL SYNTHETIC CHECKS PASSED")
