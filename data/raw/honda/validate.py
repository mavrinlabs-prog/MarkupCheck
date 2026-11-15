"""Check this issuer's Parquet files against CONTRACT.md, the manifest and the 424B5 figures.

usage: .venv/bin/python -I data/raw/<issuer>/validate.py

The issuer is the name of the folder this file sits in. Hard checks decide the exit code; lines marked [INFO] only
report (the brief's 300-850 credit-score wording, seasoning, prospectus APR range).
"""
import json
import os
import sys

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
ISSUER = os.path.basename(HERE)
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
PARQUET_DIR = os.path.join(ROOT, "data", "parquet", ISSUER)

CONTRACT = [
    ("issuer", pa.string()), ("deal", pa.string()), ("deal_cik", pa.string()), ("source_url", pa.string()),
    ("filing_date", pa.string()), ("asset_number", pa.string()), ("origination_month", pa.string()),
    ("original_loan_amount", pa.float64()), ("original_term_months", pa.int64()), ("apr_pct", pa.float64()),
    ("interest_rate_type_code", pa.string()), ("subvented", pa.string()), ("vehicle_make", pa.string()),
    ("vehicle_model", pa.string()), ("new_used_code", pa.string()), ("vehicle_model_year", pa.int64()),
    ("vehicle_type_code", pa.string()), ("vehicle_value", pa.float64()), ("vehicle_value_source_code", pa.string()),
    ("credit_score_type", pa.string()), ("credit_score", pa.float64()),
    ("income_verification_code", pa.string()), ("employment_verification_code", pa.string()),
    ("co_obligor", pa.bool_()), ("pti_pct", pa.float64()), ("state", pa.string()),
]

# APR ranges as printed in each deal's 424B5 (Honda: "Range of annual percentage rates"; Hyundai: "APR (range)",
# total-pool column). Shown next to the file's own range; not a pass/fail check.
PROSPECTUS_APR_RANGE = {
    "Honda Auto Receivables 2024-1 Owner Trust": "0.69% to 24.08%",
    "Honda Auto Receivables 2025-1 Owner Trust": "0.50% to 25.79%",
    "Honda Auto Receivables 2026-1 Owner Trust": "0.90% to 24.29%",
    "Hyundai Auto Receivables Trust 2024-A": "0.00% to 14.95%",
    "Hyundai Auto Receivables Trust 2025-A": "0.00% to 14.95%",
    "Hyundai Auto Receivables Trust 2026-A": "0.00% to 14.99%",
}

failed = 0


def check(ok, label, detail=""):
    global failed
    failed += 0 if ok else 1
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))


def info(label, detail):
    print(f"  [INFO] {label}  -- {detail}")


def months_between(a, b):
    ya, ma = map(int, a.split("-"))
    yb, mb = map(int, b.split("-"))
    return (yb - ya) * 12 + (mb - ma)


manifest = json.load(open(os.path.join(PARQUET_DIR, "manifest.json")))
by_url = {d["source_url"]: d for d in manifest["deals"]}
files = sorted(f for f in os.listdir(PARQUET_DIR) if f.endswith(".parquet") and not f.startswith("perf_"))
for name in files:
    path = os.path.join(PARQUET_DIR, name)
    t = pq.read_table(path)
    df = t.to_pandas()
    deal = df["deal"].iloc[0]
    print(f"\n== data/parquet/{ISSUER}/{name}  ({len(df):,} rows, {deal})")
    check([f.name for f in t.schema] == [c for c, _ in CONTRACT], "column names and order match CONTRACT")
    check(all(t.schema.field(c).type == ty for c, ty in CONTRACT), "column types match CONTRACT")
    check((df["issuer"] == ISSUER).all(), f"issuer == '{ISSUER}'")
    check(df["deal_cik"].str.fullmatch(r"\d{10}").all() and df["deal_cik"].nunique() == 1, "deal_cik is 10 digits",
          str(df["deal_cik"].unique().tolist()))
    check(df["source_url"].nunique() == 1 and df["filing_date"].nunique() == 1, "one source_url and filing_date",
          f"{df['filing_date'].iloc[0]}  {df['source_url'].iloc[0]}")
    m = by_url[df["source_url"].iloc[0]]
    pc = m["prospectus_loan_count_if_found"]
    check(pc is not None and m["rows_parsed"] == pc, "rows parsed equal the 424B5 receivable count",
          f"rows_parsed {m['rows_parsed']:,}, 424B5 {pc:,}" if pc else "no 424B5 count")
    check(len(df) == m["rows_written"], "Parquet rows equal manifest rows_written",
          f"{len(df):,} vs {m['rows_written']:,}")
    dups = int(df["asset_number"].duplicated().sum())
    check(dups == 0, "no duplicate asset_number", f"{dups} duplicates")
    om = df["origination_month"]
    bad = int((~om.fillna("").str.fullmatch(r"\d{4}-(0[1-9]|1[0-2])")).sum())
    check(bad == 0, "origination_month parses as YYYY-MM", f"range {om.min()} .. {om.max()}, bad rows {bad}")
    check(om.max() <= "2026-01", "no loan originated after 2026-01", f"latest {om.max()}")
    fd = df["filing_date"].iloc[0][:7]
    old = int((om.map(lambda x: months_between(x, fd)) > 12).sum())
    info("seasoning", f"{old:,} rows ({old / len(df):.1%}) originated more than 12 months before the filing month {fd}")
    apr = df["apr_pct"]
    check(apr.notna().all() and apr.between(0, 40).all(), "apr_pct present and within [0, 40]",
          f"min {apr.min():.2f}, max {apr.max():.2f}, exactly 0: {int((apr == 0).sum())}")
    info("424B5 APR range", f"{PROSPECTUS_APR_RANGE.get(deal, 'not recorded')}; file {apr.min():.2f}% to {apr.max():.2f}%")
    cs = df["credit_score"]
    share = cs.notna().mean()
    info("numeric credit_score share", f"{share:.4%} ({int(cs.notna().sum()):,} of {len(df):,})")
    check(cs.dropna().between(250, 900).all(), "credit_score within the FICO Auto scale 250-900 or NaN",
          f"min {cs.min()}, max {cs.max()}, NaN {int(cs.isna().sum())}")
    for typ, g in df.groupby("credit_score_type", dropna=False):
        s = g["credit_score"].dropna()
        info(f"credit_score for type {typ!r}", f"n {len(g):,}, numeric {len(s):,}, min {s.min():.0f}, "
             f"median {s.median():.0f}, max {s.max():.0f}")
    out = int(((cs < 300) | (cs > 850)).sum())
    info("credit_score outside 300-850 (brief's classic FICO range)",
         f"{out:,} rows ({int((cs > 850).sum()):,} above 850, {int((cs < 300).sum()):,} below 300); kept as written")
    for col in ("credit_score_type", "subvented", "new_used_code", "interest_rate_type_code"):
        info(col, str(df[col].value_counts(dropna=False).to_dict()))
    info("vehicle_make (top 6)", str(df["vehicle_make"].value_counts(dropna=False).head(6).to_dict()))

print(f"\n{len(files)} file(s) checked, {failed} check(s) failed")
sys.exit(1 if failed else 0)
