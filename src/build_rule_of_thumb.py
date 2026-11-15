"""Write app/model/rule_of_thumb.json: the B1 rule of thumb (credit tier x new/used ranges from the training months),
so the app can show it next to the model's range for the buyer's own offer.

The table is rebuilt exactly as the notebook builds it (same cleaning, same time split, mc.baseline_b1), and the
script stops unless the rule's test error matches reports/results.json, so the app shows the same rule the write-up
reports. Values are spreads (APR minus the 5-year Treasury); the app adds the offer's Treasury rate.

Run after the notebook: .venv/bin/python src/build_rule_of_thumb.py
"""
import json
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import mc  # noqa: E402

results = json.loads((ROOT / "reports" / "results.json").read_text())
metrics = {m["method"]: m for m in results["metrics_test"]}
rule, model = metrics["B1 credit tier x new/used"], metrics["Model + conformal calibration"]

bench = mc.load_benchmark()
d, _ = mc.clean(mc.load_raw(), bench)
d = mc.add_features(d, bench)
d = mc.apply_split(d, mc.time_split(d))
train, test = d[d.set == "train"], d[d.set == "test"]
b0, b1 = mc.baseline_b0(train), mc.baseline_b1(train)

mae = float(np.mean(np.abs(test["spread"].to_numpy() - mc.predict_b1(b1, b0, test)["q50"].to_numpy())))
if abs(mae - rule["MAE_points"]) > 1e-9:
    raise SystemExit(f"rule error {mae} differs from results.json {rule['MAE_points']}; rerun the notebook first.")

table = {f"{tier}|{int(used)}": {"q_lo": round(float(r.q_lo), 4), "q50": round(float(r.q50), 4),
                                  "q_hi": round(float(r.q_hi), 4), "n_train": int(r.n_train)}
         for (tier, used), r in b1.iterrows()}
out = {
    "about": "B1 rule of thumb: 10th, 50th and 90th percentile spread (APR minus 5-year Treasury) by credit tier and "
             "new/used in the training months; b0 is the fallback for an empty cell.",
    "lo": mc.LO, "hi": mc.HI, "table": table,
    "b0": {"q_lo": round(b0[mc.LO], 4), "q50": round(b0[0.5], 4), "q_hi": round(b0[mc.HI], 4)},
    "test": {"rule_mae": round(rule["MAE_points"], 2), "model_mae": round(model["MAE_points"], 2),
             "rule_coverage_pct": round(100 * rule["coverage_of_80pct_range"], 1),
             "model_coverage_pct": round(100 * model["coverage_of_80pct_range"], 1),
             "rule_width": round(rule["mean_width_points"], 2), "model_width": round(model["mean_width_points"], 2)},
}
path = ROOT / "app" / "model" / "rule_of_thumb.json"
path.write_text(json.dumps(out, indent=1) + "\n")
print(f"wrote {path.relative_to(ROOT)}: {len(table)} cells; rule test error {mae:.3f} matches results.json")
