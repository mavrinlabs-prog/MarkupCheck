"""Parse Honda EX-102 (Schedule AL) XML pool files into the CONTRACT Parquet format.

Adapted from data/raw/carmax/parse_carmax.py (same namespace, same CONTRACT columns).

usage:
  .venv/bin/python -I data/raw/honda/parse_honda.py parse <slug> [<slug> ...]
  .venv/bin/python -I data/raw/honda/parse_honda.py manifest

Each `parse` run writes data/parquet/honda/<slug>.parquet and data/raw/honda/stats_<slug>.json.
`manifest` builds data/parquet/honda/manifest.json from the stats files that exist.
"""
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq
from lxml import etree

ISSUER = "honda"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PARQUET_DIR = os.path.join(ROOT, "data", "parquet", ISSUER)
NS = "{http://www.sec.gov/edgar/document/absee/autoloan/assetdata}"
USER_AGENT = "MarkupCheck student research project"

# Deal metadata. American Honda Receivables LLC files three pool ABS-EE filings for each deal on the day of the
# preliminary prospectus (424H), one per deal size: 'sp' (small pool), 'mp' (medium pool) and 'lp' (large pool). The
# 424H gives each size's note amount, initial pool balance and receivable count, and each ABS-EE cover page states its
# pool balance. The final prospectus (424B5) gives one pool; in all three deals it is the 'lp' size, the file parsed.
# `others` rows: (size, accession, xml, bytes, notes total, 424H pool balance, 424H receivable count).
DEALS = {
    "honda_2024-1": dict(
        deal="Honda Auto Receivables 2024-1 Owner Trust", cik="0002008953", filing_date="2024-02-07",
        accession="0000950131-24-000414", xml="harot241ex102_0206-1655lp.xml", size=329951704,
        notes_total="$2,105,264,000",
        others=[("sp", "0000950131-24-000410", "harot241ex102_0206-1545sp.xml", 231130268,
                 "$1,473,685,000", "$1,511,471,985.64", 64735),
                ("mp", "0000950131-24-000413", "harot241ex102_0206-1630mp.xml", 288688372,
                 "$1,842,106,000", "$1,889,339,731.68", 80856)],
        cutoff="opening of business 2024-01-01", prospectus_pool_balance="2,159,245,264.72",
        prospectus_loan_count=92413,
        h424="0001104659-24-011502 (2024-02-07)", b424="0001104659-24-024400 (2024-02-15)",
    ),
    "honda_2025-1": dict(
        deal="Honda Auto Receivables 2025-1 Owner Trust", cik="0002052479", filing_date="2025-01-29",
        accession="0000950131-25-000398", xml="harot251ex102_0128-1550lp.xml", size=371612156,
        notes_total="$2,368,422,000",
        others=[("sp", "0000950131-25-000394", "harot251ex102_0128-1653sp.xml", 264268540,
                 "$1,684,211,000", "$1,727,396,411.74", 74011),
                ("mp", "0000950131-25-000396", "harot251ex102_0128-1644mp.xml", 330326674,
                 "$2,105,264,000", "$2,159,245,265.40", 92511)],
        cutoff="opening of business 2025-01-01", prospectus_pool_balance="2,429,150,798.03",
        prospectus_loan_count=104073,
        h424="0001104659-25-007138 (2025-01-29)", b424="0001104659-25-010095 (2025-02-06)",
    ),
    "honda_2026-1": dict(
        deal="Honda Auto Receivables 2026-1 Owner Trust", cik="0002100818", filing_date="2026-02-03",
        accession="0001193125-26-034352", xml="harot261ex102_0202-1729lp.xml", size=362209716,
        notes_total="$2,421,053,000",
        others=[("sp", "0001193125-26-034142", "harot261ex102_0202-1507sp.xml", 252212946,
                 "$1,684,211,000", "$1,727,396,412.29", 70633),
                ("mp", "0001193125-26-034171", "harot261ex102_0202-1707mp.xml", 315025752,
                 "$2,105,264,000", "$2,159,245,264.63", 88224)],
        cutoff="opening of business 2026-01-01", prospectus_pool_balance="2,483,131,904.21",
        prospectus_loan_count=101438,
        h424="0001104659-26-009632 (2026-02-03)", b424="0001104659-26-014201 (2026-02-12)",
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


def source_url_of(cik, accession, xml):
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{xml}"


def parse(slug):
    d = DEALS[slug]
    xml_path = os.path.join(HERE, d["xml"])
    source_url = source_url_of(d["cik"], d["accession"], d["xml"])
    cols = {name: [] for name in SCHEMA.names}
    seen = set()
    rows_parsed = dup = 0
    months = []
    codes = {k: Counter() for k in CODE_FIELDS}
    nonnumeric_scores = Counter()
    repeated = Counter()
    makes = Counter()
    end_balance = 0.0

    for _, elem in etree.iterparse(xml_path, events=("end",), tag=NS + "assets", huge_tree=True):
        # `subvented` may repeat inside one asset (XSD maxOccurs=unbounded); every value is kept, comma-joined in
        # document order (e.g. "1,2"), the convention data/raw/santander uses.
        rec = {}
        for c in elem:
            name = c.tag[len(NS):]
            text = c.text.strip() if c.text is not None else None
            if name in rec:
                repeated[name] += 1
                rec[name] = f"{rec[name]},{text}"
            else:
                rec[name] = text
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
        om = month_from_mmyyyy(rec.get("originationDate"))
        months.append(om)
        eb = to_float(rec.get("reportingPeriodActualEndBalanceAmount"))
        if not math.isnan(eb):
            end_balance += eb

        row = {
            "issuer": ISSUER, "deal": d["deal"], "deal_cik": d["cik"], "source_url": source_url,
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
            "pti_pct": round(pti * 100, 6) if not math.isnan(pti) else math.nan,
            "state": rec.get("obligorGeographicLocation"),
        }
        for k, v in row.items():
            cols[k].append(v)
        for k in CODE_FIELDS:
            codes[k][row[k]] += 1
        makes[row["vehicle_make"]] += 1

    table = pa.Table.from_pydict(cols, schema=SCHEMA)
    os.makedirs(PARQUET_DIR, exist_ok=True)
    out = os.path.join(PARQUET_DIR, slug + ".parquet")
    pq.write_table(table, out, compression="zstd")
    scores = [s for s in cols["credit_score"] if not math.isnan(s)]
    by_type = defaultdict(list)
    for t, s in zip(cols["credit_score_type"], cols["credit_score"]):
        if not math.isnan(s):
            by_type[t].append(s)
    stats = {
        "slug": slug, "source_url": source_url, "xml_file": d["xml"], "bytes": os.path.getsize(xml_path),
        "rows_parsed": rows_parsed, "rows_written": len(cols["asset_number"]),
        "duplicate_asset_numbers_dropped": dup,
        "origination_month_min": min(m for m in months if m), "origination_month_max": max(m for m in months if m),
        "origination_month_missing": sum(1 for m in months if not m),
        "codes": {k: dict(v) for k, v in codes.items()},
        "repeated_elements": dict(repeated),
        "vehicle_make_counts": dict(makes.most_common()),
        "nonnumeric_credit_score_values": dict(nonnumeric_scores),
        "numeric_credit_score_share": len(scores) / len(cols["credit_score"]),
        "credit_score_min": min(scores) if scores else None, "credit_score_max": max(scores) if scores else None,
        "credit_score_by_type": {t: {"n": len(v), "min": min(v), "median": statistics.median(v), "max": max(v)}
                                 for t, v in by_type.items()},
        "credit_score_outside_300_850": sum(1 for s in scores if s < 300 or s > 850),
        "sum_reporting_period_actual_end_balance": round(end_balance, 2),
        "parquet_bytes": os.path.getsize(out),
    }
    with open(os.path.join(HERE, f"stats_{slug}.json"), "w") as f:
        json.dump(stats, f, indent=1, sort_keys=True)
    print(json.dumps({k: v for k, v in stats.items() if k not in ("codes", "vehicle_make_counts")}, indent=1))
    for k in ("subvented", "new_used_code", "credit_score_type", "interest_rate_type_code"):
        print(k, stats["codes"][k])
    print("vehicle_make", stats["vehicle_make_counts"])


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
        others = "; ".join(f"{kind} '{x}' (accession {acc}, {size:,} bytes; 424H: notes {notes}, pool {pool}, "
                           f"{count:,} receivables)"
                           for kind, acc, x, size, notes, pool, count in d["others"])
        deals.append({
            "deal": d["deal"], "deal_cik": d["cik"], "filing_date": d["filing_date"], "accession": d["accession"],
            "source_url": s["source_url"],
            "why_this_is_the_first_pool_filing": (
                f"Filed {d['filing_date']} by American Honda Receivables LLC (depositor, CIK 0000890975) for the trust, "
                f"accession {d['accession']}, the same day as the preliminary prospectus (424H {d['h424']}) and before "
                f"the final prospectus (424B5 {d['b424']}); the trust's submissions list on data.sec.gov shows only an "
                "ABS-15G before these filings. The pool is as of the cutoff date "
                f"({d['cutoff']}). Honda files three pool ABS-EE filings that day, one per deal size offered in the "
                f"424H: {others}; and lp '{d['xml']}' (this filing, {d['size']:,} bytes; 424H: notes "
                f"{d['notes_total']}, pool ${d['prospectus_pool_balance']}, {d['prospectus_loan_count']:,} "
                f"receivables). The 424B5 states the initial pool balance as ${d['prospectus_pool_balance']} and "
                f"{d['prospectus_loan_count']:,} receivables, which is the lp file; see rows_parsed and "
                "prospectus_loan_count_if_found. The sp and mp files were not downloaded."),
            "bytes": s["bytes"], "rows_parsed": s["rows_parsed"], "rows_written": s["rows_written"],
            "duplicate_asset_numbers_dropped": s["duplicate_asset_numbers_dropped"],
            "origination_month_min": s["origination_month_min"], "origination_month_max": s["origination_month_max"],
            "prospectus_loan_count_if_found": d["prospectus_loan_count"],
            "sum_reporting_period_actual_end_balance": s["sum_reporting_period_actual_end_balance"],
            "vehicle_make_counts": s["vehicle_make_counts"],
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
