"""MarkupCheck core: load the parsed SEC loan files, clean them, build features, split by time,
fit quantile models with conformal calibration, and run every evaluation the write-up reports.

The notebook (notebooks/MarkupCheck.ipynb) calls these functions in order and shows their outputs.
Every row the cleaning step removes is counted, so the write-up can say exactly what was dropped.
Ranges, tier bins, lender codes and the scoring math come from app/scoring.py, which the app also uses.
"""
from __future__ import annotations

import glob
import json
import math
import pathlib
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
import scoring  # noqa: E402

SEED = 7
TIER_ORDER = scoring.TIER_ORDER

# Model inputs: only things a buyer knows at the dealer's desk. Never payment-to-income
# (the payment depends on the APR, so it would leak the answer), never state or issuer
# (they are audit groups for the fairness checks).
FEATURES = ["credit_score", "is_used", "vehicle_age", "amount_financed", "ltv", "term_months"]
# Same-lender view: a dealer markup sits on top of a specific lender's approved rate, so comparing
# with that lender's own similar loans is the sharper markup test. Used only when the buyer names
# the lender on the contract; the whole-market model (FEATURES) never sees the lender.
LENDER_CODES = {k: v["code"] for k, v in scoring.LENDERS.items()}
FEATURES_B = FEATURES + ["lender_code"]
ALPHAS = np.round(np.arange(0.05, 0.951, 0.05), 2)  # quantile grid: 0.05, 0.10, ..., 0.95
LO, HI = 0.10, 0.90  # the 80% range before calibration
NOT_INPUTS = ["pti_pct", "state", "issuer", "lender_code", "deal", "apr_pct", "spread", "asset_number"]
DOMAIN = scoring.INPUT_DOMAIN
# How each lender labels a consumer credit-bureau score in obligorCreditScoreType (from each manifest's
# code_values_seen): CarMax, Ally and Santander "Bureau" or "Consumer Bureau"; Ford "Consumer Bureau"; GM Financial
# "Credit Bureau Score"; Honda "Credit Bureau"; Hyundai "Consumer Credit Bureau"; Toyota "FICO Score 8 Auto";
# Nissan and Capital One "FICO". Ford's "Commercial Bureau" (business scores, another scale) and "None" stay out.
CONSUMER_SCORE_TYPES = ["bureau", "consumer bureau", "credit bureau", "credit bureau score", "consumer credit bureau",
                        "fico score 8 auto", "fico"]


# ---------- loading ----------

def load_raw() -> pd.DataFrame:
    files = sorted(f for f in glob.glob(str(ROOT / "data" / "parquet" / "*" / "*.parquet"))
                   if not pathlib.Path(f).name.startswith("perf_"))
    if not files:
        raise FileNotFoundError("No deal Parquet files in data/parquet/<issuer>/ yet.")
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def load_benchmark() -> pd.Series:
    b = pd.read_csv(ROOT / "data" / "benchmark" / "treasury_5y_monthly.csv")
    return b.set_index("month")["five_year_pct"]


# ---------- cleaning ----------

def _months_between(orig_month: pd.Series, filing_date: pd.Series) -> pd.Series:
    o = pd.to_datetime(orig_month + "-01")
    f = pd.to_datetime(filing_date.str[:7] + "-01")
    return (f.dt.year - o.dt.year) * 12 + (f.dt.month - o.dt.month)


def _is_false(v) -> bool:
    return str(v).strip().lower() in {"0", "false", "no", "n"}


def clean(df: pd.DataFrame, bench: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply every filter in order and count what each one removes."""
    log = [("all loans parsed", 0, len(df))]
    d = df.copy()
    s_lo, s_hi = DOMAIN["credit_score"]
    t_lo, t_hi = DOMAIN["term_months"]

    def step(name, mask):
        nonlocal d
        before = len(d)
        d = d[mask(d)].copy()
        log.append((name, before - len(d), len(d)))

    step("duplicate (deal, asset_number) removed",
         lambda x: ~x.duplicated(subset=["deal", "asset_number"]))
    step("subsidised (subvented) loans removed — a promo rate is not a market price",
         lambda x: x["subvented"].map(_is_false))
    step("fixed-rate loans only", lambda x: x["interest_rate_type_code"].astype(str).str.strip() == "1")
    step("consumer credit-bureau score only (drops business 'Commercial Bureau' and 'None' score types; each lender "
         "labels the consumer score its own way)",
         lambda x: x["credit_score_type"].astype(str).str.strip().str.lower().isin(CONSUMER_SCORE_TYPES))
    step(f"credit score present and {s_lo}–{s_hi} (lenders report FICO Auto scores, which run 250–900; "
         "0 and 999 mean no score)",
         lambda x: x["credit_score"].between(s_lo, s_hi))
    step("originated at most 12 months before the deal's first pool filing — older loans still in a pool "
         "are survivors of years of payoffs and defaults",
         lambda x: _months_between(x["origination_month"], x["filing_date"]).between(0, 12))
    step(f"APR above 0% and at most {DOMAIN['apr_pct_max']:.0f}%",
         lambda x: (x["apr_pct"] > 0) & (x["apr_pct"] <= DOMAIN["apr_pct_max"]))
    step("new (1) or used (2) code", lambda x: x["new_used_code"].astype(str).str.strip().isin(["1", "2"]))
    step(f"term {t_lo}–{t_hi} months", lambda x: x["original_term_months"].between(t_lo, t_hi))
    step("loan amount and vehicle value above $1,000",
         lambda x: (x["original_loan_amount"] > 1000) & (x["vehicle_value"] > 1000))
    step("loan-to-value 0.2–3.0",
         lambda x: (x["original_loan_amount"] / x["vehicle_value"]).between(0.2, 3.0))
    step("origination month has a Treasury benchmark",
         lambda x: x["origination_month"].isin(bench.index))
    step(f"vehicle model year plausible ({DOMAIN['model_year_min']} to origination year + 1)",
         lambda x: x["vehicle_model_year"].between(DOMAIN["model_year_min"],
                                                   x["origination_month"].str[:4].astype(int) + 1))

    drops = pd.DataFrame(log, columns=["step", "rows_removed", "rows_left"])
    return d, drops


def add_features(d: pd.DataFrame, bench: pd.Series) -> pd.DataFrame:
    """Same feature definitions as features_from_offer() in app/markupcheck_model.py
    (tests/test_mc_synthetic.py checks that the two agree)."""
    d = d.copy()
    d["is_used"] = (d["new_used_code"].astype(str).str.strip() == "2").astype(int)
    orig_year = d["origination_month"].str[:4].astype(int)
    d["vehicle_age"] = (orig_year - d["vehicle_model_year"]).clip(*scoring.VEHICLE_AGE_CLIP)
    d["amount_financed"] = d["original_loan_amount"]
    d["ltv"] = d["original_loan_amount"] / d["vehicle_value"]
    d["term_months"] = d["original_term_months"]
    d["treasury_5y_pct"] = d["origination_month"].map(bench)
    d["spread"] = d["apr_pct"] - d["treasury_5y_pct"]  # the target
    d["tier"] = pd.cut(d["credit_score"], bins=scoring.TIER_BINS, labels=TIER_ORDER)
    d["lender_code"] = d["issuer"].map(LENDER_CODES)
    return d


# ---------- time split ----------

def time_split(d: pd.DataFrame, test_frac=0.20, cal_frac=0.15) -> dict:
    counts = d.groupby("origination_month").size().sort_index()
    months = list(counts.index)
    total = counts.sum()
    test, cal = [], []
    acc = 0
    for m in reversed(months):
        if acc < test_frac * total:
            test.append(m); acc += counts[m]
        else:
            break
    acc2 = 0
    for m in reversed(months[: len(months) - len(test)]):
        if acc2 < cal_frac * total:
            cal.append(m); acc2 += counts[m]
        else:
            break
    train = [m for m in months if m not in test and m not in cal]
    return {"train": sorted(train), "cal": sorted(cal), "test": sorted(test)}


def apply_split(d: pd.DataFrame, split: dict) -> pd.DataFrame:
    d = d.copy()
    d["set"] = np.select([d["origination_month"].isin(split["train"]),
                          d["origination_month"].isin(split["cal"]),
                          d["origination_month"].isin(split["test"])],
                         ["train", "cal", "test"], default="none")
    # Calibration months are split in two at random: half sets the conformal width,
    # half tunes the markup-flag threshold, so neither is tuned on the data that checks it.
    rng = np.random.default_rng(SEED)
    is_cal = d["set"] == "cal"
    half = rng.random(len(d)) < 0.5
    d.loc[is_cal & half, "set"] = "cal_width"
    d.loc[is_cal & ~half, "set"] = "cal_flag"
    return d


# ---------- baselines ----------

def baseline_b0(train: pd.DataFrame) -> dict:
    return {a: float(np.quantile(train["spread"], a)) for a in (LO, 0.5, HI)}


def baseline_b1(train: pd.DataFrame) -> pd.DataFrame:
    g = train.groupby(["tier", "is_used"], observed=True)["spread"]
    t = g.quantile([LO, 0.5, HI]).unstack()
    t.columns = ["q_lo", "q50", "q_hi"]
    t["n_train"] = g.size()
    return t


def predict_b1(table: pd.DataFrame, b0: dict, df: pd.DataFrame) -> pd.DataFrame:
    """The B1 rule's range for each row (its tier × new/used bucket), falling back to B0 for empty buckets."""
    out = table[["q_lo", "q50", "q_hi"]].reindex(pd.MultiIndex.from_arrays([df["tier"], df["is_used"]]))
    out.index = df.index
    return out.fillna({"q_lo": b0[LO], "q50": b0[0.5], "q_hi": b0[HI]})


# ---------- model ----------

def fit_quantile_models(train: pd.DataFrame, alphas=ALPHAS, features=FEATURES) -> dict:
    models = {}
    X, y = train[features], train["spread"]
    categorical = [f == "lender_code" for f in features]
    for a in alphas:
        m = HistGradientBoostingRegressor(loss="quantile", quantile=float(a), max_iter=400,
                                          learning_rate=0.06, max_leaf_nodes=31, min_samples_leaf=200,
                                          l2_regularization=1.0, early_stopping=True,
                                          validation_fraction=0.1, n_iter_no_change=20,
                                          categorical_features=categorical if any(categorical) else None,
                                          random_state=SEED)
        m.fit(X, y)
        models[float(a)] = m
    return models


def predict_grid(models: dict, df: pd.DataFrame, features=FEATURES) -> np.ndarray:
    return scoring.predict_grid(models, df[features])


col = scoring.col


def conformal_qhat(q_lo, q_hi, y, alpha=0.20) -> float:
    scores = np.maximum(q_lo - y, y - q_hi)
    n = len(scores)
    k = min(n, math.ceil((n + 1) * (1 - alpha)))
    return float(np.sort(scores)[k - 1])


def percentile_from_grid(qgrid: np.ndarray, alphas, values: np.ndarray) -> np.ndarray:
    return np.array([scoring.percentile(row, alphas, v) for row, v in zip(qgrid, values)])


# ---------- metrics ----------

def pinball(y, q, a) -> float:
    diff = y - q
    return float(np.mean(np.maximum(a * diff, (a - 1) * diff)))


def interval_metrics(y, lo, hi) -> dict:
    return {"coverage": float(np.mean((y >= lo) & (y <= hi))), "mean_width": float(np.mean(hi - lo))}


def bootstrap_mean_ci(x: np.ndarray, n_boot=500, seed=SEED) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    x = np.asarray(x)
    if len(x) == 0:
        return (float("nan"),) * 3
    means = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(n_boot)]
    return float(x.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


# ---------- markup flag and injection test ----------

def detection_scores(injected, flagged, before) -> dict:
    """Precision and recall of a flag on loans with injected markups. recall_new counts only marked-up
    loans that were NOT already flagged before the markup was added. NaN when a denominator is empty."""
    injected, flagged, before = (np.asarray(v, bool) for v in (injected, flagged, before))
    tp = int(np.sum(flagged & injected)); fp = int(np.sum(flagged & ~injected)); fn = int(np.sum(~flagged & injected))
    fresh = injected & ~before
    return {"precision": tp / (tp + fp) if tp + fp else float("nan"),
            "recall": tp / (tp + fn) if tp + fn else float("nan"),
            "recall_new": float(np.sum(flagged & fresh) / np.sum(fresh)) if np.sum(fresh) else float("nan")}


def injection_run(spread, upper, delta, size, frac=0.10, seed=SEED) -> dict:
    """Add `size` points to a random `frac` of loans and score the flag 'spread > upper + delta'."""
    rng = np.random.default_rng(seed)
    injected = rng.random(len(spread)) < frac
    before = spread > upper + delta
    flagged = spread + injected * size > upper + delta
    return {"size_pts": size, "injected": int(injected.sum()), "flagged": int(flagged.sum()),
            **detection_scores(injected, flagged, before), "untouched_flagged_share": float(np.mean(before)),
            "_injected": injected, "_flagged": flagged, "_before": before}


def tune_delta_false_alarm(spread, upper, target=0.025) -> float:
    """Smallest delta >= 0 such that at most `target` of ordinary loans are flagged 'well above'.
    Tuned on calibration loans only. (Maximising F1 instead always chose delta = 0, which made the
    'high' and 'well above' flags identical.)"""
    excess = np.asarray(spread) - np.asarray(upper)
    return max(0.0, round(float(np.quantile(excess, 1 - target)), 2))


def centered_group_table(frame: pd.DataFrame, col: str, resid_col: str, min_n: int, n_boot=500) -> pd.DataFrame:
    """Gap between a group's mean residual and the overall mean residual, with bootstrap CIs.
    Residual = actual spread minus the model's median spread. Centring on the overall mean makes
    'positive' mean 'paid more than the average similar loan', not 'more than the median'."""
    overall = float(frame[resid_col].mean())
    rows = []
    for k, g in frame.groupby(col, observed=True):
        if len(g) < min_n:
            continue
        m, lo, hi = bootstrap_mean_ci(g[resid_col].to_numpy(), n_boot=n_boot)
        rows.append({col: k, "loans": len(g), "gap_vs_average_points": m - overall,
                     "ci_low": lo - overall, "ci_high": hi - overall})
    return pd.DataFrame(rows).sort_values("gap_vs_average_points").reset_index(drop=True)


def percentile_recal_table(raw_cal: np.ndarray, points: int = 201) -> tuple[np.ndarray, np.ndarray]:
    """Map a raw model percentile to the share of calibration loans at or below it. Notebook section 5
    shows this correction made the test months worse, so the app doesn't use it."""
    xs = np.linspace(0, 100, points)
    s = np.sort(np.asarray(raw_cal))
    ys = 100 * np.searchsorted(s, xs, side="right") / len(s)
    return xs, ys


def crossfit_quantile(df: pd.DataFrame, features, alpha=0.9, folds=5) -> np.ndarray:
    """Out-of-fold quantile prediction: each loan's value comes from a model that never saw it.
    Uses the same model settings as fit_quantile_models()."""
    rng = np.random.default_rng(SEED)
    fold = rng.integers(0, folds, len(df))
    out = np.empty(len(df))
    for k in range(folds):
        tr, te = fold != k, fold == k
        m = fit_quantile_models(df.loc[tr], alphas=[alpha], features=features)[float(alpha)]
        out[te] = m.predict(df.loc[te, features])
    return out


# ---------- output helpers ----------

def md_table(df: pd.DataFrame, floatfmt: str = "{:.3f}") -> str:
    """Render a DataFrame as a GitHub markdown table (no extra packages)."""
    def fmt(v):
        if isinstance(v, (float, np.floating)):
            return "" if np.isnan(v) else floatfmt.format(v)
        return str(v)
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(fmt(v) for v in r.tolist()) + " |")
    return "\n".join(lines)


def save_json(obj, path):
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, default=float)
