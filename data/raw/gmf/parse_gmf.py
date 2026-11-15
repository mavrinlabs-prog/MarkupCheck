"""Parse GM Financial Consumer Automobile Receivables Trust EX-102 (Schedule AL) pool files into the CONTRACT Parquet format.

Adapted from data/raw/carmax/parse_carmax.py (same namespace, same CONTRACT columns, issuer = "gmf").

usage (the sec.gov User-Agent comes from the SEC_UA environment variable, copied from CLAUDE.md, so the
contact address never lands in a project file):
  SEC_UA='...' .venv/bin/python -I data/raw/gmf/parse_gmf.py fetch <sec.gov url> <dest path>
  .venv/bin/python -I data/raw/gmf/parse_gmf.py parse <slug> [<slug> ...]
  .venv/bin/python -I data/raw/gmf/parse_gmf.py manifest
  .venv/bin/python -I data/raw/gmf/parse_gmf.py check

`fetch` sends one request, appends it to sec_requests.log (git-ignored) and then sleeps 1 s, so sequential calls
stay at or under 1 request per second. No retries.
Each `parse` run writes data/parquet/gmf/gmf_<deal>.parquet and data/raw/gmf/stats_<slug>.json.
`manifest` builds data/parquet/gmf/manifest.json from the stats files; `check` re-reads the Parquet files.
"""
import json
import math
import os
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq
from lxml import etree

ISSUER = "gmf"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PARQUET_DIR = os.path.join(ROOT, "data", "parquet", ISSUER)
NS = "{http://www.sec.gov/edgar/document/absee/autoloan/assetdata}"
USER_AGENT = "MarkupCheck student research project"
REQUEST_LOG = os.path.join(HERE, "sec_requests.log")

# Deal metadata, from the depositor's (AFS SenSub Corp., CIK 0001347185, which also files AmeriCredit deals) submissions
# JSON, each filing's index.json (served under the GM Financial Consumer Automobile Receivables Trust's own CIK) and the
# final prospectus (424B5). For each deal the depositor filed two pool ABS-EEs the same day, one per deal size:
# 'exh102<n><cutoff>[_]sp.xml' (small pool) and 'exh102<n><cutoff>[_]lp.xml' or '_mp.xml' (larger pool); the larger
# file's record count equals the 424B5 contract count in all three deals.
_WHY = ("Initial asset-level data: filed {fd} by AFS SenSub Corp. (CIK 0001347185), accession {acc}, with the trust as "
        "co-registrant (EDGAR serves the filing under the trust's CIK {cik}), before the preliminary prospectus "
        "(424H {h424}) and the final prospectus (424B5 {b424}), which says the initial asset-level data was filed on "
        "Form ABS-EE on or prior to the date of the prospectus. The cover document is '{cover}' and the EX-102 is "
        "'{xml}'. The same day the depositor filed a second pool ABS-EE for the smaller deal size, accession {sp_acc} "
        "with '{sp_xml}' ({sp_size:,} bytes, not downloaded). The 424B5 gives {count:,} contracts ({new:,} new, "
        "{used:,} used) and an aggregate principal balance of ${balance} at the cutoff date {cutoff}; the parsed file "
        "has the same number of records, so it is the pool the deal was priced on.")
DEALS = {
    "gmf_2024-1": dict(
        deal="GM Financial Consumer Automobile Receivables Trust 2024-1", cik="0002003007", filing_date="2024-01-02",
        accession="0001347185-24-000003", xml="exh1024600112023lp.xml", size=195809253,
        cover="absee_4600x112023xlp.htm", prospectus_loan_count=48285, prospectus_pool_balance="1,657,333,024.92",
        new=36191, used=12094, cutoff="2023-11-30",
        h424="0001193125-24-002483, 2024-01-04", b424="0001193125-24-006679, 2024-01-11",
        sp_acc="0001347185-24-000005", sp_xml="exh1024600112023sp.xml", sp_size=169670851,
    ),
    "gmf_2025-1": dict(
        deal="GM Financial Consumer Automobile Receivables Trust 2025-1", cik="0002047316", filing_date="2025-01-03",
        accession="0001347185-25-000003", xml="exh1024740112024_lp.xml", size=205716878,
        cover="absee_4740x112024xlp.htm", prospectus_loan_count=50723, prospectus_pool_balance="1,644,919,577.13",
        new=36642, used=14081, cutoff="2024-12-03",
        h424="0001193125-25-002125, 2025-01-06", b424="0001193125-25-005364, 2025-01-13",
        sp_acc="0001347185-25-000005", sp_xml="exh1024740112024_sp.xml", sp_size=170878836,
    ),
    "gmf_2026-1": dict(
        deal="GM Financial Consumer Automobile Receivables Trust 2026-1", cik="0002099048", filing_date="2026-01-02",
        accession="0001347185-26-000003", xml="exh1024860112025_mp.xml", size=139190118,
        cover="absee_4860x112025xmp.htm", prospectus_loan_count=33198, prospectus_pool_balance="1,317,621,312.63",
        new=24944, used=8254, cutoff="2025-12-08",
        h424="0001193125-26-002340, 2026-01-05", b424="0001193125-26-010639, 2026-01-12",
        sp_acc="0001347185-26-000005", sp_xml="exh1024860112025_sp.xml", sp_size=111313281,
    ),
}
for _d in DEALS.values():
    _d["why_first"] = _WHY.format(fd=_d["filing_date"], acc=_d["accession"], cik=_d["cik"], h424=_d["h424"],
                                  b424=_d["b424"], cover=_d["cover"], xml=_d["xml"], sp_acc=_d["sp_acc"],
                                  sp_xml=_d["sp_xml"], sp_size=_d["sp_size"], count=_d["prospectus_loan_count"],
                                  new=_d["new"], used=_d["used"], balance=_d["prospectus_pool_balance"],
                                  cutoff=_d["cutoff"])

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
# The XSD allows <subvented> to repeat (maxOccurs="unbounded"); every value is kept, in file order, joined by this.
SUBVENTED_SEP = "|"


def fetch(url, dest):
    import requests
    if "sec.gov" not in url.split("/")[2]:
        raise SystemExit("fetch is for sec.gov URLs only")
    ua = os.environ["SEC_UA"]
    t0 = time.time()
    with requests.get(url, headers={"User-Agent": ua}, stream=True, timeout=300) as r:
        status = r.status_code
        size = 0
        if status == 200:
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
                    size += len(chunk)
            os.replace(tmp, dest)
    with open(REQUEST_LOG, "a") as f:
        f.write(f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\t{status}\t{size}\t{url}\n")
    n = sum(1 for _ in open(REQUEST_LOG))
    print(f"status {status}, {size:,} bytes, {time.time() - t0:.1f} s -> {dest}; requests logged here: {n}")
    time.sleep(1)
    if status != 200:
        raise SystemExit(f"HTTP {status} for {url}")


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
    try:
        mm, yyyy = text.strip().split("/")
        if not 1 <= int(mm) <= 12 or len(yyyy) != 4:
            return None
        return f"{yyyy}-{int(mm):02d}"
    except ValueError:
        return None


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
    subvented_each = Counter()
    nonnumeric_scores = Counter()
    bad_orig = Counter()
    end_balance = begin_balance = 0.0

    for _, elem in etree.iterparse(xml_path, events=("end",), tag=NS + "assets", huge_tree=True):
        rec, subv = {}, []
        for c in elem:
            if not isinstance(c.tag, str):
                continue
            name = c.tag[len(NS):]
            val = c.text.strip() if c.text is not None else None
            if name == "subvented":
                subv.append(val)
            else:
                rec[name] = val
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]
        rows_parsed += 1
        eb = to_float(rec.get("reportingPeriodActualEndBalanceAmount"))
        bb = to_float(rec.get("reportingPeriodBeginningLoanBalanceAmount"))
        end_balance += 0.0 if math.isnan(eb) else eb
        begin_balance += 0.0 if math.isnan(bb) else bb
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
        if om is None:
            bad_orig[rec.get("originationDate")] += 1
        months.append(om)
        for v in subv:
            subvented_each[v] += 1

        row = {
            "issuer": ISSUER, "deal": d["deal"], "deal_cik": d["cik"], "source_url": source_url,
            "filing_date": d["filing_date"], "asset_number": an, "origination_month": om,
            "original_loan_amount": to_float(rec.get("originalLoanAmount")),
            "original_term_months": to_int(rec.get("originalLoanTerm")),
            # round() removes float noise such as 5.490000000000001 from 0.0549 * 100
            "apr_pct": round(apr * 100, 6) if not math.isnan(apr) else math.nan,
            "interest_rate_type_code": rec.get("originalInterestRateTypeCode"),
            "subvented": SUBVENTED_SEP.join("" if v is None else v for v in subv) if subv else None,
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
        "unparsed_origination_dates": {str(k): v for k, v in bad_orig.items()},
        "codes": {k: {str(kk): vv for kk, vv in v.items()} for k, v in codes.items()},
        "subvented_each_code": {str(k): v for k, v in subvented_each.items()},
        "nonnumeric_credit_score_values": {str(k): v for k, v in nonnumeric_scores.items()},
        "credit_score_min": min(scores) if scores else None, "credit_score_max": max(scores) if scores else None,
        "credit_score_median": statistics.median(scores) if scores else None,
        "credit_score_outside_300_850": sum(1 for s in scores if s < 300 or s > 850),
        "sum_reportingPeriodActualEndBalanceAmount": round(end_balance, 2),
        "sum_reportingPeriodBeginningLoanBalanceAmount": round(begin_balance, 2),
        "parquet_bytes": os.path.getsize(out),
    }
    with open(os.path.join(HERE, f"stats_{slug}.json"), "w") as f:
        json.dump(stats, f, indent=1, sort_keys=True)
    print(json.dumps({k: v for k, v in stats.items() if k != "codes"}, indent=1))
    for k in ("subvented", "new_used_code", "credit_score_type", "interest_rate_type_code"):
        print(k, stats["codes"][k])


def check():
    """Re-read each Parquet and print the brief's step-4 checks."""
    import pandas as pd
    for slug, d in DEALS.items():
        path = os.path.join(PARQUET_DIR, slug + ".parquet")
        if not os.path.exists(path):
            print(f"== {slug}: no Parquet yet")
            continue
        df = pd.read_parquet(path)
        exp = d.get("prospectus_loan_count")
        print(f"== {slug} ({d['deal']}): {len(df):,} rows; final-prospectus loan count {exp if exp is None else f'{exp:,}'}"
              f" -> {'MATCH' if exp == len(df) else 'DIFFERENT'}")
        print(f"   columns match CONTRACT: {list(df.columns) == SCHEMA.names}; duplicate asset_number: "
              f"{int(df['asset_number'].duplicated().sum())}")
        om = df["origination_month"].dropna()
        print(f"   origination_month {om.min()} .. {om.max()}; missing {int(df['origination_month'].isna().sum())};"
              f" originated after 2026-01: {int((om > '2026-01').sum())}")
        num = df["credit_score"].notna()
        print(f"   numeric credit_score: {int(num.sum()):,} of {len(df):,} = {num.mean() * 100:.2f}%")
        for t, g in df.groupby(df["credit_score_type"].fillna("<missing>")):
            s = g["credit_score"].dropna()
            if len(s):
                print(f"   credit_score_type {t!r}: n={len(g):,}, numeric {len(s):,}, min {s.min():g}, "
                      f"median {s.median():g}, max {s.max():g}, below 300: {int((s < 300).sum())}, "
                      f"above 850: {int((s > 850).sum())}")
            else:
                print(f"   credit_score_type {t!r}: n={len(g):,}, no numeric score")
        print(f"   apr_pct min {df['apr_pct'].min():g}, median {df['apr_pct'].median():g}, max {df['apr_pct'].max():g};"
              f" exactly 0: {int((df['apr_pct'] == 0).sum())}")


def build_manifest():
    deals, merged = [], {k: Counter() for k in CODE_FIELDS}
    subv_each = Counter()
    missing = []
    for slug, d in DEALS.items():
        sp = os.path.join(HERE, f"stats_{slug}.json")
        if not os.path.exists(sp):
            missing.append(slug)
            continue
        s = json.load(open(sp))
        for k in CODE_FIELDS:
            merged[k].update(s["codes"][k])
        subv_each.update(s["subvented_each_code"])
        deals.append({
            "deal": d["deal"], "deal_cik": d["cik"], "filing_date": d["filing_date"], "accession": d["accession"],
            "source_url": s["source_url"],
            "why_this_is_the_first_pool_filing": d["why_first"],
            "bytes": s["bytes"], "rows_parsed": s["rows_parsed"], "rows_written": s["rows_written"],
            "duplicate_asset_numbers_dropped": s["duplicate_asset_numbers_dropped"],
            "origination_month_min": s["origination_month_min"], "origination_month_max": s["origination_month_max"],
            "prospectus_loan_count_if_found": d.get("prospectus_loan_count"),
        })
    notes = json.load(open(os.path.join(HERE, "manifest_notes.json")))
    manifest = {
        "issuer": ISSUER, "user_agent": USER_AGENT, "deals": deals,
        "code_values_seen": {k: dict(v) for k, v in merged.items()},
        "subvented_each_code_seen": dict(subv_each),
        "spec_url": notes["spec_url"], "notes": notes["notes"], "couldnt_confirm": notes["couldnt_confirm"],
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "deals_not_yet_parsed": missing,
    }
    with open(os.path.join(PARQUET_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print("manifest written; deals:", [x["deal"] for x in deals], "missing:", missing)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "fetch":
        fetch(sys.argv[2], sys.argv[3])
    elif cmd == "parse":
        for slug in sys.argv[2:]:
            parse(slug)
    elif cmd == "manifest":
        build_manifest()
    elif cmd == "check":
        check()
    else:
        raise SystemExit(__doc__)
