"""Monthly recalibration of the same-lender view from each lender's newest filings.

The models are never refitted. For each lender with loans originated after the training data's newest month (today:
CarMax's 2026-2 to 2026-4 deals and Capital One Prime 2026-1, parsed by src/forward_test.py), this script:
  1. tests the monthly routine on that lender's newer months: each month is scored after re-centring the typical price
     by the median miss and re-widening the range on the two months before it (as in src/eval_recalibration.py);
  2. computes the recalibration to use now, from the lender's two newest months.

Rule: a lender's recalibration is written to app/model/meta.json (views.same_lender.recalibrated) only if, in step 1,
the routine's pooled coverage is between 78% and 82%, its typical-price error is no worse than the frozen model's, and
the two newest months hold at least 2,000 loans. The 78-82% band is the one src/eval_recalibration.py fixed before any
recalibration was run. An earlier version of this script used a wider 75-85% band, chosen after seeing that script's
results; CarMax passed it at 77.2%. Because that band was not set in advance, we went back to the one that was, so
today no lender is recalibrated and the app shows the newer-loans warning instead. The app then uses it when the buyer names that lender. Every number is written to reports/recalibrate.json.

Run after src/forward_test.py parse and parse_capone: .venv/bin/python -I src/recalibrate.py [--apply]
"""
import json
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import forward_test as ft  # noqa: E402
import mc  # noqa: E402

MIN_LOANS = 2000
COVERAGE_BAND = (0.78, 0.82)  # src/eval_recalibration.py's band, fixed before any recalibration was run
FILES = {"carmax": [ft.PARQUET_DIR / f"{s}.parquet" for s in ft.DEALS],
         "capone": [ft.PARQUET_DIR / f"{s}.parquet" for s in ft.CAPONE]}


def recal_params(s: pd.DataFrame, rows: pd.Series, qhat0: float) -> tuple[float, float]:
    """Median miss and the conformal width of the re-centred raw 10-90 range, both from `rows`."""
    c = s[rows]
    move = float(np.median(c.y - c["mid"]))
    q = mc.conformal_qhat((c.lo + qhat0 + move).to_numpy(), (c.hi - qhat0 + move).to_numpy(), c.y.to_numpy())
    return move, q


def main(apply: bool):
    meta_path = ft.MODEL_DIR / "meta.json"
    meta = json.loads(meta_path.read_text())
    bench = mc.load_benchmark()
    old, _ = mc.clean(mc.load_raw(), bench)
    old = mc.add_features(old, bench)
    old = mc.apply_split(old, mc.time_split(old))
    train = old[old.set == "train"]
    b0, b1 = mc.baseline_b0(train), mc.baseline_b1(train)
    models = ft.load_models("same_lender", meta)
    qhat0 = float(meta["views"]["same_lender"]["conformal_qhat"])
    out, chosen = {"rule": __doc__.split("Rule:")[1].split("Run after")[0].strip(), "lenders": {}}, {}
    for lender, files in FILES.items():
        raw = pd.concat([pd.read_parquet(f) for f in files if f.exists()], ignore_index=True)
        if lender == "capone":
            raw["credit_score_type"] = raw["credit_score_type"].replace(ft.CAPONE_SCORE_TYPE_MAP)
        raw["issuer"] = lender
        clean, _ = mc.clean(raw, bench)
        d = mc.add_features(clean, bench)
        d = d[d.origination_month > meta["newest_origination_month"]].copy()
        months = sorted(d.origination_month.unique())
        if len(months) < 3:  # the routine needs two months to calibrate and one to test
            out["lenders"][lender] = {"months": months, "passes": False,
                                      "reason": f"{len(d):,} loans in {len(months)} newer month(s); the routine needs 3"}
            print(f"{lender}: {out['lenders'][lender]['reason']}; skipped")
            continue
        s = ft.score_frame(d, models, meta, "same_lender", b1, b0).reset_index(drop=True)
        rows = []
        for i, m in enumerate(months[2:], start=2):
            move, q = recal_params(s, s.month.isin(months[i - 2:i]), qhat0)
            cur = s[s.month == m]
            lo, hi = cur.lo + qhat0 + move - q, cur.hi - qhat0 + move + q
            rows.append({"month": m, "loans": int(len(cur)),
                         "frozen_coverage": float(((cur.y >= cur.lo) & (cur.y <= cur.hi)).mean()),
                         "routine_coverage": float(((cur.y >= lo) & (cur.y <= hi)).mean()),
                         "frozen_mae": float(np.mean(np.abs(cur.y - cur["mid"]))),
                         "routine_mae": float(np.mean(np.abs(cur.y - (cur["mid"] + move))))})
        n = sum(r["loans"] for r in rows)
        pooled = {k: sum(r[k] * r["loans"] for r in rows) / n if n else float("nan")
                  for k in ("frozen_coverage", "routine_coverage", "frozen_mae", "routine_mae")}
        newest = s.month.isin(months[-2:])
        move, q = recal_params(s, newest, qhat0)
        passes = bool(n and COVERAGE_BAND[0] <= pooled["routine_coverage"] <= COVERAGE_BAND[1]
                      and pooled["routine_mae"] <= pooled["frozen_mae"]
                      and int(newest.sum()) >= MIN_LOANS)
        out["lenders"][lender] = {"months": months, "routine": rows, "pooled": pooled, "passes": passes,
                                  "now": {"shift_points": move, "qhat": q, "months": months[-2:],
                                          "loans": int(newest.sum()), "coverage_expected": pooled["routine_coverage"]}}
        print(f"{lender}: {len(s):,} newer loans {months[0]}..{months[-1]}; routine pooled coverage "
              f"{pooled['frozen_coverage']:.3f} -> {pooled['routine_coverage']:.3f}, error {pooled['frozen_mae']:.3f} -> "
              f"{pooled['routine_mae']:.3f}; now: shift {move:+.2f}, width {q:.2f} from {months[-2]}..{months[-1]} "
              f"({int(newest.sum()):,} loans); passes rule: {passes}")
        if passes:
            chosen[lender] = out["lenders"][lender]["now"]
    (ROOT / "reports" / "recalibrate.json").write_text(json.dumps(out, indent=1, default=float) + "\n")
    if apply:
        meta["views"]["same_lender"]["recalibrated"] = chosen
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")
        print(f"wrote {len(chosen)} recalibration(s) to app/model/meta.json: {sorted(chosen)}")
    print("wrote reports/recalibrate.json")


if __name__ == "__main__":
    main("--apply" in sys.argv)
