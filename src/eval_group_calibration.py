"""Per-group (Mondrian) conformal calibration: does widening each credit tier x new/used group's range separately
bring every group closer to the 80% promise than one width for everyone?

Decision rule, fixed before running: widths are set on the calibration months' first half (cal_width), exactly as
the single width is. They are adopted only if, on the other half (cal_flag, never used to set them):
  (a) the largest gap between any group's coverage and 80% shrinks, and
  (b) overall coverage stays between 78% and 82%.
The test months are reported for both, but never used to decide. Groups with fewer than MIN_N calibration loans keep
the single width. Run: .venv/bin/python src/eval_group_calibration.py   (writes reports/group_calibration.json)
"""
import json
import pathlib
import sys

import joblib
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import mc  # noqa: E402

MIN_N = 200
meta = json.loads((ROOT / "app" / "model" / "meta.json").read_text())
alphas = [float(a) for a in meta["alphas"]]
iL, iH = alphas.index(mc.LO), alphas.index(mc.HI)

bench = mc.load_benchmark()
d, _ = mc.clean(mc.load_raw(), bench)
d = mc.add_features(d, bench)
d = mc.apply_split(d, mc.time_split(d))
d["group"] = d["tier"].astype(str) + "|" + d["is_used"].astype(int).astype(str)
sets = {s: d[d.set == s] for s in ("cal_width", "cal_flag", "test")}


def cover(lo, hi, y):
    return float(np.mean((y >= lo) & (y <= hi)))


out = {"rule": __doc__.split("Decision rule, fixed before running: ")[1].split(" Run:")[0].strip(), "min_n": MIN_N}
for view, info in meta["views"].items():
    models = {a: joblib.load(ROOT / "app" / "model" / info["dir"] / f"q{int(round(a * 100)):02d}.joblib") for a in alphas}
    feats = info["features"]
    grids = {s: mc.predict_grid(models, df, feats) for s, df in sets.items()}
    cw, gw = sets["cal_width"], grids["cal_width"]
    q_global = mc.conformal_qhat(gw[:, iL], gw[:, iH], cw["spread"].to_numpy())
    assert abs(q_global - info["conformal_qhat"]) < 1e-9, "single width differs from meta.json"
    q_group = {}
    for g, idx in cw.groupby("group").indices.items():
        if len(idx) >= MIN_N:
            q_group[g] = mc.conformal_qhat(gw[idx, iL], gw[idx, iH], cw["spread"].to_numpy()[idx])
    res = {"q_global": q_global, "q_group": q_group, "n_cal_width": cw.groupby("group").size().to_dict()}
    for s in ("cal_flag", "test"):
        df, g = sets[s], grids[s]
        y = df["spread"].to_numpy()
        qg = df["group"].map(q_group).fillna(q_global).to_numpy()
        rows = {}
        for name, q in (("single", np.full(len(df), q_global)), ("per_group", qg)):
            lo, hi = g[:, iL] - q, g[:, iH] + q
            by = {k: cover(lo[i], hi[i], y[i]) for k, i in df.groupby("group").indices.items()}
            rows[name] = {"overall": cover(lo, hi, y), "by_group": by,
                          "worst_gap": max(abs(v - 0.80) for v in by.values()),
                          "mean_width": float(np.mean(hi - lo))}
        res[s] = rows
    v = res["cal_flag"]
    res["adopt"] = bool(v["per_group"]["worst_gap"] < v["single"]["worst_gap"]
                        and 0.78 <= v["per_group"]["overall"] <= 0.82)
    out[view] = res
    print(f"{view}: single width {q_global:.3f}; per-group widths " +
          ", ".join(f"{k} {q:.2f}" for k, q in sorted(q_group.items())))
    for s in ("cal_flag", "test"):
        for name in ("single", "per_group"):
            r = res[s][name]
            print(f"  {s:8s} {name:9s} overall {r['overall']:.3f}  worst gap {r['worst_gap']:.3f}  "
                  f"width {r['mean_width']:.2f}  " + " ".join(f"{k}:{c:.3f}" for k, c in sorted(r["by_group"].items())))
    print(f"  adopt (decided on cal_flag only): {res['adopt']}")

(ROOT / "reports" / "group_calibration.json").write_text(json.dumps(out, indent=1, default=float) + "\n")
print("wrote reports/group_calibration.json")
