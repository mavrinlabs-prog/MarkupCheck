"""Later deals from the three lenders with no loans in the test months (Toyota, Nissan, Capital One).

Their training deals end before the test months (2025-08 to 2026-01), so the notebook could not test the check on their
loans. Each deal here was filed after every training deal of its lender, so none of its loans was used to train or
calibrate anything. This script scores them the way the app would: the same-lender view (used when a buyer names the
lender), next to the whole-market view and the B1 rule of thumb, after the same counted cleaning as training.

  Toyota Auto Receivables 2026-C (pool filed 2026-07-07) and Nissan Auto Receivables 2026-A and 2026-B (pools filed
  2026-05-11 and 2026-09-15):
    parsed here by each lender's own parser, pointed at data/raw/later_deals/ (data/parquet/ stays the training data).
  Capital One Prime 2026-1 (pool filed 2026-09-02): already parsed by src/forward_test.py parse_capone.

Run: .venv/bin/python -I src/later_deals.py parse    (needs the two XML files in data/raw/later_deals/)
     .venv/bin/python -I src/later_deals.py score    (writes reports/later_deals.json)
"""
import importlib.util
import json
import os
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import forward_test as ft  # noqa: E402
import mc  # noqa: E402

HERE = ROOT / "data" / "raw" / "later_deals"
PARQUET_DIR = HERE / "parquet"
SEC = "https://www.sec.gov/Archives/edgar/data"
# Counts and dates read from each deal's EDGAR index and 424B5 (saved in data/raw/later_deals/sec/, Nov 15 2026).
DEALS = {
    "toyota": {"toyota_2026-C": dict(
        deal="Toyota Auto Receivables 2026-C Owner Trust", cik="0002099541", filing_date="2026-07-07",
        accession="0001193125-26-297081", xml="taot26cex102_0623-1819lp.xml", size=256339620, scenario="lp",
        other_pool_files=[("sp", "0001193125-26-297053", "taot26cex102_0623-1858sp.xml", 175606797),
                          ("mp", "0001193125-26-297077", "taot26cex103_0623-1853mp.xml", 215912734)],
        h424="0000929638-26-002565 (2026-07-08)", b424="0000929638-26-002627 (2026-07-16)",
        b424_url=f"{SEC}/2099541/000092963826002627/taot2026-c_424b5.htm",
        prospectus_loan_count=68025, prospectus_pool_balance=None)},
    "nissan": {"nissan_2026-A": dict(
        deal="Nissan Auto Receivables 2026-A Owner Trust", cik="0002130293", filing_date="2026-05-11",
        accession="0001193125-26-216202", xml="narot26aex102_0508-1653lp.xml", size=197733881, scenario="lp",
        other_pool_files=[("sp", "0001193125-26-216164", None, None)],
        h424="0001193125-26-223775 (2026-05-14)", b424="0001193125-26-236121 (2026-05-22)",
        b424_url=f"{SEC}/2130293/000119312526236121/d59935d424b5.htm",
        prospectus_loan_count=51130, prospectus_pool_balance=None),
        "nissan_2026-B": dict(
        deal="Nissan Auto Receivables 2026-B Owner Trust", cik="0002153094", filing_date="2026-09-15",
        accession="0001193125-26-392069", xml="narot26bex102_0914-1302lp.xml", size=209466932, scenario="lp",
        other_pool_files=[("sp", "0001193125-26-392012", "narot26bex102_0914-1342sp.xml", 167760320)],
        h424=None, b424="0001193125-26-401058 (2026-09-24)",
        b424_url=f"{SEC}/2153094/000119312526401058/d153597d424b5.htm",
        prospectus_loan_count=54150, prospectus_pool_balance=None)},
}
CAPONE = ("capone", "capone_2026-1", ft.PARQUET_DIR / "capone_2026-1.parquet")


def parse():
    PARQUET_DIR.mkdir(exist_ok=True)
    sys.dont_write_bytecode = True  # no __pycache__ in the lenders' folders
    for lender, deals in DEALS.items():
        spec = importlib.util.spec_from_file_location(f"parse_{lender}", ROOT / "data" / "raw" / lender / f"parse_{lender}.py")
        p = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(p)
        p.HERE, p.PARQUET_DIR, p.DEALS = str(HERE), str(PARQUET_DIR), deals
        for slug in deals:
            p.parse(slug)
            os.replace(HERE / f"stats_{slug}.json", PARQUET_DIR / f"stats_{slug}.json")


def score():
    meta = json.loads((ft.MODEL_DIR / "meta.json").read_text())
    bench = mc.load_benchmark()
    # The B1 rule from the training months only, exactly as src/forward_test.py and the notebook build it.
    raw_old = mc.load_raw()
    old, _ = mc.clean(raw_old, bench)
    old = mc.add_features(old, bench)
    old = mc.apply_split(old, mc.time_split(old))
    train, test = old[old.set == "train"], old[old.set == "test"]
    b0, b1 = mc.baseline_b0(train), mc.baseline_b1(train)
    newest = old.origination_month.max()
    assert newest == ft.NEWEST_TRAINING_MONTH == meta["newest_origination_month"], newest
    models = {v: ft.load_models(v, meta) for v in ("market", "same_lender")}

    files = [(lender, slug, PARQUET_DIR / f"{slug}.parquet") for lender, deals in DEALS.items() for slug in deals] + [CAPONE]
    out = {"what": __doc__.split("\n\n")[1].replace("\n", " "), "newest_training_month": newest, "deals": {}}
    for lender, slug, path in files:
        raw = pd.read_parquet(path)
        if lender == "capone":  # parsed with the CarMax parser, which writes 'carmax' and Capital One's 'FICO' label
            raw["issuer"] = "capone"
            raw["credit_score_type"] = raw["credit_score_type"].replace(ft.CAPONE_SCORE_TYPE_MAP)
        trained_ids = set(raw_old.loc[raw_old.issuer == lender, "asset_number"])
        overlap = int(raw.asset_number.isin(trained_ids).sum())
        raw = raw[~raw.asset_number.isin(trained_ids)]  # none expected: a loan is sold into one trust
        clean, drops = mc.clean(raw, bench)
        if clean.empty:  # Nissan 2026-A: every loan is promotional (subvented), so cleaning keeps none
            out["deals"][slug] = {"lender": lender, "parsed_rows": int(len(raw) + overlap),
                                    "asset_numbers_also_in_training": overlap, "drops": drops.to_dict(orient="records"),
                                    "loans": 0}
            print(f"{lender} {slug}: {len(raw) + overlap:,} rows, none kept after cleaning")
            print(drops.to_string(index=False))
            continue
        d = mc.add_features(clean, bench)
        same = ft.summary(ft.score_frame(d, models["same_lender"], meta, "same_lender", b1, b0))
        market = ft.summary(ft.score_frame(d, models["market"], meta, "market", b1, b0))
        after = d.origination_month > newest
        out["deals"][slug] = {
            "lender": lender, "parsed_rows": int(len(raw) + overlap), "asset_numbers_also_in_training": overlap,
            "drops": drops.to_dict(orient="records"), "loans": int(len(d)),
            "months": [d.origination_month.min(), d.origination_month.max()] if len(d) else None,
            "loans_after_newest_training_month": int(after.sum()),
            "same_lender": same, "market": market}
        print(f"{lender} {slug}: {len(raw) + overlap:,} rows, {overlap} already in training, {len(d):,} kept "
              f"({d.origination_month.min() if len(d) else '-'} to {d.origination_month.max() if len(d) else '-'}; "
              f"{int(after.sum()):,} after {newest})")
        if len(d):
            print(f"  same-lender view: error {same['model_mae']:.3f} vs rule {same['b1_mae']:.3f}, coverage {same['coverage']:.3f}; "
                  f"whole market: error {market['model_mae']:.3f}, coverage {market['coverage']:.3f}")
        print(drops.to_string(index=False))
    # Hyundai, the one tested lender where the whole-market view lost to the rule in the test months: is that more
    # than noise on its 210 loans, and does naming the lender (the same-lender view) fix it? Paired bootstrap, seed 0.
    h = test[test.issuer == "hyundai"]
    sm = ft.score_frame(h, models["market"], meta, "market", b1, b0)
    sb = ft.score_frame(h, models["same_lender"], meta, "same_lender", b1, b0)
    err_m, err_b, err_r = (np.abs(sm.y - sm["mid"]).to_numpy(), np.abs(sb.y - sb["mid"]).to_numpy(),
                           np.abs(sm.y - sm.b1_mid).to_numpy())
    rng = np.random.default_rng(0)
    idx = rng.integers(0, len(h), size=(2000, len(h)))
    ci = lambda a: [float(np.percentile(a[idx].mean(axis=1), q)) for q in (2.5, 97.5)]
    out["hyundai_test_months"] = {
        "loans": int(len(h)), "market_mae": float(err_m.mean()), "same_lender_mae": float(err_b.mean()),
        "rule_mae": float(err_r.mean()), "market_minus_rule_ci95": ci(err_m - err_r),
        "same_lender_minus_rule_ci95": ci(err_b - err_r)}
    print(f"Hyundai test months ({len(h)} loans): market {err_m.mean():.3f}, same lender {err_b.mean():.3f}, rule "
          f"{err_r.mean():.3f}; market minus rule 95% CI {out['hyundai_test_months']['market_minus_rule_ci95']}, "
          f"same lender minus rule {out['hyundai_test_months']['same_lender_minus_rule_ci95']}")
    mc.save_json(out, ROOT / "reports" / "later_deals.json")
    print("wrote reports/later_deals.json")


if __name__ == "__main__":
    {"parse": parse, "score": score}[sys.argv[1]]()
