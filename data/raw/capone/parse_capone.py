"""Parse Capital One Prime Auto Receivables Trust EX-102 (Schedule AL) pool files into the CONTRACT Parquet format.
Adapted from data/raw/carmax/parse_carmax.py (same namespace, same columns); issuer slug 'capone'.

usage:
  .venv/bin/python -I data/raw/capone/parse_capone.py parse <slug> [<slug> ...]
  .venv/bin/python -I data/raw/capone/parse_capone.py manifest
  .venv/bin/python -I data/raw/capone/parse_capone.py check

Each `parse` run writes data/parquet/capone/<slug>.parquet and data/raw/capone/stats_<slug>.json.
`manifest` builds data/parquet/capone/manifest.json from the stats files that exist.
`check` re-reads each Parquet and prints the brief's checks against the prospectus figures below.
"""
import json
import math
import os
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq
from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PARQUET_DIR = os.path.join(ROOT, "data", "parquet", "capone")
NS = "{http://www.sec.gov/edgar/document/absee/autoloan/assetdata}"
USER_AGENT = "MarkupCheck student research project"
ISSUER = "capone"

# Capital One writes paymentToIncomePercentage already in percent (5.82 = 5.82%; median about 5, max about 21),
# unlike CarMax's fractions, so pti_pct is the value as written. originalInterestRatePercentage is a fraction
# (0.0599 = 5.99%) like CarMax's, so apr_pct is still x100.
PTI_SCALE = 1

# Only two Capital One Prime deals were priced between Jan 2024 and Feb 2026 (depositor Capital One Auto
# Receivables LLC, CIK 0001133438, filing list read Nov 15 2026): 2024-1 (pool filed 2024-11-13) and 2025-1
# (pool filed 2025-10-22). The one before is 2023-2 (Sep 2023) and the one after is 2026-1 (Sep 2026).
# Prospectus figures were read from each 424B5 ("Composition of the Pool of Receivables As of the Cut-off Date").
DEALS = {
    "capone_2024-1": dict(
        deal="Capital One Prime Auto Receivables Trust 2024-1", cik="0002039534", filing_date="2024-11-13",
        accession="0000950131-24-004424", xml="copart241ex102_1112-1953.xml", size=190447160, cutoff="2024-09-30",
        h424="0001193125-24-258605 (2024-11-14)", b424="0001193125-24-263327 (2024-11-21)",
        prospectus_loan_count=49532, prospectus_pool_balance=1116124822.45, prospectus_rate_range=(1.99, 12.99),
        prospectus_fico_range=(700, 885), prospectus_new_pct_by_balance=28.57,
        other_pool_files=None,
        window_note=("No Capital One Prime deal was filed Jan-Jun 2024 (2023-2 priced in Sep-Oct 2023, 2024-1 in "
                     "Nov 2024); 2024-1 is the nearest deal filed Jan 2024 - Feb 2026. It is also the nearest to the "
                     "Jan-Jun 2025 window (filed 49 days before it; 2025-1 came 114 days after it)."),
    ),
    "capone_2025-1": dict(
        deal="Capital One Prime Auto Receivables Trust 2025-1", cik="0002089663", filing_date="2025-10-22",
        accession="0001193125-25-247047", xml="copart251ex102_1021-1943lp.xml", size=278614189, cutoff="2025-09-30",
        h424="0001193125-25-248706 (2025-10-23)", b424="0001193125-25-258371 (2025-10-30)",
        prospectus_loan_count=72469, prospectus_pool_balance=1456229893.76, prospectus_rate_range=(1.90, 12.99),
        prospectus_fico_range=(700, 884), prospectus_new_pct_by_balance=26.46,
        other_pool_files=dict(
            xml_filing="copart251absee_1022-0951sp.htm", accession="0001193125-25-246960", label="sp",
            scenario="Base Transaction", pool_balance="1,092,162,854.95", count=54436,
            chosen_scenario="Upsize Transaction"),
        window_note="Filed 2025-10-22, inside the Oct 2025 - Feb 28 2026 window; the only Capital One Prime deal in it.",
    ),
}

SCHEMA = pa.schema([
    ("issuer", pa.string()), ("deal", pa.string()), ("deal_cik", pa.string()), ("source_url", pa.string()),
    ("filing_date", pa.string()), ("asset_number", pa.string()), ("origination_month", pa.string()),
    ("original_loan_amount", pa.float64()), ("original_term_months", pa.int64()), ("apr_pct", pa.float64()),
    ("interest_rate_type_code", pa.string()), ("subvented", pa.string()), ("vehicle_make", pa.string()),
    ("vehicle_model", pa.string()), ("new_used_code", pa.string()), ("vehicle_model_year", pa.int64()),
    ("vehicle_type_code", pa.string()), ("vehicle_value", pa.float64()), ("vehicle_value_source_code", pa.string()),
    ("credit_score_type", pa.string()), ("credit_score", pa.float64()),
    ("income_verification_code", pa.string()), ("employment_verification_code", pa.string()),
    ("co_obligor", pa.bool_()), ("pti_pct", pa.float64()), ("state", pa.string()),
])

CODE_FIELDS = ["subvented", "new_used_code", "credit_score_type", "interest_rate_type_code", "vehicle_type_code",
               "vehicle_value_source_code", "income_verification_code", "employment_verification_code"]


def to_float(text):
    if text is None:
        return math.nan
    try:
        return float(text)
    except ValueError:
        return math.nan


def to_int(text):
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def to_bool(text):
    if text is None:
        return None
    t = text.strip().lower()
    return {"true": True, "false": False}.get(t)


def month_from_mmyyyy(text):
    if text is None:
        return None
    mm, yyyy = text.strip().split("/")
    return f"{yyyy}-{int(mm):02d}"


def source_url(d):
    return (f"https://www.sec.gov/Archives/edgar/data/{int(d['cik'])}/"
            f"{d['accession'].replace('-', '')}/{d['xml']}")


def parse(slug):
    d = DEALS[slug]
    xml_path = os.path.join(HERE, d["xml"])
    url = source_url(d)
    cols = {name: [] for name in SCHEMA.names}
    seen = set()
    rows_parsed = dup = 0
    months = []
    codes = {k: Counter() for k in CODE_FIELDS}
    nonnumeric_scores = Counter()
    end_balance = 0.0
    new_balance = 0.0
    period_ends = Counter()
    pti_raw = []

    for _, elem in etree.iterparse(xml_path, events=("end",), tag=NS + "assets"):
        rec = {c.tag[len(NS):]: (c.text.strip() if c.text is not None else None) for c in elem}
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]
        rows_parsed += 1
        an = rec.get("assetNumber")
        if an in seen:
            dup += 1
            continue
        seen.add(an)

        score_raw = rec.get("obligorCreditScore")
        score = to_float(score_raw)
        if math.isnan(score):
            nonnumeric_scores[score_raw] += 1
        apr = to_float(rec.get("originalInterestRatePercentage"))
        pti = to_float(rec.get("paymentToIncomePercentage"))
        if not math.isnan(pti):
            pti_raw.append(pti)
        om = month_from_mmyyyy(rec.get("originationDate"))
        months.append(om)
        bal = to_float(rec.get("reportingPeriodActualEndBalanceAmount"))
        if not math.isnan(bal):
            end_balance += bal
            if rec.get("vehicleNewUsedCode") == "1":
                new_balance += bal
        period_ends[rec.get("reportingPeriodEndingDate")] += 1

        row = {
            "issuer": ISSUER, "deal": d["deal"], "deal_cik": d["cik"], "source_url": url,
            "filing_date": d["filing_date"], "asset_number": an, "origination_month": om,
            "original_loan_amount": to_float(rec.get("originalLoanAmount")),
            "original_term_months": to_int(rec.get("originalLoanTerm")),
            # round() removes float noise such as 5.490000000000001 from 0.0549 * 100
            "apr_pct": round(apr * 100, 6),
            "interest_rate_type_code": rec.get("originalInterestRateTypeCode"),
            "subvented": rec.get("subvented"),
            "vehicle_make": rec.get("vehicleManufacturerName"), "vehicle_model": rec.get("vehicleModelName"),
            "new_used_code": rec.get("vehicleNewUsedCode"),
            "vehicle_model_year": to_int(rec.get("vehicleModelYear")),
            "vehicle_type_code": rec.get("vehicleTypeCode"),
            "vehicle_value": to_float(rec.get("vehicleValueAmount")),
            "vehicle_value_source_code": rec.get("vehicleValueSourceCode"),
            "credit_score_type": rec.get("obligorCreditScoreType"), "credit_score": score,
            "income_verification_code": rec.get("obligorIncomeVerificationLevelCode"),
            "employment_verification_code": rec.get("obligorEmploymentVerificationCode"),
            "co_obligor": to_bool(rec.get("coObligorIndicator")),
            "pti_pct": round(pti * PTI_SCALE, 6) if not math.isnan(pti) else math.nan,
            "state": rec.get("obligorGeographicLocation"),
        }
        for k, v in row.items():
            cols[k].append(v)
        for k in CODE_FIELDS:
            codes[k][row[k]] += 1

    table = pa.Table.from_pydict(cols, schema=SCHEMA)
    os.makedirs(PARQUET_DIR, exist_ok=True)
    out = os.path.join(PARQUET_DIR, slug + ".parquet")
    pq.write_table(table, out, compression="zstd")
    scores = [s for s in cols["credit_score"] if not math.isnan(s)]
    stats = {
        "slug": slug, "source_url": url, "xml_file": d["xml"], "bytes": os.path.getsize(xml_path),
        "rows_parsed": rows_parsed, "rows_written": len(cols["asset_number"]),
        "duplicate_asset_numbers_dropped": dup,
        "origination_month_min": min(m for m in months if m), "origination_month_max": max(m for m in months if m),
        "codes": {k: dict(v) for k, v in codes.items()},
        "nonnumeric_credit_score_values": dict(nonnumeric_scores),
        "credit_score_min": min(scores) if scores else None, "credit_score_max": max(scores) if scores else None,
        "credit_score_outside_300_850": sum(1 for s in scores if s < 300 or s > 850),
        "sum_reporting_period_actual_end_balance": round(end_balance, 2),
        "new_vehicle_pct_by_end_balance": round(100 * new_balance / end_balance, 2) if end_balance else None,
        "reporting_period_ending_dates": dict(period_ends),
        "pti_as_written_min_median_max": [min(pti_raw), statistics.median(pti_raw), max(pti_raw)] if pti_raw else None,
        "parquet_bytes": os.path.getsize(out),
    }
    with open(os.path.join(HERE, f"stats_{slug}.json"), "w") as f:
        json.dump(stats, f, indent=1, sort_keys=True)
    print(json.dumps({k: v for k, v in stats.items() if k != "codes"}, indent=1))
    for k in ("credit_score_type", "subvented", "new_used_code", "interest_rate_type_code"):
        print(k, stats["codes"][k])


def why_first(d):
    first = ("it is the trust's first filing of any kind" if d["other_pool_files"] is None else
             "it and the other pool file filed the same day are the trust's first filings of any kind")
    text = (f"Filed {d['filing_date']} under the trust's CIK {d['cik']} (accession {d['accession']}); {first} "
            f"and it describes the pool as of the {d['cutoff']} cut-off date (reportingPeriodEndingDate "
            f"in every row). It came before the preliminary prospectus (424H {d['h424']}) and the final prospectus "
            f"(424B5 {d['b424']}); the trust's first monthly ABS-EE files came in the December after. ")
    o = d["other_pool_files"]
    if o is None:
        text += "Capital One filed one pool file for this deal (no size scenarios). "
    else:
        text += (f"Capital One filed two pool files that day, one per deal size in the 424H: '{o['label']}' (accession "
                 f"{o['accession']}, the 424H's {o['scenario']}: pool ${o['pool_balance']}, {o['count']:,} receivables), "
                 f"not downloaded, and this 'lp' file, the 424H's {o['chosen_scenario']}. ")
    text += (f"The 424B5 gives {d['prospectus_loan_count']:,} receivables with a ${d['prospectus_pool_balance']:,.2f} "
             "aggregate principal balance as of the cut-off date; the parsed row count and the sum of "
             "reportingPeriodActualEndBalanceAmount are compared with those in TASKS_capone.md and the check command.")
    return text


def build_manifest():
    deals, merged = [], {k: Counter() for k in CODE_FIELDS}
    missing = []
    for slug, d in DEALS.items():
        sp = os.path.join(HERE, f"stats_{slug}.json")
        if not os.path.exists(sp):
            missing.append(slug)
            continue
        s = json.load(open(sp))
        for k in CODE_FIELDS:
            merged[k].update(s["codes"][k])
        deals.append({
            "deal": d["deal"], "deal_cik": d["cik"], "filing_date": d["filing_date"], "accession": d["accession"],
            "source_url": s["source_url"],
            "why_this_is_the_first_pool_filing": why_first(d),
            "why_this_deal": d["window_note"],
            "bytes": s["bytes"], "rows_parsed": s["rows_parsed"], "rows_written": s["rows_written"],
            "duplicate_asset_numbers_dropped": s["duplicate_asset_numbers_dropped"],
            "origination_month_min": s["origination_month_min"], "origination_month_max": s["origination_month_max"],
            "prospectus_loan_count_if_found": d["prospectus_loan_count"],
            "prospectus_pool_balance": d["prospectus_pool_balance"],
            "sum_reporting_period_actual_end_balance": s["sum_reporting_period_actual_end_balance"],
            "code_values_seen_this_deal": {k: s["codes"][k] for k in
                                           ("credit_score_type", "subvented", "new_used_code", "interest_rate_type_code")},
        })
    notes = json.load(open(os.path.join(HERE, "manifest_notes.json")))
    manifest = {
        "issuer": ISSUER, "user_agent": USER_AGENT, "deals": deals,
        "code_values_seen": {k: dict(v) for k, v in merged.items()},
        "spec_url": notes["spec_url"], "notes": notes["notes"], "couldnt_confirm": notes["couldnt_confirm"],
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "deals_not_yet_parsed": missing,
    }
    with open(os.path.join(PARQUET_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print("manifest written; deals:", [x["deal"] for x in deals], "missing:", missing)


def check():
    """Re-read each Parquet (not the parse-time stats) and print the brief's checks."""
    import pandas as pd
    manifest = json.load(open(os.path.join(PARQUET_DIR, "manifest.json")))
    by_deal = {x["deal"]: x for x in manifest["deals"]}
    fails = 0
    for slug, d in DEALS.items():
        path = os.path.join(PARQUET_DIR, slug + ".parquet")
        t = pq.read_table(path)
        df = t.to_pandas()
        s = json.load(open(os.path.join(HERE, f"stats_{slug}.json")))
        m = by_deal[d["deal"]]
        print(f"\n== {os.path.relpath(path, ROOT)}  ({len(df):,} rows, {d['deal']})")

        def line(ok, name, detail):
            nonlocal fails
            fails += 0 if ok else 1
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}  -- {detail}")

        line(t.schema.names == SCHEMA.names, "column names and order match CONTRACT", "")
        line(t.schema.equals(SCHEMA), "column types match CONTRACT", "")
        line(len(df) == d["prospectus_loan_count"], "rows equal the 424B5 receivable count",
             f"parquet {len(df):,}, 424B5 {d['prospectus_loan_count']:,}")
        line(len(df) == m["rows_written"], "rows equal manifest rows_written", f"manifest {m['rows_written']:,}")
        diff = s["sum_reporting_period_actual_end_balance"] - d["prospectus_pool_balance"]
        line(abs(diff) < 0.005, "sum of ending balances equals the 424B5 pool balance",
             f"file ${s['sum_reporting_period_actual_end_balance']:,.2f}, 424B5 ${d['prospectus_pool_balance']:,.2f}, "
             f"difference {diff:,.2f}")
        line(list(s["reporting_period_ending_dates"]) == [datetime.strptime(d["cutoff"], "%Y-%m-%d").strftime("%m-%d-%Y")],
             "every row's reportingPeriodEndingDate is the cut-off date", str(s["reporting_period_ending_dates"]))
        line(df.asset_number.duplicated().sum() == 0, "no duplicate asset_number", f"{df.asset_number.duplicated().sum()} duplicates")
        bad_month = (~df.origination_month.str.fullmatch(r"\d{4}-\d{2}")).sum()
        line(bad_month == 0, "origination_month parses as YYYY-MM",
             f"{bad_month} bad; range {df.origination_month.min()} to {df.origination_month.max()}")
        late = (df.origination_month > "2026-01").sum()
        line(late == 0, "no loan originated after Jan 2026", f"{late} rows")
        numeric = df.credit_score.notna()
        line(True, "share of rows with a numeric credit_score", f"{numeric.mean():.4%} ({numeric.sum():,} of {len(df):,})")
        for typ, g in df.groupby("credit_score_type", dropna=False):
            sc = g.credit_score.dropna()
            if len(sc):
                lo, hi = d["prospectus_fico_range"]
                line(sc.min() >= lo and sc.max() <= hi,
                     f"credit_score for type {typ!r} within the 424B5 FICO range {lo}-{hi}",
                     f"n {len(sc):,}, min {sc.min():g}, median {sc.median():g}, max {sc.max():g}")
            else:
                line(True, f"credit_score for type {typ!r}", f"n {len(g):,}, all NaN")
        lo, hi = d["prospectus_rate_range"]
        line(df.apr_pct.min() >= lo - 1e-9 and df.apr_pct.max() <= hi + 1e-9,
             f"apr_pct within the 424B5 contract-rate range {lo}-{hi}",
             f"min {df.apr_pct.min():g}, median {df.apr_pct.median():g}, max {df.apr_pct.max():g}")
        line(abs(s["new_vehicle_pct_by_end_balance"] - d["prospectus_new_pct_by_balance"]) < 0.01,
             "new-vehicle share by balance equals the 424B5", f"file {s['new_vehicle_pct_by_end_balance']}%, "
             f"424B5 {d['prospectus_new_pct_by_balance']}%")
        line(df.pti_pct.dropna().between(0, 100).all(), "pti_pct is in percent (0-100)",
             f"min {df.pti_pct.min():g}, median {df.pti_pct.median():g}, max {df.pti_pct.max():g}, NaN {df.pti_pct.isna().sum()}")
        months = df.origination_month.value_counts().sort_index()
        print(f"  origination months: {len(months)} distinct; rows per year "
              f"{df.origination_month.str[:4].value_counts().sort_index().to_dict()}")
    print(f"\n{len(DEALS)} file(s) checked, {fails} check(s) failed")
    return fails


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "parse":
        for slug in sys.argv[2:]:
            parse(slug)
    elif cmd == "manifest":
        build_manifest()
    elif cmd == "check":
        sys.exit(1 if check() else 0)
    else:
        raise SystemExit(__doc__)
