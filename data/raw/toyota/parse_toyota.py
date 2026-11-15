"""Parse Toyota EX-102 (Schedule AL) XML pool files into the CONTRACT Parquet format.

Adapted from data/raw/carmax/parse_carmax.py (same namespace, same CONTRACT columns).

usage:
  .venv/bin/python -I data/raw/toyota/parse_toyota.py parse <slug> [<slug> ...]
  .venv/bin/python -I data/raw/toyota/parse_toyota.py manifest

Each `parse` run writes data/parquet/toyota/<slug>.parquet and data/raw/toyota/stats_<slug>.json.
`manifest` builds data/parquet/toyota/manifest.json from the stats files that exist and manifest_notes.json.
"""
import json
import math
import os
import re
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq
from lxml import etree

ISSUER = "toyota"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PARQUET_DIR = os.path.join(ROOT, "data", "parquet", ISSUER)
NS = "{http://www.sec.gov/edgar/document/absee/autoloan/assetdata}"
USER_AGENT = "MarkupCheck student research project"
CENT = Decimal("0.01")

# Each deal's pool ABS-EE filings, all filed the same day before the 424H: Toyota files one EX-102 per deal size
# offered ('sp' small, 'mp' medium, 'lp' large pool). The file parsed is the one whose row count equals the final
# prospectus (424B5) "Number of Receivables"; the others were not downloaded.
DEALS = {
    "toyota_2024-A": dict(
        deal="Toyota Auto Receivables 2024-A Owner Trust", cik="0002002262", filing_date="2024-01-16",
        accession="0000950131-24-000229", xml="taot24aex102_0111-1650lp.xml", size=270125622, scenario="lp",
        other_pool_files=[("sp", "0000950131-24-000227", "taot24aex102_0111-1654sp.xml", 208272565)],
        h424="0000929638-24-000153 (2024-01-18)", b424="0000929638-24-000196 (2024-01-25)",
        b424_url="https://www.sec.gov/Archives/edgar/data/2002262/000092963824000196/taot2024a-424b5.htm",
        prospectus_loan_count=71726, prospectus_pool_balance="1908468799.65",
    ),
    "toyota_2025-A": dict(
        deal="Toyota Auto Receivables 2025-A Owner Trust", cik="0002047571", filing_date="2025-01-14",
        accession="0000950131-25-000124", xml="taot25aex102_0113-1648lp.xml", size=260362386, scenario="lp",
        other_pool_files=[("sp", "0000950131-25-000122", "taot25aex102_0113-1741sp.xml", 205445118)],
        h424="0000929638-25-000154 (2025-01-15)", b424="0000929638-25-000276 (2025-01-24)",
        b424_url="https://www.sec.gov/Archives/edgar/data/2047571/000092963825000276/taot2025a-424b5.htm",
        prospectus_loan_count=69132, prospectus_pool_balance="1977161496.74",
    ),
    "toyota_2026-A": dict(
        deal="Toyota Auto Receivables 2026-A Owner Trust", cik="0002099539", filing_date="2026-01-06",
        accession="0001193125-26-003680", xml="taot26aex102_1215-2121lp.xml", size=229310854, scenario="lp",
        other_pool_files=[("sp", "0001193125-26-003592", "taot26aex102_1215-2101sp.xml", 156868513),
                          ("mp", "0001193125-26-003656", "taot26aex102_1215-2114mp.xml", 192964176)],
        h424="0000929638-26-000041 (2026-01-07)", b424="0000929638-26-000167 (2026-01-15)",
        b424_url="https://www.sec.gov/Archives/edgar/data/2099539/000092963826000167/taot2026-a_424b5.htm",
        prospectus_loan_count=65867, prospectus_pool_balance="1995353675.63",
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
    m = re.fullmatch(r"(\d{1,2})/(\d{4})", text.strip())
    if not m:
        return None
    return f"{m.group(2)}-{int(m.group(1)):02d}"


def parse(slug):
    d = DEALS[slug]
    xml_path = os.path.join(HERE, d["xml"])
    cik_plain = str(int(d["cik"]))
    source_url = (f"https://www.sec.gov/Archives/edgar/data/{cik_plain}/"
                  f"{d['accession'].replace('-', '')}/{d['xml']}")
    cols = {name: [] for name in SCHEMA.names}
    seen = set()
    rows_parsed = dup = 0
    months = []
    bad_months = Counter()
    codes = {k: Counter() for k in CODE_FIELDS}
    nonnumeric_scores = Counter()
    repeated_tags = Counter()
    periods = Counter()
    end_bal = beg_bal = Decimal(0)
    bal_rows = {"beginning": [], "end": []}

    for _, elem in etree.iterparse(xml_path, events=("end",), tag=NS + "assets"):
        rec, multi = {}, {}
        for c in elem:
            tag = c.tag[len(NS):]
            val = c.text.strip() if c.text is not None else None
            if tag in rec:
                repeated_tags[tag] += 1
                multi.setdefault(tag, [rec[tag]]).append(val)
            rec[tag] = val
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]
        rows_parsed += 1
        an = rec.get("assetNumber")
        if an in seen:
            dup += 1
            continue
        seen.add(an)

        # 'subvented' may repeat (spec maxOccurs unbounded); Toyota writes '1' and '2' for loans with both rate
        # subvention and a cash rebate. Keep every value, in file order, joined by ','.
        subv = ",".join(v for v in multi["subvented"] if v is not None) if "subvented" in multi \
            else rec.get("subvented")
        score_raw = rec.get("obligorCreditScore")
        score = to_float(score_raw)
        if math.isnan(score):
            nonnumeric_scores[score_raw] += 1
        apr = to_float(rec.get("originalInterestRatePercentage"))
        pti = to_float(rec.get("paymentToIncomePercentage"))
        om = month_from_mmyyyy(rec.get("originationDate"))
        if om is None:
            bad_months[rec.get("originationDate")] += 1
        else:
            months.append(om)
        periods[(rec.get("reportingPeriodBeginningDate"), rec.get("reportingPeriodEndingDate"))] += 1
        if rec.get("reportingPeriodActualEndBalanceAmount"):
            end_bal += Decimal(rec["reportingPeriodActualEndBalanceAmount"])
        if rec.get("reportingPeriodBeginningLoanBalanceAmount"):
            beg_bal += Decimal(rec["reportingPeriodBeginningLoanBalanceAmount"])
        bal_rows["end"].append(to_float(rec.get("reportingPeriodActualEndBalanceAmount")))
        bal_rows["beginning"].append(to_float(rec.get("reportingPeriodBeginningLoanBalanceAmount")))

        row = {
            "issuer": ISSUER, "deal": d["deal"], "deal_cik": d["cik"], "source_url": source_url,
            "filing_date": d["filing_date"], "asset_number": an, "origination_month": om,
            "original_loan_amount": to_float(rec.get("originalLoanAmount")),
            "original_term_months": to_int(rec.get("originalLoanTerm")),
            # round() removes float noise such as 5.490000000000001 from 0.0549 * 100
            "apr_pct": round(apr * 100, 6),
            "interest_rate_type_code": rec.get("originalInterestRateTypeCode"),
            "subvented": subv,
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
            "pti_pct": round(pti * 100, 6) if not math.isnan(pti) else math.nan,
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

    n = len(cols["asset_number"])
    scores = [s for s in cols["credit_score"] if not math.isnan(s)]
    by_type = {}
    for t, s in zip(cols["credit_score_type"], cols["credit_score"]):
        by_type.setdefault(str(t), []).append(s)
    score_by_type = {}
    for t, vals in by_type.items():
        num = sorted(v for v in vals if not math.isnan(v))
        score_by_type[t] = {"rows": len(vals), "numeric": len(num),
                            "min": num[0] if num else None, "median": statistics.median(num) if num else None,
                            "max": num[-1] if num else None}
    aprs = cols["apr_pct"]
    # Balance-weighted figures to compare with the 424B5 summary table (weighted average APR and FICO score,
    # share of new vehicles); computed on both balance columns because issuers differ in which holds the cutoff
    # balance.
    weighted = {}
    for basis, w in bal_rows.items():
        ok = [(b, a, sc, nu) for b, a, sc, nu in zip(w, aprs, cols["credit_score"], cols["new_used_code"])
              if not math.isnan(b)]
        tot = sum(b for b, *_ in ok)
        sw = [(b, sc) for b, _, sc, _ in ok if not math.isnan(sc)]
        weighted[basis] = {
            "apr_pct": round(sum(b * a for b, a, _, _ in ok) / tot, 4) if tot else None,
            "credit_score": round(sum(b * sc for b, sc in sw) / sum(b for b, _ in sw), 2) if sw else None,
            "new_used_code_1_share_pct": round(100 * sum(b for b, _, _, nu in ok if nu == "1") / tot, 2)
            if tot else None,
        }
    stats = {
        "slug": slug, "source_url": source_url, "xml_file": d["xml"], "bytes": os.path.getsize(xml_path),
        "bytes_listed_by_edgar": d["size"],
        "rows_parsed": rows_parsed, "rows_written": n, "duplicate_asset_numbers_dropped": dup,
        "prospectus_loan_count": d["prospectus_loan_count"],
        "rows_equal_prospectus_count": n == d["prospectus_loan_count"],
        "sum_end_balance": str(end_bal), "sum_beginning_balance": str(beg_bal),
        "prospectus_pool_balance": d["prospectus_pool_balance"],
        "balance_weighted": weighted,
        "reporting_periods": {f"{a} to {b}": c for (a, b), c in periods.items()},
        "origination_month_min": min(months), "origination_month_max": max(months),
        "origination_month_unparsed": dict(bad_months),
        "origination_by_year": dict(sorted(Counter(m[:4] for m in months).items())),
        "origination_after_2026_01": sum(1 for m in months if m > "2026-01"),
        "codes": {k: dict(v) for k, v in codes.items()},
        "repeated_tags": dict(repeated_tags),
        "nonnumeric_credit_score_values": dict(nonnumeric_scores),
        "numeric_credit_score_share": round(len(scores) / n, 6) if n else None,
        "credit_score_min": min(scores) if scores else None, "credit_score_max": max(scores) if scores else None,
        "credit_score_by_type": score_by_type,
        "credit_score_outside_300_850": sum(1 for s in scores if s < 300 or s > 850),
        "credit_score_outside_250_900": sum(1 for s in scores if s < 250 or s > 900),
        "apr_min": min(aprs), "apr_max": max(aprs), "apr_zero_rows": sum(1 for a in aprs if a == 0),
        "apr_median": statistics.median(aprs),
        "pti_missing": sum(1 for p in cols["pti_pct"] if math.isnan(p)),
        "parquet_bytes": os.path.getsize(out),
    }
    with open(os.path.join(HERE, f"stats_{slug}.json"), "w") as f:
        json.dump(stats, f, indent=1, sort_keys=True)
    print(json.dumps({k: v for k, v in stats.items() if k != "codes"}, indent=1))
    for k in ("credit_score_type", "subvented", "new_used_code", "interest_rate_type_code"):
        print(k, stats["codes"][k])


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
        others = "; ".join(f"'{x[2]}' ({x[0]}, accession {x[1]}, {x[3]:,} bytes)" for x in d["other_pool_files"])
        deals.append({
            "deal": d["deal"], "deal_cik": d["cik"], "filing_date": d["filing_date"], "accession": d["accession"],
            "source_url": s["source_url"],
            "why_this_is_the_first_pool_filing": (
                f"Filed {d['filing_date']} under the trust's CIK, accession {d['accession']}: the trust's first ABS-EE "
                "(its EDGAR submissions list has only an ABS-15G before it), filed before the preliminary prospectus "
                f"(424H {d['h424']}) and the final prospectus (424B5 {d['b424']}). Toyota filed one pool file per deal "
                f"size that day; this is the '{d['scenario']}' file. Not used: {others}. The 424B5 states "
                f"{d['prospectus_loan_count']:,} receivables with a total principal balance of "
                f"${Decimal(d['prospectus_pool_balance']):,}; this file has {s['rows_written']:,} rows; its "
                f"reportingPeriodActualEndBalanceAmount sums to ${Decimal(s['sum_end_balance']).quantize(CENT):,} and "
                f"reportingPeriodBeginningLoanBalanceAmount to "
                f"${Decimal(s['sum_beginning_balance']).quantize(CENT):,}."),
            "bytes": s["bytes"], "rows_parsed": s["rows_parsed"], "rows_written": s["rows_written"],
            "duplicate_asset_numbers_dropped": s["duplicate_asset_numbers_dropped"],
            "origination_month_min": s["origination_month_min"], "origination_month_max": s["origination_month_max"],
            "prospectus_loan_count_if_found": d["prospectus_loan_count"],
            "prospectus_url": d["b424_url"],
            "numeric_credit_score_share": s["numeric_credit_score_share"],
            "credit_score_by_type": s["credit_score_by_type"],
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


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "parse":
        for slug in sys.argv[2:]:
            parse(slug)
    elif cmd == "manifest":
        build_manifest()
    else:
        raise SystemExit(__doc__)
