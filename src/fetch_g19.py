"""Fetch the Federal Reserve G.19 new-car loan rates into data/benchmark/ and app/model/rates_extra.json.

Three series, each with its latest value and period:
- commercial banks, new car, 60-month (RIFLPBCIANM60): average of each bank's most common rate charged in the
  first calendar week of the middle month of each quarter (G.19 footnote 5), so the Aug value is Q3
- commercial banks, new car, 72-month (RIFLPBCIANM72): same survey
- finance companies, new car (RIELPCFAN): amount-weighted average rate on new-car loans made by captive and
  non-captive finance companies in the quarter, produced from Experian's AutoCount Risk Report (G.19 "About")

Values come from the Fed's Data Download Program CSV (full precision). The script checks each one against the
G.19 release table (rounded, with its preliminary flag and release date) and prints a check against FRED.
Run: .venv/bin/python src/fetch_g19.py
"""
import csv
import datetime
import io
import json
import pathlib
import re

import requests
from lxml import html

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "benchmark" / "g19_terms_of_credit.csv"
TIDY = ROOT / "data" / "benchmark" / "g19_auto_rates.csv"
JSON_OUT = ROOT / "app" / "model" / "rates_extra.json"
UA = {"User-Agent": "MarkupCheck student research project"}
RELEASE = "https://www.federalreserve.gov/releases/g19/current/default.htm"
DDP_CSV = ("https://www.federalreserve.gov/datadownload/Output.aspx?rel=G19&series=10264fd36110a9c4906bd99f1daccf29"
           "&lastObs=&from=&to=&filetype=csv&label=include&layout=seriescolumn&type=package")

# key: (Fed series id, FRED id, label, row label in the release's Terms of Credit table, decimals shown there)
SERIES = {
    "bank_new_60m": ("RIFLPBCIANM60_N.M", "RIFLPBCIANM60NM", "Commercial banks, new car, 60-month", "60-month", 2),
    "bank_new_72m": ("RIFLPBCIANM72_N.M", "RIFLPBCIANM72NM", "Commercial banks, new car, 72-month", "72-month", 2),
    "finco_new": ("RIELPCFAN_N.M", "RIELPCFANNM", "Finance companies, new car (all terms)", "Interest rates", 1),
}
MEASURES = {
    "bank_new_60m": "Simple average of each reporting bank's most common APR on 60-month new-car loans, charged in the "
                    "first calendar week of the middle month of the quarter. No credit-score split.",
    "bank_new_72m": "Simple average of each reporting bank's most common APR on 72-month new-car loans, charged in the "
                    "first calendar week of the middle month of the quarter. No credit-score split.",
    "finco_new": "Average APR on new-car loans at captive and non-captive finance companies for the quarter, "
                 "weighted by amount financed, across all loan terms (the Fed produces it from Experian's AutoCount "
                 "Risk Report). No credit-score or term split.",
}
SOURCES = [
    {"title": "Federal Reserve Board, G.19 Consumer Credit, Terms of Credit table", "url": None},  # dated URL set below
    {"title": "G.19 Terms of Credit CSV, Fed Data Download Program (preformatted packages retire Mar 31 2027; "
              "FRED keeps the same series)", "url": DDP_CSV},
    {"title": "Terms of use: Federal Reserve Board website policies, checked 2026-11-15",
     "url": "https://www.federalreserve.gov/disclaimer.htm",
     "note": "Board website information is in the public domain unless otherwise indicated and may be copied and "
             "distributed without permission; cite the Board as the source. The finance-company series is produced "
             "from Experian's AutoCount Risk Report (https://www.federalreserve.gov/releases/g19/about.htm); "
             "credit it as Federal Reserve Board G.19."},
    {"title": "Terms of use: FRED, checked 2026-11-15", "url": "https://fred.stlouisfed.org/legal/",
     "note": "All three series are tagged 'Public Domain: Citation Requested' on FRED: usable without permission if "
             "you cite the source and FRED. FRED's terms bar disruptive scraping, mirroring or robots."},
]


def get(url, **kw):
    r = requests.get(url, timeout=60, **kw)
    r.raise_for_status()
    return r


def write_section(key, section, sources):
    """Replace one section of rates_extra.json, keeping the other script's section."""
    doc = json.loads(JSON_OUT.read_text()) if JSON_OUT.exists() else {}
    built = doc.get("built", {})
    built[key] = datetime.date.today().isoformat()
    srcs = doc.get("sources", {})
    srcs[key] = sources
    doc[key] = section
    out = {"built": {k: built[k] for k in sorted(built)}, "sources": {k: srcs[k] for k in sorted(srcs)}}
    for k in ("g19", "ncua_callreport"):
        if k in doc:
            out[k] = doc[k]
    JSON_OUT.write_text(json.dumps(out, indent=1) + "\n")


# 1. Fed Data Download CSV: 5 metadata rows, then "Time Period" header, then one row per month.
raw = get(DDP_CSV, headers=UA).content
RAW.write_bytes(raw)
rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
header = rows[5]
if header[0] != "Time Period":
    raise SystemExit(f"Unexpected layout in {DDP_CSV}: row 6 starts {header[:2]}")
latest = {}
for key, (fed_id, *_rest) in SERIES.items():
    col = header.index(fed_id)
    obs = [(r[0], float(r[col])) for r in rows[6:] if len(r) > col and re.fullmatch(r"-?\d+(\.\d+)?", r[col])]
    month, value = obs[-1]
    y, m = map(int, month.split("-"))
    latest[key] = {"month": month, "value": value, "quarter": f"{y} Q{(m - 1) // 3 + 1}", "year": y}

# 2. Release page: release date, the quarter column headers ("Q3p" = preliminary) and the rounded values.
page = get(RELEASE, headers=UA)
tree = html.fromstring(page.content)
text = " ".join(tree.text_content().split())
rel = datetime.datetime.strptime(re.search(r"Release Date\*?: ([A-Z][a-z]+ \d{1,2}, \d{4})", text).group(1),
                                 "%B %d, %Y").date()
table = next(t for t in tree.xpath("//table") if "Commercial bank interest rates" in t.text_content())
trs = [[" ".join(c.text_content().split()) for c in tr.xpath("./th|./td")] for tr in table.xpath(".//tr")]
periods = trs[1]  # e.g. ['', '2021', ..., 'Q3', 'Q4', 'Q1', 'Q2', 'Q3p', 'Julr', 'Augr', 'Sepp']
dated = f"https://www.federalreserve.gov/releases/g19/{rel:%Y%m%d}/default.htm"
release_url = dated if requests.get(dated, headers=UA, timeout=60).status_code == 200 else RELEASE
SOURCES[0]["url"] = release_url
SOURCES[0]["title"] += f", release of {rel:%B} {rel.day}, {rel.year}"

section, tidy = {}, []
for key, (fed_id, fred_id, label, row_label, decimals) in SERIES.items():
    v = latest[key]
    q = "Q" + v["quarter"][-1]
    col = max(i for i, p in enumerate(periods) if p.rstrip("pr") == q)  # newest column for that quarter
    in_section = False
    shown = None
    for tr in trs:  # bank rows sit under "Commercial bank interest rates", finance-company rows under "Finance companies"
        if tr and tr[0].startswith(("Commercial bank interest rates", "Finance companies")):
            in_section = tr[0].startswith("Commercial") == key.startswith("bank")
        if in_section and tr and tr[0] == row_label:
            shown = tr[col]
            break
    if shown is None or f"{v['value']:.{decimals}f}" != shown:
        raise SystemExit(f"{fed_id}: data download says {v['value']} for {v['month']}, release table shows {shown!r} "
                         f"in column {periods[col]!r}")
    preliminary = periods[col].endswith("p")
    fred_url = f"https://fred.stlouisfed.org/series/{fred_id}"
    section[key] = {"label": label, "value_pct": v["value"], "period": v["quarter"], "preliminary": preliminary,
                    "observation_month": v["month"], "measures": MEASURES[key], "fed_series": fed_id,
                    "url": fred_url, "release_date": rel.isoformat()}
    tidy.append({"key": key, "label": label, "value_pct": v["value"], "period": v["quarter"],
                 "preliminary": preliminary, "observation_month": v["month"], "fed_series": fed_id,
                 "fred_id": fred_id, "release_date": rel.isoformat(), "url": fred_url, "data_url": DDP_CSV})

    # FRED cross-check (print only, so the JSON doesn't depend on it). FRED's bot filter times out unknown
    # User-Agents (tested Nov 15 2026); requests' own generic one passes.
    try:
        fred = get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={fred_id}").text.strip().splitlines()
        last = [ln.split(",") for ln in fred[1:] if ln.split(",")[1] not in ("", ".")][-1]
        same = last[0][:7] == v["month"] and float(last[1]) == v["value"]
        print(f"FRED {fred_id}: {last[1]} for {last[0][:7]} -> {'matches' if same else 'DIFFERS'}")
        if not same:
            raise SystemExit(f"FRED {fred_id} differs from the Fed data download; check before using.")
    except requests.RequestException as e:
        print(f"FRED {fred_id}: not checked ({type(e).__name__})")

with TIDY.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(tidy[0]))
    w.writeheader()
    w.writerows(tidy)
write_section("g19", section, SOURCES)
for key, s in section.items():
    print(f"{s['label']}: {s['value_pct']}% ({s['period']}{', preliminary' if s['preliminary'] else ''}; "
          f"G.19 released {s['release_date']})")
print(f"-> {TIDY.relative_to(ROOT)}, {RAW.relative_to(ROOT)}, {JSON_OUT.relative_to(ROOT)}")
