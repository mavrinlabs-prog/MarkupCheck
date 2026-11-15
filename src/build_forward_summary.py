"""Write app/model/forward_summary.json: the few forward-test numbers the app shows under "How sure is this?".

The app ships only app/, so it can't read reports/forward_test.json itself. Run after src/forward_test.py score:
.venv/bin/python src/build_forward_summary.py
"""
import datetime
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
f = json.loads((ROOT / "reports" / "forward_test.json").read_text())
months = sorted(f["treasury_5y_forward_months"])
first, last = (datetime.datetime.strptime(m, "%Y-%m") for m in (months[0], months[-1]))
m = f["forward"]["market"]
out = {
    "lender": "CarMax", "loans": f["n_loans"],
    "months": f"{first:%B} to {last:%B %Y}" if first.year == last.year else f"{first:%B %Y} to {last:%B %Y}",
    "model_mae": round(m["model_mae"], 2), "rule_mae": round(m["b1_mae"], 2),
    "coverage_pct": round(100 * m["coverage"], 1), "below_pct": round(100 * m["share_below_range"], 1),
}
path = ROOT / "app" / "model" / "forward_summary.json"
path.write_text(json.dumps(out, indent=1) + "\n")
print(f"wrote {path.relative_to(ROOT)}: {out}")
