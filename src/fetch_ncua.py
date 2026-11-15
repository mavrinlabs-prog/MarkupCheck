"""Download NCUA's quarterly credit-union and bank car-loan rates into data/benchmark/ncua_car_rates.csv.

NCUA publishes national average rates that active credit unions and banks reported for the last Friday of
each quarter (data from S&P Global Market Intelligence). They are not broken down by credit score.
Run: .venv/bin/python src/fetch_ncua.py [quarter, default 2025-q4]
"""
import csv
import pathlib
import re
import sys

import requests
from lxml import html

ROOT = pathlib.Path(__file__).resolve().parent.parent
QUARTER = sys.argv[1] if len(sys.argv) > 1 else "2025-q4"
URL = f"https://ncua.gov/analysis/cuso-economic-data/credit-union-bank-rates/credit-union-and-bank-rates-{QUARTER}"
OUT = ROOT / "data" / "benchmark" / "ncua_car_rates.csv"

page = requests.get(URL, headers={"User-Agent": "MarkupCheck student research project"}, timeout=60)
page.raise_for_status()
tree = html.fromstring(page.content)
text = " ".join(tree.text_content().split())
rate_date = re.search(r"for the last Friday of the quarter \(([^)]+)\)", text).group(1)

rows = []
for tr in tree.xpath("//table//tr"):
    cells = [" ".join(c.text_content().split()) for c in tr.xpath("./th|./td")]
    m = re.fullmatch(r"(New|Used) car loan, (\d+) months", cells[0]) if cells else None
    if m:
        rows.append({"new_or_used": m.group(1).lower(), "term_months": int(m.group(2)),
                     "credit_union_pct": float(cells[1]), "bank_pct": float(cells[2]),
                     "rate_date": rate_date, "quarter": QUARTER, "source_url": URL})
if len(rows) != 4:
    raise SystemExit(f"Expected 4 car-loan rows on {URL}, found {len(rows)}; the page layout may have changed.")

with OUT.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
print(f"{len(rows)} rows, rates for {rate_date} -> {OUT.relative_to(ROOT)}")
