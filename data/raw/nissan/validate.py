"""Reload each deal Parquet of this issuer and check it against CONTRACT.md and the brief's checks.

usage: .venv/bin/python -I data/raw/<issuer>/validate.py
The issuer is this script's folder name. Exit status is 0 only if every hard check passes; the brief's 300-850
credit-score wording is printed as INFO because lenders report FICO Auto scores, which run 250-900 (CONTRACT.md).
"""
import glob
import json
import os
import re
import sys

import pyarrow as pa
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
ISSUER = os.path.basename(HERE)
PARQUET_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "parquet", ISSUER))

CONTRACT = [
    ("issuer", "string"), ("deal", "string"), ("deal_cik", "string"), ("source_url", "string"),
    ("filing_date", "string"), ("asset_number", "string"), ("origination_month", "string"),
    ("original_loan_amount", "float"), ("original_term_months", "int"), ("apr_pct", "float"),
    ("interest_rate_type_code", "string"), ("subvented", "string"), ("vehicle_make", "string"),
    ("vehicle_model", "string"), ("new_used_code", "string"), ("vehicle_model_year", "int"),
    ("vehicle_type_code", "string"), ("vehicle_value", "float"), ("vehicle_value_source_code", "string"),
    ("credit_score_type", "string"), ("credit_score", "float"),
    ("income_verification_code", "string"), ("employment_verification_code", "string"),
    ("co_obligor", "bool"), ("pti_pct", "float"), ("state", "string"),
]
KIND = {
    "string": lambda t: pa.types.is_string(t) or pa.types.is_large_string(t),
    "float": pa.types.is_floating,
    "int": pa.types.is_integer,
    "bool": pa.types.is_boolean,
}


def check_file(path, mdeal):
    out = []  # (level, label, ok, detail); level 'hard' or 'info'
    schema = pq.read_schema(path)
    names = [c for c, _ in CONTRACT]
    out.append(("hard", "column names and order match CONTRACT", schema.names == names,
                "" if schema.names == names else f"got {schema.names}"))
    bad = [f"{c}: {schema.field(c).type}" for c, k in CONTRACT if c in schema.names and not KIND[k](schema.field(c).type)]
    out.append(("hard", "column types match CONTRACT", not bad, "; ".join(bad)))
    df = pq.read_table(path).to_pandas()
    n = len(df)
    out.append(("hard", f"issuer == '{ISSUER}'", bool((df["issuer"] == ISSUER).all()), ""))
    out.append(("hard", "deal_cik is 10 digits", bool(df["deal_cik"].str.fullmatch(r"\d{10}").all()),
                str(sorted(df["deal_cik"].unique()))))
    if mdeal:
        out.append(("hard", "rows == manifest rows_written", n == mdeal["rows_written"],
                    f"parquet {n:,}, manifest {mdeal['rows_written']:,}"))
        pc = mdeal.get("prospectus_loan_count_if_found")
        out.append(("hard", "rows == 424B5 'Number of Receivables'", n == pc, f"parquet {n:,}, 424B5 {pc:,}"))
    dups = int(df["asset_number"].duplicated().sum())
    out.append(("hard", "no duplicate asset_number", dups == 0, f"{dups} duplicates"))
    om = df["origination_month"]
    bad_m = int((~om.fillna("").str.fullmatch(r"\d{4}-(0[1-9]|1[0-2])")).sum())
    out.append(("hard", "origination_month is YYYY-MM", bad_m == 0, f"{bad_m} bad; range {om.min()} .. {om.max()}"))
    late = int((om > "2026-01").sum())
    out.append(("hard", "no loan originated after 2026-01", late == 0, f"{late} rows"))
    apr = df["apr_pct"]
    bad_apr = int((~apr.between(0, 40)).sum())
    out.append(("hard", "apr_pct within [0, 40]", bad_apr == 0,
                f"min {apr.min()}, median {apr.median()}, max {apr.max()}; {int((apr == 0).sum())} rows exactly 0"))
    cs = df["credit_score"]
    share = cs.notna().mean()
    out.append(("info", "share of rows with a numeric credit_score", True, f"{share:.4%}"))
    for t, g in df.groupby(df["credit_score_type"].fillna("<missing>"))["credit_score"]:
        out.append(("info", f"credit_score for type '{t}'", True,
                    f"rows {len(g):,}, numeric {int(g.notna().sum()):,}, min {g.min()}, median {g.median()}, max {g.max()}"))
    out_fico = int(((cs < 250) | (cs > 900)).sum())
    out.append(("hard", "credit_score within 250-900 (FICO Auto scale) or NaN", out_fico == 0, f"{out_fico} rows outside"))
    out_brief = int(((cs < 300) | (cs > 850)).sum())
    out.append(("info", "credit_score within 300-850 (brief wording)", out_brief == 0,
                f"{out_brief} rows outside ({int((cs > 850).sum())} above 850, {int((cs < 300).sum())} below 300)"))
    pti = df["pti_pct"]
    med = pti.median()
    out.append(("hard", "pti_pct is on a percent scale (median between 1 and 50)", 1 <= med <= 50,
                f"median {med}, max {pti.max()}, NaN {int(pti.isna().sum())}, rows == 999.99: {int((pti == 999.99).sum())}"))
    return n, out


def main():
    m = json.load(open(os.path.join(PARQUET_DIR, "manifest.json")))
    by_slug = {}
    for d in m["deals"]:
        by_slug[f"{ISSUER}_" + re.search(r"(\d{4}-[A-Z0-9]+) Owner Trust", d["deal"]).group(1)] = d
    files = sorted(p for p in glob.glob(os.path.join(PARQUET_DIR, f"{ISSUER}_*.parquet")))
    failed = 0
    for p in files:
        slug = os.path.basename(p)[:-len(".parquet")]
        n, results = check_file(p, by_slug.get(slug))
        print(f"\n== data/parquet/{ISSUER}/{slug}.parquet  ({n:,} rows)")
        for level, label, ok, detail in results:
            tag = ("PASS" if ok else "FAIL") if level == "hard" else ("INFO" if ok else "INFO-FAIL")
            print(f"  [{tag}] {label}" + (f"  -- {detail}" if detail else ""))
            failed += 0 if (ok or level == "info") else 1
    for k in ("credit_score_type", "subvented", "new_used_code", "interest_rate_type_code"):
        print(f"\ncode_values_seen[{k}] = {m['code_values_seen'][k]}")
    print(f"\n{len(files)} file(s) checked, {failed} hard check(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
