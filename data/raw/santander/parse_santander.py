"""Parse one SDART EX-102 (auto-loan asset data) XML into a CONTRACT-format Parquet.

Usage: parse_santander.py <deal_slug> [out_dir]
Reads data/raw/santander/deals.json for the deal's metadata and the XML file name, writes
data/parquet/santander/<deal_slug>.parquet and data/raw/santander/stats_<deal_slug>.json.
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from lxml import etree

NS = "http://www.sec.gov/edgar/document/absee/autoloan/assetdata"
HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parent.parent / "parquet" / "santander"

# Santander files obligorCreditScore 0 (no score; 13-17% of loans) and a few 851-900 values (a different score
# scale, mean APR 3-10%). Both fall outside the 300-850 range the brief, validate.py and the app use, so they
# were once set to NaN here. That dropped only Santander's 851-900 FICO Auto scores (CarMax and Ally keep theirs), so
# scores are now kept as written and src/mc.py clean() applies one 250-900 rule to every lender.
NULL_OUT_OF_RANGE_SCORES = False

SCHEMA = pa.schema([
    ("issuer", pa.string()), ("deal", pa.string()), ("deal_cik", pa.string()),
    ("source_url", pa.string()), ("filing_date", pa.string()),
    ("asset_number", pa.string()), ("origination_month", pa.string()),
    ("original_loan_amount", pa.float64()), ("original_term_months", pa.int64()),
    ("apr_pct", pa.float64()), ("interest_rate_type_code", pa.string()),
    ("subvented", pa.string()), ("vehicle_make", pa.string()), ("vehicle_model", pa.string()),
    ("new_used_code", pa.string()), ("vehicle_model_year", pa.int64()),
    ("vehicle_type_code", pa.string()), ("vehicle_value", pa.float64()),
    ("vehicle_value_source_code", pa.string()), ("credit_score_type", pa.string()),
    ("credit_score", pa.float64()), ("income_verification_code", pa.string()),
    ("employment_verification_code", pa.string()), ("co_obligor", pa.bool_()),
    ("pti_pct", pa.float64()), ("state", pa.string()),
])


def num(text):
    """Float from element text, None if missing or non-numeric."""
    if text is None:
        return None
    try:
        v = float(text.strip())
    except ValueError:
        return None
    return None if math.isnan(v) else v


def to_int(text):
    v = num(text)
    return None if v is None else int(round(v))


def month_of(text):
    """originationDate is MM/YYYY; returns YYYY-MM or None."""
    if not text:
        return None
    parts = text.strip().split("/")
    if len(parts) == 2 and len(parts[1]) == 4 and parts[0].isdigit():
        return f"{parts[1]}-{int(parts[0]):02d}"
    return None


def to_bool(text):
    if text is None:
        return None
    t = text.strip().lower()
    if t in ("true", "1"):
        return True
    if t in ("false", "0"):
        return False
    return None


def scaled(text, factor):
    v = num(text)
    return None if v is None else round(v * factor, 6)


def parse(xml_path, meta):
    cols = {name: [] for name in SCHEMA.names}
    seen = set()
    rows_parsed = dups = 0
    codes = {k: Counter() for k in ("subvented", "new_used_code", "credit_score_type",
                                    "interest_rate_type_code", "vehicle_type_code",
                                    "vehicle_value_source_code", "income_verification_code",
                                    "employment_verification_code")}
    odd_dates = 0
    score_counts = Counter()
    tag = f"{{{NS}}}assets"
    for _, elem in etree.iterparse(str(xml_path), events=("end",), tag=tag, huge_tree=True):
        # `subvented` (and a few perf-only fields) may repeat inside one asset (XSD maxOccurs=unbounded);
        # keep every value, comma-joined in document order, e.g. "1,98".
        f = {}
        for c in elem:
            text = c.text.strip() if c.text and c.text.strip() else None
            if text is None:
                continue
            name = etree.QName(c).localname
            f[name] = f[name] + "," + text if name in f else text
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]
        rows_parsed += 1
        asset = f.get("assetNumber")
        if asset in seen:
            dups += 1
            continue
        seen.add(asset)
        om = month_of(f.get("originationDate"))
        if om is None:
            odd_dates += 1
        score = num(f.get("obligorCreditScore"))
        if score is None:
            score_counts["missing_or_non_numeric"] += 1
        elif not 300 <= score <= 850:
            score_counts["zero" if score == 0 else "above_850" if score > 850 else "between_1_and_299"] += 1
            if NULL_OUT_OF_RANGE_SCORES:
                score = None
        row = {
            "issuer": "santander", "deal": meta["deal"], "deal_cik": meta["deal_cik"],
            "source_url": meta["source_url"], "filing_date": meta["filing_date"],
            "asset_number": asset, "origination_month": om,
            "original_loan_amount": num(f.get("originalLoanAmount")),
            "original_term_months": to_int(f.get("originalLoanTerm")),
            "apr_pct": scaled(f.get("originalInterestRatePercentage"), 100),
            "interest_rate_type_code": f.get("originalInterestRateTypeCode"),
            "subvented": f.get("subvented"),
            "vehicle_make": f.get("vehicleManufacturerName"),
            "vehicle_model": f.get("vehicleModelName"),
            "new_used_code": f.get("vehicleNewUsedCode"),
            "vehicle_model_year": to_int(f.get("vehicleModelYear")),
            "vehicle_type_code": f.get("vehicleTypeCode"),
            "vehicle_value": num(f.get("vehicleValueAmount")),
            "vehicle_value_source_code": f.get("vehicleValueSourceCode"),
            "credit_score_type": f.get("obligorCreditScoreType"),
            "credit_score": score,
            "income_verification_code": f.get("obligorIncomeVerificationLevelCode"),
            "employment_verification_code": f.get("obligorEmploymentVerificationCode"),
            "co_obligor": to_bool(f.get("coObligorIndicator")),
            "pti_pct": scaled(f.get("paymentToIncomePercentage"), 100),
            "state": f.get("obligorGeographicLocation"),
        }
        for name, value in row.items():
            cols[name].append(value)
        for k in codes:
            codes[k][row[k] if row[k] is not None else "(missing)"] += 1
    return cols, rows_parsed, dups, odd_dates, codes, score_counts


def main(slug, out_dir=None):
    deals = json.loads((HERE / "deals.json").read_text())
    meta = deals[slug]
    out_dir = Path(out_dir) if out_dir else OUT_DIR
    xml_path = HERE / meta["xml_file"]
    cols, rows_parsed, dups, odd_dates, codes, score_counts = parse(xml_path, meta)
    table = pa.table({n: pa.array(cols[n], type=SCHEMA.field(n).type) for n in SCHEMA.names},
                     schema=SCHEMA)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{slug}.parquet"
    pq.write_table(table, out, compression="zstd")
    months = sorted(m for m in set(cols["origination_month"]) if m)
    stats = {
        "slug": slug, "xml_bytes": xml_path.stat().st_size, "rows_parsed": rows_parsed,
        "rows_written": table.num_rows, "duplicate_asset_numbers_dropped": dups,
        "rows_with_unparseable_origination_date": odd_dates,
        "credit_score_out_of_range_300_850": dict(score_counts),
        "credit_scores_nulled": NULL_OUT_OF_RANGE_SCORES,
        "origination_month_min": months[0] if months else None,
        "origination_month_max": months[-1] if months else None,
        "code_values_seen": {k: dict(v) for k, v in codes.items()},
    }
    (HERE / f"stats_{slug}.json").write_text(json.dumps(stats, indent=1))  # one stats file per slug
    print(json.dumps({k: v for k, v in stats.items() if k != "code_values_seen"}, indent=1))
    for k, v in codes.items():
        print(k, dict(v.most_common(12)))
    print("wrote", out, out.stat().st_size, "bytes")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
