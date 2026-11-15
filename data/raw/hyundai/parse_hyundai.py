"""Parse Hyundai EX-102 (Schedule AL) XML pool files into the CONTRACT Parquet format.

Adapted from data/raw/carmax/parse_carmax.py (same namespace, same CONTRACT columns).

usage:
  .venv/bin/python -I data/raw/hyundai/parse_hyundai.py parse <slug> [<slug> ...]
  .venv/bin/python -I data/raw/hyundai/parse_hyundai.py manifest

Each `parse` run writes data/parquet/hyundai/<slug>.parquet and data/raw/hyundai/stats_<slug>.json.
`manifest` builds data/parquet/hyundai/manifest.json from the stats files that exist.
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

ISSUER = "hyundai"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PARQUET_DIR = os.path.join(ROOT, "data", "parquet", ISSUER)
NS = "{http://www.sec.gov/edgar/document/absee/autoloan/assetdata}"
USER_AGENT = "MarkupCheck student research project"

# Deal metadata. Hyundai ABS Funding, LLC files one pool ABS-EE filing per deal size offered in the preliminary
# prospectus (424H), before the 424H: the cover pages say "Schedule AL for Base Transaction", "Upsize Transaction" or
# "Maximum Transaction". The 424H gives each size's note amount, pool balance and receivable count; the final
# prospectus (424B5) gives one pool, and the parsed file is the scenario whose count and balance equal it.
# `others` rows: (scenario, accession, xml, bytes, notes total, 424H pool balance, 424H receivable count).
DEALS = {
    "hyundai_2024-A": dict(
        deal="Hyundai Auto Receivables Trust 2024-A", cik="0002010834", filing_date="2024-03-05",
        accession="0001104659-24-031026", xml="hca-autoloanex102_021420241u.xml", size=237446705,
        scenario="Upsize Transaction", notes_total="$1,647,010,000",
        others=[("Base Transaction", "0001104659-24-031005", "hca-autoloanex102_021520241b.xml", 179436615,
                 "$1,245,070,000", "$1,370,393,333.99", 51568)],
        cutoff="close of business 2024-02-05", prospectus_pool_balance="1,812,800,084.97",
        prospectus_loan_count=68239,
        h424="0001104659-24-031300 (2024-03-06)", b424="0001104659-24-033905 (2024-03-13)",
    ),
    "hyundai_2025-A": dict(
        deal="Hyundai Auto Receivables Trust 2025-A", cik="0002056104", filing_date="2025-02-25",
        accession="0001104659-25-016986", xml="hca-autoloanex102_021020251m.xml", size=295859906,
        scenario="Maximum Transaction", notes_total="$2,005,250,000",
        others=[("Base Transaction", "0001104659-25-016964", "hca-autoloanex102_021020251b.xml", 221575459,
                 "$1,501,510,000", "$1,638,428,161.37", 63727),
                ("Upsize Transaction", "0001104659-25-016985", "hca-autoloanex102_021020251u.xml", 258490417,
                 "$1,751,760,000", "$1,911,492,868.08", 74345)],
        cutoff="close of business 2025-02-03", prospectus_pool_balance="2,188,286,865.59",
        prospectus_loan_count=85093,
        h424="0001104659-25-017888 (2025-02-27)", b424="0001104659-25-021310 (2025-03-06)",
    ),
    "hyundai_2026-A": dict(
        deal="Hyundai Auto Receivables Trust 2026-A", cik="0002104134", filing_date="2026-02-02",
        accession="0001104659-26-009139", xml="hca-autoloanex102_011620261.xml", size=275772124,
        scenario="Maximum Transaction", notes_total="$2,199,700,000",
        # all three 2026-A scenario files share one file name; only the accession differs
        others=[("Base Transaction", "0001104659-26-009127", "hca-autoloanex102_011620261.xml", 199848847,
                 "$1,595,110,000", "$1,734,904,585.03", 57396),
                ("Upsize Transaction", "0001104659-26-009138", "hca-autoloanex102_011620261.xml", 237414369,
                 "$1,894,110,000", "$2,060,199,191.42", 68185)],
        cutoff="close of business 2026-01-06", prospectus_pool_balance="2,392,354,765.71",
        prospectus_loan_count=79201,
        h424="0001104659-26-010086 (2026-02-04)", b424="0001104659-26-014212 (2026-02-12)",
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
                f"Filed {d['filing_date']} by Hyundai ABS Funding, LLC (depositor, CIK 0001260125) for the trust, "
                f"accession {d['accession']}, before the preliminary prospectus (424H {d['h424']}) and the final "
                f"prospectus (424B5 {d['b424']}); the trust's submissions list on data.sec.gov shows only an ABS-15G "
                "before these filings. The pool is as of the cut-off date "
                f"({d['cutoff']}). Hyundai files one pool ABS-EE per deal size offered in the 424H: {others}; and "
                f"{d['scenario']} '{d['xml']}' (this filing, {d['size']:,} bytes; 424H: notes {d['notes_total']}, "
                f"pool ${d['prospectus_pool_balance']}, {d['prospectus_loan_count']:,} receivables). The 424B5 states "
                f"the pool as ${d['prospectus_pool_balance']} and {d['prospectus_loan_count']:,} receivables, which is "
                f"the {d['scenario']} file; see rows_parsed and prospectus_loan_count_if_found. The other scenario "
                "files were not downloaded."),
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
