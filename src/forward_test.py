"""Forward test of the frozen, shipped MarkupCheck models on CarMax loans originated after the newest month in
the training data (Jan 2026), so no model, range or flag threshold has seen them.

usage:
  .venv/bin/python -I src/forward_test.py parse   # parse the downloaded pool XMLs with the CarMax parser's own code
  .venv/bin/python -I src/forward_test.py parse_capone   # same parser on Capital One Prime 2026-1 (out-of-lender test)
  .venv/bin/python -I src/forward_test.py score   # clean, score, print, write reports/forward_test.json and FORWARD_TEST.md

Inputs: the first pool ABS-EE EX-102 files of CarMax Auto Owner Trust 2026-2, 2026-3 and 2026-4 in
data/raw/carmax_forward/xml/ (downloaded from EDGAR; see data/raw/carmax_forward/sec_requests.log).
The models are read from app/model/ and never refitted; this script writes nothing outside
data/raw/carmax_forward/ and reports/.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys

import joblib
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import mc  # noqa: E402

FWD = ROOT / "data" / "raw" / "carmax_forward"
XML_DIR, PARQUET_DIR = FWD / "xml", FWD / "parquet"
MODEL_DIR = ROOT / "app" / "model"
NEWEST_TRAINING_MONTH = "2026-01"

# The 'largepool' file of each deal. The 424H offers two deal sizes and CarMax files one EX-102 per size
# ('b' small, 'u' large); in each 424B5 the pool's receivable count is the one given here, which is checked
# against the parsed row count below. Filing date is the ABS-EE pool filing (mc.clean's 12-month rule uses it).
DEALS = {
    "carmax_2026-2": dict(deal="CarMax Auto Owner Trust 2026-2", cik="0002117307", filing_date="2026-04-14",
                          accession="0001259380-26-000017", xml="cart20262u.xml",
                          b424="0001193125-26-173162 (2026-04-23)", prospectus_loan_count=52812),
    "carmax_2026-3": dict(deal="CarMax Auto Owner Trust 2026-3", cik="0002142044", filing_date="2026-07-07",
                          accession="0001259380-26-000027", xml="cart20263u.xml",
                          b424="0001193125-26-305902 (2026-07-16)", prospectus_loan_count=79198),
    "carmax_2026-4": dict(deal="CarMax Auto Owner Trust 2026-4", cik="0002150706", filing_date="2026-10-06",
                          accession="0001259380-26-000035", xml="cart20264u.xml",
                          b424="0001193125-26-423742 (2026-10-16)", prospectus_loan_count=69556),
}

# Out-of-lender test: a bank pool the model never saw. The 424H offered three sizes (sp, mp, lp files); the 424B5's
# receivable count is checked against the parsed large-pool ('lp') file below.
CAPONE_DIR = FWD / "capone"
CAPONE = {"capone_2026-1": dict(deal="Capital One Prime Auto Receivables Trust 2026-1", cik="0002149906",
                                filing_date="2026-09-02", accession="0001193125-26-379485",
                                xml="copart261ex102_0831-1940lp.xml", b424="0001193125-26-389225 (2026-09-11)",
                                prospectus_loan_count=91627)}
# Capital One labels every score "FICO"; mc.clean keeps only consumer bureau scores, labelled "Bureau" by CarMax.
CAPONE_SCORE_TYPE_MAP = {"FICO": "Bureau"}

# Numbers the README and RESULTS.md report for the original test months (all lenders), read from the notebook's
# own outputs so this check still holds after a retrain.
_mt = {m["method"]: m for m in json.loads((ROOT / "reports" / "results.json").read_text())["metrics_test"]}
_cov_pu = json.loads((MODEL_DIR / "meta.json").read_text())["views"]["market"]["coverage_by_group"]["prime|1"]
README_TEST = {"model_mae": round(_mt["Model + conformal calibration"]["MAE_points"], 2),
               "b1_mae": round(_mt["B1 credit tier x new/used"]["MAE_points"], 2),
               "coverage": round(_mt["Model + conformal calibration"]["coverage_of_80pct_range"], 3),
               "coverage_prime_used": round(_cov_pu, 3)}


def parse(xml_dir=XML_DIR, deals=DEALS, pti_scale=1.0):
    """Run the CarMax parser's own parse() on the new files, pointed at this folder instead of
    data/parquet/carmax/ (which the notebook loads as training data, so it must not change). The CarMax parser reads
    paymentToIncomePercentage as a fraction (x100); `pti_scale` corrects a lender that writes it in percent."""
    spec = importlib.util.spec_from_file_location("parse_carmax", ROOT / "data" / "raw" / "carmax" / "parse_carmax.py")
    pc = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True  # no __pycache__ in data/raw/carmax/, which this script doesn't own
    spec.loader.exec_module(pc)
    pc.HERE, pc.PARQUET_DIR, pc.DEALS = str(xml_dir), str(PARQUET_DIR), deals
    for slug in deals:
        pc.parse(slug)
        if pti_scale != 1.0:  # pti_pct is not a model input; this keeps the file true to CONTRACT.md (percent)
            import pyarrow.compute as pac
            import pyarrow.parquet as pq
            f = PARQUET_DIR / f"{slug}.parquet"
            t = pq.read_table(f)
            i = t.schema.get_field_index("pti_pct")
            t = t.set_column(i, t.schema.field(i), pac.round(pac.multiply(t.column(i), pti_scale), 6))
            pq.write_table(t, f)
        os.replace(pathlib.Path(xml_dir) / f"stats_{slug}.json", PARQUET_DIR / f"stats_{slug}.json")


def load_models(view: str, meta: dict) -> dict:
    """Same files and naming as _load() in app/markupcheck_model.py."""
    d = meta["views"][view]["dir"]
    return {float(a): joblib.load(MODEL_DIR / d / f"q{int(round(float(a) * 100)):02d}.joblib") for a in meta["alphas"]}


def score_frame(df, models, meta, view, b1, b0) -> pd.DataFrame:
    """Per-loan typical price, calibrated 80% range and flags, computed the way notebook section 5 does."""
    info = meta["views"][view]
    alphas = sorted(float(a) for a in meta["alphas"])
    iL, iM, iH = mc.col(alphas, meta["lo"]), mc.col(alphas, 0.5), mc.col(alphas, meta["hi"])
    q = mc.predict_grid(models, df, info["features"])
    qhat, delta = float(info["conformal_qhat"]), float(info["flag_delta"])
    pb1 = mc.predict_b1(b1, b0, df)
    y = df["spread"].to_numpy()
    return pd.DataFrame({
        "month": df["origination_month"].to_numpy(), "issuer": df["issuer"].to_numpy(),
        "tier": df["tier"].astype(str).to_numpy(), "is_used": df["is_used"].to_numpy(), "y": y,
        "mid": q[:, iM], "lo": q[:, iL] - qhat, "hi": q[:, iH] + qhat,
        "b1_mid": pb1.q50.to_numpy(), "b1_lo": pb1.q_lo.to_numpy(), "b1_hi": pb1.q_hi.to_numpy(),
        "high": y > q[:, iH] + qhat, "well_above": y > q[:, iH] + qhat + delta})


def summary(s: pd.DataFrame) -> dict:
    inside = (s.y >= s.lo) & (s.y <= s.hi)
    pu = (s.tier == "prime") & (s.is_used == 1)
    return {"loans": int(len(s)), "model_mae": float(np.mean(np.abs(s.y - s["mid"]))),
            "b1_mae": float(np.mean(np.abs(s.y - s.b1_mid))),
            "coverage": float(inside.mean()), "mean_width": float(np.mean(s.hi - s.lo)),
            "prime_used_loans": int(pu.sum()), "coverage_prime_used": float(inside[pu].mean()) if pu.any() else float("nan"),
            "b1_coverage": float(((s.y >= s.b1_lo) & (s.y <= s.b1_hi)).mean()),
            "share_high": float(s.high.mean()), "share_well_above": float(s.well_above.mean()),
            "share_below_range": float((s.y < s.lo).mean()), "mean_residual": float(np.mean(s.y - s["mid"]))}


def by_month(sA: pd.DataFrame, sB: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for m in sorted(sA.month.unique()):
        a, b = summary(sA[sA.month == m]), summary(sB[sB.month == m])
        rows.append({"month": m, "loans": a["loans"], "model_MAE": a["model_mae"], "same_lender_MAE": b["model_mae"],
                     "B1_rule_MAE": a["b1_mae"], "model_coverage": a["coverage"], "same_lender_coverage": b["coverage"],
                     "model_below_range": a["share_below_range"], "model_above_range": a["share_high"],
                     "model_mean_residual": a["mean_residual"], "model_well_above_share": a["share_well_above"]})
    return pd.DataFrame(rows)


def score():
    meta = json.loads((MODEL_DIR / "meta.json").read_text())
    bench = mc.load_benchmark()
    res = json.loads((ROOT / "reports" / "results.json").read_text())
    reported = {"same_lender_mae": res["compare_A_B"][1]["MAE_points"], "same_lender_coverage": res["compare_A_B"][1]["coverage_of_80pct_range"],
                "model_well_above_share": res["model_false_alarm_test"],
                "b1_coverage": next(m["coverage_of_80pct_range"] for m in res["metrics_test"] if m["method"].startswith("B1"))}

    # The original data, cleaning and time split, rebuilt exactly as the notebook does, for the B1 rule
    # (training months only) and to check that this script reproduces the reported test numbers.
    raw_old = mc.load_raw()
    old, _ = mc.clean(raw_old, bench)
    old = mc.add_features(old, bench)
    old = mc.apply_split(old, mc.time_split(old))
    train, test = old[old.set == "train"], old[old.set == "test"]
    b0, b1 = mc.baseline_b0(train), mc.baseline_b1(train)
    newest = old.origination_month.max()
    assert newest == NEWEST_TRAINING_MONTH == meta["newest_origination_month"], newest
    models = {v: load_models(v, meta) for v in ("market", "same_lender")}

    tA = score_frame(test, models["market"], meta, "market", b1, b0)
    tB = score_frame(test, models["same_lender"], meta, "same_lender", b1, b0)
    check = summary(tA)
    print(f"Check on the original test months ({test.origination_month.min()} to {test.origination_month.max()}, "
          f"{check['loans']:,} loans): model MAE {check['model_mae']:.3f}, B1 MAE {check['b1_mae']:.3f}, "
          f"coverage {check['coverage']:.3f}, prime used {check['coverage_prime_used']:.3f}")
    reproduced = (round(check["model_mae"], 2) == README_TEST["model_mae"] and round(check["b1_mae"], 2) == README_TEST["b1_mae"]
                  and round(check["coverage"], 3) == README_TEST["coverage"]
                  and round(check["coverage_prime_used"], 3) == README_TEST["coverage_prime_used"])
    print("reproduces the README's test numbers:", reproduced)
    assert reproduced, "scoring here differs from the notebook's; fix before reporting forward numbers"
    cm = test.issuer.to_numpy() == "carmax"
    test_carmax = {"A": summary(tA[cm]), "B": summary(tB[cm])}

    # The new loans: parse output -> the same counted cleaning and features as training -> only unseen months.
    raw = pd.concat([pd.read_parquet(PARQUET_DIR / f"{slug}.parquet") for slug in DEALS], ignore_index=True)
    stats = {slug: json.loads((PARQUET_DIR / f"stats_{slug}.json").read_text()) for slug in DEALS}
    cross_deal_dups = int(raw.asset_number.duplicated().sum())
    seen_ids = set(raw_old.loc[raw_old.issuer == "carmax", "asset_number"])
    overlap_training_ids = int(raw.asset_number.isin(seen_ids).sum())
    missing_bench = sorted(set(raw.origination_month.dropna()) - set(bench.index))
    clean, drops = mc.clean(raw, bench)
    d = mc.add_features(clean, bench)
    n_before = len(d)
    d = d[d.origination_month > newest].copy()
    drops = pd.concat([drops, pd.DataFrame([{"step": f"originated after {newest} (newest month in the training data)",
                                             "rows_removed": n_before - len(d), "rows_left": len(d)}])], ignore_index=True)
    sA = score_frame(d, models["market"], meta, "market", b1, b0)
    sB = score_frame(d, models["same_lender"], meta, "same_lender", b1, b0)
    fA, fB = summary(sA), summary(sB)
    months = by_month(sA, sB)
    bench_fwd = bench.reindex(sorted(d.origination_month.unique()))

    print("\nDeals parsed (largepool EX-102; parsed rows vs the 424B5 receivable count):")
    for slug, dl in DEALS.items():
        st = stats[slug]
        print(f"  {dl['deal']}: {st['rows_parsed']:,} rows parsed, 424B5 says {dl['prospectus_loan_count']:,}; "
              f"origination {st['origination_month_min']} to {st['origination_month_max']}")
    print(f"asset numbers repeated across the three deals: {cross_deal_dups}; also in the training CarMax files: {overlap_training_ids}")
    print("origination months without a Treasury benchmark:", missing_bench or "none")
    print("\nCleaning (mc.clean, then the unseen-months filter):")
    print(drops.to_string(index=False))
    print(f"\nForward-test loans: {len(d):,}, originated {d.origination_month.min()} to {d.origination_month.max()} "
          f"({d.origination_month.nunique()} months); 5-year Treasury in those months {bench_fwd.min():.2f}% to {bench_fwd.max():.2f}% "
          f"(training data {meta['data_benchmark_min']:.2f}% to {meta['data_benchmark_max']:.2f}%)")
    print(f"Typical-price error (MAE, points): model {fA['model_mae']:.3f}, same-lender model {fB['model_mae']:.3f}, "
          f"B1 credit-tier rule {fA['b1_mae']:.3f}")
    print(f"80% range coverage: model {fA['coverage']:.3f} (mean width {fA['mean_width']:.3f}), same-lender model {fB['coverage']:.3f} "
          f"(mean width {fB['mean_width']:.3f}), B1 rule {fA['b1_coverage']:.3f}")
    print(f"Prime used-car buyers ({fA['prime_used_loans']:,} loans): coverage model {fA['coverage_prime_used']:.3f}, "
          f"same-lender model {fB['coverage_prime_used']:.3f}")
    print(f"Outside the model's range: below {fA['share_below_range']:.3f}, above {fA['share_high']:.3f}; "
          f"mean residual (actual minus typical) {fA['mean_residual']:.3f}")
    print(f"Real (unaltered) loans flagged: model 'high' {fA['share_high']:.3f}, 'well above' {fA['share_well_above']:.3f}; "
          f"same-lender 'high' {fB['share_high']:.3f}, 'well above' {fB['share_well_above']:.3f}")
    print(f"\nREADME test months (all lenders): model {README_TEST['model_mae']} vs B1 {README_TEST['b1_mae']}; "
          f"coverage {README_TEST['coverage']:.3f}, prime used {README_TEST['coverage_prime_used']:.3f}")
    ta, tb = test_carmax["A"], test_carmax["B"]
    print(f"Same test months, CarMax loans only ({ta['loans']:,}): model {ta['model_mae']:.3f}, same-lender {tb['model_mae']:.3f}, "
          f"B1 {ta['b1_mae']:.3f}; coverage {ta['coverage']:.3f} (same-lender {tb['coverage']:.3f}), "
          f"prime used {ta['coverage_prime_used']:.3f} ({ta['prime_used_loans']:,} loans); 'well above' share {ta['share_well_above']:.3f}; "
          f"below range {ta['share_below_range']:.3f}, above {ta['share_high']:.3f}; mean residual {ta['mean_residual']:.3f}")
    print("\nBy origination month:")
    print(months.round(3).to_string(index=False))
    beats = int((months.model_MAE < months.B1_rule_MAE).sum())
    print(f"model beats the B1 rule in {beats} of {len(months)} months")

    out = {
        "what": "Forward test of the frozen app/model/ files on CarMax loans originated after the training data's newest month",
        "newest_training_month": newest,
        "deals": [{"slug": s, **{k: v for k, v in dl.items()}, "source_url": stats[s]["source_url"], "bytes": stats[s]["bytes"],
                   "rows_parsed": stats[s]["rows_parsed"], "origination_month_min": stats[s]["origination_month_min"],
                   "origination_month_max": stats[s]["origination_month_max"]} for s, dl in DEALS.items()],
        "asset_numbers_repeated_across_deals": cross_deal_dups, "asset_numbers_also_in_training_carmax_files": overlap_training_ids,
        "months_without_benchmark": missing_bench, "benchmark_file": "data/benchmark/treasury_5y_monthly.csv (unchanged)",
        "treasury_5y_forward_months": {k: float(v) for k, v in bench_fwd.items()},
        "drops": drops.to_dict(orient="records"),
        "n_loans": int(len(d)), "months": sorted(d.origination_month.unique()),
        "forward": {"market": fA, "same_lender": fB}, "by_month": months.to_dict(orient="records"),
        "model_beats_b1_months": beats,
        "check_original_test": {"all_lenders_market": check, "reproduces_readme": reproduced,
                                "carmax_only": test_carmax},
        "readme_test": README_TEST, "reported_test": reported,
        "conformal_qhat": {v: meta["views"][v]["conformal_qhat"] for v in ("market", "same_lender")},
        "flag_delta": {v: meta["views"][v]["flag_delta"] for v in ("market", "same_lender")},
    }
    ool_md = []
    if (PARQUET_DIR / f"{next(iter(CAPONE))}.parquet").exists():
        out["out_of_lender"], ool_md = out_of_lender(meta, bench, models, b1, b0, test, tA, newest)
    mc.save_json(out, ROOT / "reports" / "forward_test.json")
    write_md(out, drops, months, ool_md)
    print("\nwrote reports/forward_test.json and reports/FORWARD_TEST.md")


def group_table(s: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (t, u), g in s.groupby(["tier", "is_used"]):
        sm = summary(g)
        rows.append({"tier": t, "new_or_used": "used" if u else "new", "loans": sm["loans"], "model_MAE": sm["model_mae"],
                     "B1_rule_MAE": sm["b1_mae"], "model_coverage": sm["coverage"], "B1_coverage": sm["b1_coverage"],
                     "below_range": sm["share_below_range"], "above_range": sm["share_high"]})
    return pd.DataFrame(rows)


def out_of_lender(meta, bench, models, b1, b0, test, tA, newest):
    """The whole-market model (the view the app uses for lenders not in the data) on Capital One Prime 2026-1."""
    slug, dl = next(iter(CAPONE.items()))
    raw = pd.read_parquet(PARQUET_DIR / f"{slug}.parquet")
    st = json.loads((PARQUET_DIR / f"stats_{slug}.json").read_text())
    seen = "capone" in meta["views"]["same_lender"].get("n_loans_by_lender", {})  # v2 trains on its 2024-1 and 2025-1 deals
    raw["issuer"] = "capone" if seen else "capitalone"  # the CarMax parser writes 'carmax' into every row
    raw["credit_score_type"] = raw["credit_score_type"].replace(CAPONE_SCORE_TYPE_MAP)
    clean, drops = mc.clean(raw, bench)
    d = mc.add_features(clean, bench)
    s = score_frame(d, models["market"], meta, "market", b1, b0)
    f = summary(s)
    lo_score = float(d.credit_score.min())
    same = (test.credit_score.to_numpy() >= lo_score) & test.origination_month.isin(d.origination_month.unique()).to_numpy()
    c = summary(tA[same])
    gt_cap, gt_test = group_table(s), group_table(tA[same])
    rule_wins = [f"{r.tier} {r.new_or_used} cars ({r.model_MAE:.2f} vs {r.B1_rule_MAE:.2f})" for r in gt_cap.itertuples() if r.B1_rule_MAE < r.model_MAE]
    n_well = int(s.well_above.sum())
    print(f"\nOut-of-lender test: {dl['deal']}: {st['rows_parsed']:,} rows parsed, 424B5 says {dl['prospectus_loan_count']:,}; "
          f"origination {st['origination_month_min']} to {st['origination_month_max']}; score type map {CAPONE_SCORE_TYPE_MAP}")
    print(drops.to_string(index=False))
    print(f"Capital One loans scored: {len(d):,}, originated {d.origination_month.min()} to {d.origination_month.max()}, "
          f"credit score {lo_score:.0f} to {d.credit_score.max():.0f}; originated after {newest}: {int((d.origination_month > newest).sum())}")
    print(f"Typical-price error (MAE, points): model {f['model_mae']:.3f}, B1 rule {f['b1_mae']:.3f}")
    print(f"80% range coverage: model {f['coverage']:.3f} (mean width {f['mean_width']:.3f}), B1 rule {f['b1_coverage']:.3f}; "
          f"prime used ({f['prime_used_loans']:,} loans) {f['coverage_prime_used']:.3f}")
    print(f"Outside the model's range: below {f['share_below_range']:.3f}, above {f['share_high']:.3f}; 'well above' {f['share_well_above']:.3f}; "
          f"mean residual {f['mean_residual']:.3f}")
    print(f"Same months, original test loans with score {lo_score:.0f}+ (Ally, CarMax, Santander; {c['loans']:,}): model {c['model_mae']:.3f}, "
          f"B1 {c['b1_mae']:.3f}; coverage {c['coverage']:.3f}; below {c['share_below_range']:.3f}, above {c['share_high']:.3f}; "
          f"'well above' {c['share_well_above']:.3f}; mean residual {c['mean_residual']:.3f}")
    print("Capital One by tier and new/used:"); print(gt_cap.round(3).to_string(index=False))
    print(f"Original test loans, same months, score {lo_score:.0f}+:"); print(gt_test.round(3).to_string(index=False))
    res = {"deal": {"slug": slug, **dl, "source_url": st["source_url"], "bytes": st["bytes"], "rows_parsed": st["rows_parsed"],
                    "origination_month_min": st["origination_month_min"], "origination_month_max": st["origination_month_max"]},
           "score_type_map": CAPONE_SCORE_TYPE_MAP, "drops": drops.to_dict(orient="records"), "n_loans": int(len(d)),
           "months": sorted(d.origination_month.unique()), "credit_score_min": lo_score, "after_newest_training_month": int((d.origination_month > newest).sum()),
           "capital_one": f, "capital_one_n_well_above": n_well, "groups_where_rule_beats_model": rule_wins,
           "original_test_same_months_same_scores": c,
           "by_group_capital_one": gt_cap.to_dict(orient="records"), "by_group_original_test": gt_test.to_dict(orient="records")}
    md = ["", ("## Capital One Prime Auto Receivables Trust 2026-1: a later deal from a lender in the data" if seen
               else "## Out-of-lender test: Capital One Prime Auto Receivables Trust 2026-1"), "",
          (f"A bank lending through dealers. Its 2024-1 and 2025-1 deals are in the training data, so this later deal tests "
           f"a known lender's newer pool. Same parser and counted cleaning; the one change is a code map: " if seen else
           f"A bank lending through dealers, which the model never saw. Same parser and counted cleaning; the one change is a code map: ")
          +
          f"Capital One labels every credit score \"FICO\", which we treat as the consumer bureau score that cleaning keeps. "
          f"This section scores it with the whole-market model. The pool is prime only "
          f"(scores {lo_score:.0f} to {d.credit_score.max():.0f}) and its loans after cleaning were originated {d.origination_month.min()} "
          f"to {d.origination_month.max()}. "
          f"The comparison column is the original test loans from the same months with scores of {lo_score:.0f} or more.", "",
          f"| measure | Capital One 2026-1 | original test, same months and scores |", "|---|---|---|",
          f"| loans | {f['loans']:,} | {c['loans']:,} |",
          f"| typical-price error, model | {f['model_mae']:.2f} | {c['model_mae']:.2f} |",
          f"| typical-price error, rule of thumb (B1) | {f['b1_mae']:.2f} | {c['b1_mae']:.2f} |",
          f"| 80% range covers, model | {100 * f['coverage']:.1f}% | {100 * c['coverage']:.1f}% |",
          f"| 80% range covers, rule of thumb (B1) | {100 * f['b1_coverage']:.1f}% | {100 * c['b1_coverage']:.1f}% |",
          f"| loans below / above the model's range | {100 * f['share_below_range']:.1f}% / {100 * f['share_high']:.1f}% | "
          f"{100 * c['share_below_range']:.1f}% / {100 * c['share_high']:.1f}% |",
          f"| real loans flagged 'well above', model | {100 * f['share_well_above']:.1f}% | {100 * c['share_well_above']:.1f}% |",
          f"| mean of actual minus typical price | {f['mean_residual']:+.2f} | {c['mean_residual']:+.2f} |", "",
          f"**What it shows.** The model still beat the rule of thumb overall ({f['model_mae']:.2f} vs {f['b1_mae']:.2f} points)"
          + (f", though not for {', '.join(rule_wins)}" if rule_wins else "") + ". "
          f"But Capital One charged on average {abs(f['mean_residual']):.2f} points {'less' if f['mean_residual'] < 0 else 'more'} than the model's typical price: "
          f"{100 * f['share_below_range']:.1f}% of its loans fell below the 80% range and {100 * f['share_high']:.1f}% above it, "
          f"and {n_well} of {f['loans']:,} were flagged 'well above'. For a buyer whose lender is a prime bank like this one, "
          "the whole-market range sits too high, so an offer marked up above that bank's usual price can still look typical.", "",
          "### By credit tier and new/used, Capital One", mc.md_table(gt_cap), "",
          "### By credit tier and new/used, original test loans (same months and scores)", mc.md_table(gt_test), "",
          "### Cleaning, Capital One", mc.md_table(drops), "",
          f"Source: {st['source_url']} (ABS-EE filed {dl['filing_date']}, accession {dl['accession']}, {st['bytes']:,} bytes); "
          f"final prospectus 424B5 {dl['b424']} gives {dl['prospectus_loan_count']:,} receivables, the parsed row count."]
    return res, md


def write_md(o, drops, months, extra=()):
    fA, fB = o["forward"]["market"], o["forward"]["same_lender"]
    ta, tb = o["check_original_test"]["carmax_only"]["A"], o["check_original_test"]["carmax_only"]["B"]
    r = o["readme_test"]
    deals = ", ".join(f"{x['deal'].split()[-1]} ({x['rows_parsed']:,} loans)" for x in o["deals"])
    lines = [
        "# Forward test: the shipped model on loans it never saw", "",
        "Generated by `src/forward_test.py`; do not edit by hand. Numbers are in APR percentage points.", "",
        f"**What we did.** We froze the shipped models (`app/model/`, both views, with the conformal widths in `meta.json`) and "
        f"scored CarMax loans from three bond deals filed after training ended: CarMax Auto Owner Trust {deals}. "
        f"We parsed them with the project's CarMax parser, cleaned them with the same counted steps as training, and kept only "
        f"loans originated after {o['newest_training_month']}, the newest month in the training data. Nothing was refitted or re-tuned.", "",
        f"**Loans tested:** {o['n_loans']:,}, originated {o['months'][0]} to {o['months'][-1]} ({len(o['months'])} months). "
        "The 5-year Treasury yields for these months were already in `data/benchmark/treasury_5y_monthly.csv`.", "",
        "| measure | forward test (CarMax, new months) | original test, CarMax only | original test, all lenders (README) |",
        "|---|---|---|---|",
        f"| typical-price error, model | {fA['model_mae']:.2f} | {ta['model_mae']:.2f} | {r['model_mae']:.2f} |",
        f"| typical-price error, same-lender model | {fB['model_mae']:.2f} | {tb['model_mae']:.2f} | {o['reported_test']['same_lender_mae']:.2f} |",
        f"| typical-price error, credit-tier rule of thumb (B1) | {fA['b1_mae']:.2f} | {ta['b1_mae']:.2f} | {r['b1_mae']:.2f} |",
        f"| 80% range covers, model | {100 * fA['coverage']:.1f}% | {100 * ta['coverage']:.1f}% | {100 * r['coverage']:.1f}% |",
        f"| 80% range covers, same-lender model | {100 * fB['coverage']:.1f}% | {100 * tb['coverage']:.1f}% | {100 * o['reported_test']['same_lender_coverage']:.1f}% |",
        f"| 80% range covers, credit-tier rule of thumb (B1) | {100 * fA['b1_coverage']:.1f}% | {100 * ta['b1_coverage']:.1f}% | {100 * o['reported_test']['b1_coverage']:.1f}% |",
        f"| 80% range covers prime used-car buyers, model | {100 * fA['coverage_prime_used']:.1f}% | {100 * ta['coverage_prime_used']:.1f}% | {100 * r['coverage_prime_used']:.1f}% |",
        f"| loans below the model's range | {100 * fA['share_below_range']:.1f}% | {100 * ta['share_below_range']:.1f}% | |",
        f"| loans above the model's range ('high') | {100 * fA['share_high']:.1f}% | {100 * ta['share_high']:.1f}% | |",
        f"| real loans flagged 'well above', model | {100 * fA['share_well_above']:.1f}% | {100 * ta['share_well_above']:.1f}% | {100 * o['reported_test']['model_well_above_share']:.1f}% |",
        f"| mean of actual minus typical price, model | {fA['mean_residual']:+.2f} | {ta['mean_residual']:+.2f} | |", "",
        "The fair comparison is the middle column: the forward loans are all CarMax, and CarMax loans were already the easier ones "
        "in the original test months.", "",
        f"**What it shows.** The typical price held up: error {fA['model_mae']:.2f} points against {ta['model_mae']:.2f} on CarMax's "
        f"original test loans, and the model beat the rule of thumb in {o['model_beats_b1_months']} of {len(o['months'])} months. "
        f"The 80% range did not hold up: it covered {100 * fA['coverage']:.1f}% of the new loans "
        f"({100 * fA['coverage_prime_used']:.1f}% for prime used-car buyers). "
        f"{100 * fA['share_below_range']:.1f}% of loans fell below the range and {100 * fA['share_high']:.1f}% above it "
        f"({100 * ta['share_below_range']:.1f}% and {100 * ta['share_high']:.1f}% on CarMax's original test loans). "
        f"On average the new loans were priced {abs(fA['mean_residual']):.2f} points "
        f"{'below' if fA['mean_residual'] < 0 else 'above'} the model's typical price, so most misses are on the "
        f"{'cheap' if fA['share_below_range'] > fA['share_high'] else 'expensive'} side, not the side the markup flag uses. "
        f"The rule of thumb's range lost about as much ({100 * ta['b1_coverage']:.1f}% to {100 * fA['b1_coverage']:.1f}%), so CarMax's prices "
        "moved, not only the model. For a CarMax buyer this means an offer can look more ordinary than it is. Keeping the 80% promise would need "
        "the range recalibrated on new filings, which the shipped app does not do.", "",
        "## By origination month", mc.md_table(months), "",
        "## Cleaning", mc.md_table(drops), "",
        "## Sources",
        *[f"- {x['deal']}: {x['source_url']} (ABS-EE filed {x['filing_date']}, accession {x['accession']}, {x['bytes']:,} bytes); "
          f"final prospectus 424B5 {x['b424']} gives {x['prospectus_loan_count']:,} receivables." for x in o["deals"]],
        "",
        "## Limits",
        "- CarMax only: Ally and Santander have no public deal after 2026-1 (SEC filing index, Jul to Nov 2026), so this does not test the lenders where the model was weakest.",
        "- CarMax is both the dealer and the lender on its own loans, so these loans say little about dealer markups.",
        "- The B1 rule is rebuilt from the original training months; the conformal widths and flag thresholds come unchanged from `app/model/meta.json`.",
    ]
    (ROOT / "reports" / "FORWARD_TEST.md").write_text("\n".join(lines + list(extra)) + "\n")


if __name__ == "__main__":
    # Capital One writes PTI in percent, so its file is scaled back from the CarMax parser's x100.
    {"parse": parse, "parse_capone": lambda: parse(CAPONE_DIR, CAPONE, pti_scale=0.01), "score": score}[sys.argv[1]]()
