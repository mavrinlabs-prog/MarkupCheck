"""Parse CarMax EX-102 (Schedule AL) XML pool files into the CONTRACT Parquet format.

usage:
  .venv/bin/python -I data/raw/carmax/parse_carmax.py parse <slug> [<slug> ...]
  .venv/bin/python -I data/raw/carmax/parse_carmax.py manifest

Each `parse` run writes data/parquet/carmax/<slug>.parquet and data/raw/carmax/stats_<slug>.json.
`manifest` builds data/parquet/carmax/manifest.json from the stats files that exist.
"""
import json
import math
import os
import sys
from collections import Counter
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq
from lxml import etree

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PARQUET_DIR = os.path.join(ROOT, "data", "parquet", "carmax")
NS = "{http://www.sec.gov/edgar/document/absee/autoloan/assetdata}"
USER_AGENT = "MarkupCheck student research project"

# Deal metadata. Each deal's preliminary prospectus (424H, filed the same day as the pool ABS-EE files) gives two
# possible sizes; 'smallpool' is the smaller-notes scenario and 'largepool' the larger one. In all three deals the
# final prospectus (424B5) uses the larger scenario, so the large-pool file is the one parsed.
DEALS = {
    "carmax_2024-1": dict(
        deal="CarMax Auto Owner Trust 2024-1", cik="0002003263", filing_date="2024-01-10",
        accession="0001259380-24-000005", xml="cart20241u.xml", size=260802679,
        small_xml="cart20241b.xml", small_accession="0001259380-24-000003",
        small_notes="$1,200,000,000", small_pool="1,212,123,695.19", small_count=63012,
        large_notes="$1,550,000,000", prospectus_pool_balance="1,565,657,067.52", prospectus_loan_count=81506,
        h424="0001193125-24-005935 (2024-01-10)", b424="0001193125-24-011298 (2024-01-19)",
    ),
    "carmax_2025-1": dict(
        deal="CarMax Auto Owner Trust 2025-1", cik="0002049715", filing_date="2025-01-08",
        accession="0001259380-25-000004", xml="cart20251u.xml", size=264008043,
        small_xml="cart20251b.xml", small_accession="0001259380-25-000002",
        small_notes="$1,150,000,000", small_pool="1,161,616,814.52", small_count=63221,
        large_notes="$1,500,000,000", prospectus_pool_balance="1,515,152,457.31", prospectus_loan_count=82495,
        h424="0001193125-25-003425 (2025-01-08)", b424="0001193125-25-007659 (2025-01-16)",
    ),
    "carmax_2026-1": dict(
        deal="CarMax Auto Owner Trust 2026-1", cik="0002094950", filing_date="2026-01-13",
        accession="0001259380-26-000007", xml="cart20261u.xml", size=266652248,
        small_xml="cart20261b.xml", small_accession="0001259380-26-000005",
        small_notes="$1,000,000,000", small_pool="1,005,025,872.07", small_count=63782,
        large_notes="$1,300,000,000", prospectus_pool_balance="1,306,533,362.66", prospectus_loan_count=83338,
        h424="0001193125-26-013037 (2026-01-14)", b424="0001193125-26-020885 (2026-01-23)",
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
    codes = {k: Counter() for k in CODE_FIELDS}
    nonnumeric_scores = Counter()

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
        om = month_from_mmyyyy(rec.get("originationDate"))
        months.append(om)

        row = {
            "issuer": "carmax", "deal": d["deal"], "deal_cik": d["cik"], "source_url": source_url,
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

    table = pa.Table.from_pydict(cols, schema=SCHEMA)
    os.makedirs(PARQUET_DIR, exist_ok=True)
    out = os.path.join(PARQUET_DIR, slug + ".parquet")
    pq.write_table(table, out, compression="zstd")
    scores = [s for s in cols["credit_score"] if not math.isnan(s)]
    stats = {
        "slug": slug, "source_url": source_url, "xml_file": d["xml"], "bytes": os.path.getsize(xml_path),
        "rows_parsed": rows_parsed, "rows_written": len(cols["asset_number"]),
        "duplicate_asset_numbers_dropped": dup,
        "origination_month_min": min(m for m in months if m), "origination_month_max": max(m for m in months if m),
        "codes": {k: dict(v) for k, v in codes.items()},
        "nonnumeric_credit_score_values": dict(nonnumeric_scores),
        "credit_score_min": min(scores) if scores else None, "credit_score_max": max(scores) if scores else None,
        "credit_score_outside_300_850": sum(1 for s in scores if s < 300 or s > 850),
        "parquet_bytes": os.path.getsize(out),
    }
    with open(os.path.join(HERE, f"stats_{slug}.json"), "w") as f:
        json.dump(stats, f, indent=1, sort_keys=True)
    print(json.dumps({k: v for k, v in stats.items() if k != "codes"}, indent=1))
    for k in ("subvented", "new_used_code", "credit_score_type"):
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
        deals.append({
            "deal": d["deal"], "deal_cik": d["cik"], "filing_date": d["filing_date"], "accession": d["accession"],
            "source_url": s["source_url"],
            "why_this_is_the_first_pool_filing": (
                f"Filed {d['filing_date']} by CarMax Auto Funding LLC (CIK 0001259380), accession {d['accession']}, the day "
                f"the preliminary prospectus (424H {d['h424']}) was filed and before the final prospectus (424B5 {d['b424']}); "
                "the trust's own first monthly ABS-EE came a month later. CarMax files two pool files for each deal that day, "
                "one per deal size offered in the 424H: "
                f"'{d['small_xml']}' (accession {d['small_accession']}, smallpool, if the notes total {d['small_notes']}: pool "
                f"${d['small_pool']}, {d['small_count']:,} receivables) and '{d['xml']}' (largepool, if the notes total "
                f"{d['large_notes']}). The final 424B5 sizes the deal at the larger scenario: pool ${d['prospectus_pool_balance']}, "
                f"{d['prospectus_loan_count']:,} receivables, which is the largepool file; its parsed row count equals that. "
                "The smallpool file is not used."),
            "bytes": s["bytes"], "rows_parsed": s["rows_parsed"], "rows_written": s["rows_written"],
            "duplicate_asset_numbers_dropped": s["duplicate_asset_numbers_dropped"],
            "origination_month_min": s["origination_month_min"], "origination_month_max": s["origination_month_max"],
            "prospectus_loan_count_if_found": d["prospectus_loan_count"],
        })
    notes = json.load(open(os.path.join(HERE, "manifest_notes.json")))
    manifest = {
        "issuer": "carmax", "user_agent": USER_AGENT, "deals": deals,
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
