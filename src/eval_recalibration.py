"""Does recalibrating on the newest filings fix the range on newer loans? Tested on CarMax, the only lender with
deals filed after training (src/forward_test.py parses them).

Fixed before running:
- Calibration window: forward months 2026-02 to 2026-05. Evaluation window: 2026-06 to 2026-08, never used to set
  anything. The models themselves are never refitted.
- Methods: "frozen" (as shipped); "width" (recompute the conformal width on the window); "shift+width" (first move
  the typical price by the window's median miss, then recompute the width).
- A method is adopted for the app's same-lender CarMax view only if, on the evaluation window, its coverage is
  between 78% and 82% and its typical-price error is no worse than frozen. If both pass, the simpler one ("width").
- Also a monthly routine: each month from 2026-04 on is scored after recalibrating on the two months before it.
Run after src/forward_test.py parse: .venv/bin/python -I src/eval_recalibration.py   (writes reports/recalibration.json)
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

CAL = ("2026-02", "2026-05")
EVAL = ("2026-06", "2026-08")

meta = json.loads((ft.MODEL_DIR / "meta.json").read_text())
bench = mc.load_benchmark()
old, _ = mc.clean(mc.load_raw(), bench)
old = mc.add_features(old, bench)
old = mc.apply_split(old, mc.time_split(old))
train = old[old.set == "train"]
b0, b1 = mc.baseline_b0(train), mc.baseline_b1(train)
raw = pd.concat([pd.read_parquet(ft.PARQUET_DIR / f"{slug}.parquet") for slug in ft.DEALS], ignore_index=True)
clean, _ = mc.clean(raw, bench)
d = mc.add_features(clean, bench)
d = d[d.origination_month > meta["newest_origination_month"]].copy()


def recal(s: pd.DataFrame, cal: pd.Series, qhat0: float, shift: bool) -> pd.DataFrame:
    """Re-centre (optionally) and re-widen the frozen model's raw 10-90 range using the calibration rows `cal`."""
    raw_lo, raw_hi = s.lo + qhat0, s.hi - qhat0
    c = s[cal]
    move = float(np.median(c.y - c["mid"])) if shift else 0.0
    q = mc.conformal_qhat((raw_lo[cal] + move).to_numpy(), (raw_hi[cal] + move).to_numpy(), c.y.to_numpy())
    return s.assign(mid=s["mid"] + move, lo=raw_lo + move - q, hi=raw_hi + move + q), move, q


out = {"rule": __doc__.split("Fixed before running:")[1].split("Run after")[0].strip(), "loans": int(len(d))}
for view in ("market", "same_lender"):
    models = ft.load_models(view, meta)
    s = ft.score_frame(d, models, meta, view, b1, b0).reset_index(drop=True)
    qhat0 = float(meta["views"][view]["conformal_qhat"])
    cal = s.month.between(*CAL)
    ev = s.month.between(*EVAL)
    res = {"frozen": ft.summary(s[ev])}
    for name, shift in (("width", False), ("shift+width", True)):
        r, move, q = recal(s, cal, qhat0, shift)
        res[name] = {**ft.summary(r[ev]), "shift_points": move, "qhat": q}
    for name in ("width", "shift+width"):
        e = res[name]
        res[name]["passes"] = bool(0.78 <= e["coverage"] <= 0.82 and e["model_mae"] <= res["frozen"]["model_mae"] + 1e-12)
    res["adopt"] = "width" if res["width"]["passes"] else "shift+width" if res["shift+width"]["passes"] else None
    monthly = []
    months = sorted(s.month.unique())
    for i, m in enumerate(months):
        if i < 2:
            continue
        window = s.month.isin(months[i - 2:i])
        r, move, q = recal(s, window, qhat0, True)
        f, g = ft.summary(s[s.month == m]), ft.summary(r[s.month == m])
        monthly.append({"month": m, "loans": f["loans"], "frozen_coverage": f["coverage"], "monthly_coverage": g["coverage"],
                        "frozen_mae": f["model_mae"], "monthly_mae": g["model_mae"]})
    res["monthly_routine"] = monthly
    n = sum(r["loans"] for r in monthly)
    res["monthly_routine_pooled"] = {
        "months": f"{monthly[0]['month']} to {monthly[-1]['month']}", "loans": n,
        **{k: sum(r[k] * r["loans"] for r in monthly) / n
           for k in ("frozen_coverage", "monthly_coverage", "frozen_mae", "monthly_mae")}}
    out[view] = res
    print(f"\n{view} (frozen width {qhat0:.3f}); calibrate {CAL[0]}..{CAL[1]}, evaluate {EVAL[0]}..{EVAL[1]}:")
    for name in ("frozen", "width", "shift+width"):
        e = res[name]
        extra = f"  shift {e['shift_points']:+.2f}, width {e['qhat']:.2f}, passes {e['passes']}" if name != "frozen" else ""
        print(f"  {name:12s} coverage {e['coverage']:.3f}  prime used {e['coverage_prime_used']:.3f}  MAE {e['model_mae']:.3f}  "
              f"width {e['mean_width']:.2f}  below {e['share_below_range']:.3f}  well above {e['share_well_above']:.3f}{extra}")
    print(f"  adopt: {res['adopt']}")
    print("  monthly routine (recalibrate on the 2 months before):")
    for r in monthly:
        print(f"    {r['month']} {r['loans']:6d} loans: coverage {r['frozen_coverage']:.3f} -> {r['monthly_coverage']:.3f}, "
              f"MAE {r['frozen_mae']:.3f} -> {r['monthly_mae']:.3f}")
    pl = res["monthly_routine_pooled"]
    print(f"    pooled {pl['months']}, {pl['loans']:,} loans: coverage {pl['frozen_coverage']:.3f} -> "
          f"{pl['monthly_coverage']:.3f}, MAE {pl['frozen_mae']:.3f} -> {pl['monthly_mae']:.3f}")

(ROOT / "reports" / "recalibration.json").write_text(json.dumps(out, indent=1, default=float) + "\n")
print("\nwrote reports/recalibration.json")
