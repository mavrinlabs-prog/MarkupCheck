"""Reload each CarMax Parquet and check it against CONTRACT.md.

usage: .venv/bin/python -I data/raw/carmax/validate.py
Exit status is 0 only if every check passes for every file.
"""
import glob
import json
import os
import re
import sys
from datetime import datetime

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
PARQUET_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "parquet", "carmax"))

# CONTRACT.md columns in order; kind is what pyarrow type family must be.
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
# The task brief's range. CarMax reports bureau auto scores on the FICO Auto scale (up to 900), so this fails on real data.
CREDIT_MIN, CREDIT_MAX = 300, 850


def check_file(path, manifest_rows):
    name = os.path.basename(path)
    results = []  # (label, ok, detail)
    schema = pq.read_schema(path)
    want_names = [c for c, _ in CONTRACT]
    results.append(("column names and order match CONTRACT", schema.names == want_names,
                    "" if schema.names == want_names else f"got {schema.names}"))
    bad_types = [f"{c}: {schema.field(c).type} (want {k})" for c, k in CONTRACT
                 if c in schema.names and not KIND[k](schema.field(c).type)]
    results.append(("column types match CONTRACT", not bad_types, "; ".join(bad_types)))

    df = pq.read_table(path).to_pandas()
    n = len(df)
    apr = df["apr_pct"]
    bad_apr = int((~((apr > 0) & (apr <= 40))).sum())
    results.append(("apr_pct in (0, 40]", bad_apr == 0,
                    f"{bad_apr} rows outside; min {apr.min()}, max {apr.max()}"))
    cs = df["credit_score"]
    out_rng = int(((cs < CREDIT_MIN) | (cs > CREDIT_MAX)).sum())
    results.append((f"credit_score is {CREDIT_MIN}-{CREDIT_MAX} or NaN", out_rng == 0,
                    f"{out_rng} rows outside; min {cs.min()}, max {cs.max()}, NaN {int(cs.isna().sum())}; "
                    f"{int((cs > CREDIT_MAX).sum())} above {CREDIT_MAX}, {int((cs < CREDIT_MIN).sum())} below {CREDIT_MIN}"))
    dups = int(df["asset_number"].duplicated().sum())
    results.append(("no duplicate asset_number", dups == 0, f"{dups} duplicates"))

    def month_ok(s):
        if not isinstance(s, str) or not re.fullmatch(r"\d{4}-\d{2}", s):
            return False
        try:
            datetime.strptime(s, "%Y-%m")
            return True
        except ValueError:
            return False

    bad_m = int((~df["origination_month"].map(month_ok)).sum())
    results.append(("origination_month parses as YYYY-MM", bad_m == 0,
                    f"{bad_m} bad; range {df['origination_month'].min()} to {df['origination_month'].max()}"))
    exp = manifest_rows.get(name[:-len('.parquet')])
    if exp is not None:
        results.append(("row count equals manifest rows_written", exp == n, f"parquet {n}, manifest {exp}"))
    return n, results


def main():
    mpath = os.path.join(PARQUET_DIR, "manifest.json")
    manifest_rows = {}
    if os.path.exists(mpath):
        m = json.load(open(mpath))
        for d in m["deals"]:
            slug = "carmax_" + d["deal"].rsplit(" ", 1)[1]
            manifest_rows[slug] = d["rows_written"]
    files = sorted(p for p in glob.glob(os.path.join(PARQUET_DIR, "*.parquet"))
                   if not os.path.basename(p).startswith("perf_"))
    if not files:
        print("no deal Parquet files found in", PARQUET_DIR)
        return 1
    failed = 0
    for p in files:
        n, results = check_file(p, manifest_rows)
        print(f"\n== {os.path.relpath(p, os.getcwd())}  ({n} rows)")
        for label, ok, detail in results:
            print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  -- {detail}" if detail else ""))
            failed += 0 if ok else 1
    print(f"\n{len(files)} file(s) checked, {failed} check(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
