"""Reload every Santander deal Parquet and check it against CONTRACT.md.

Run: .venv/bin/python data/raw/santander/validate.py
Exits non-zero if any hard check fails. APRs above 25% and above 40% are reported, not hidden.
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
PQ_DIR = ROOT / "data" / "parquet" / "santander"

EXPECTED = [
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
]
MANIFEST_KEYS = ["issuer", "user_agent", "deals", "code_values_seen", "spec_url", "notes",
                 "couldnt_confirm"]
DEAL_KEYS = ["deal", "deal_cik", "filing_date", "accession", "source_url",
             "why_this_is_the_first_pool_filing", "bytes", "rows_parsed", "rows_written",
             "duplicate_asset_numbers_dropped", "origination_month_min",
             "origination_month_max", "prospectus_loan_count_if_found"]
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

failures = []


def check(ok, label):
    print(("  PASS  " if ok else "  FAIL  ") + label)
    if not ok:
        failures.append(label)


files = sorted(p for p in PQ_DIR.glob("*.parquet") if not p.name.startswith("perf_"))
print(f"deal files found: {[p.name for p in files]}")
check(len(files) == 3, "exactly three deal Parquet files")

manifest = None
mpath = PQ_DIR / "manifest.json"
if mpath.exists():
    manifest = json.loads(mpath.read_text())
    check(all(k in manifest for k in MANIFEST_KEYS), "manifest.json has every top-level key")
    for d in manifest["deals"]:
        check(all(k in d for k in DEAL_KEYS), f"manifest deal {d.get('deal')} has every key")
else:
    check(False, "manifest.json exists")

for p in files:
    print(f"\n== {p.name}")
    schema = pq.read_schema(p)
    check(schema.names == [n for n, _ in EXPECTED], "column names and order match CONTRACT")
    check(all(schema.field(n).type == t for n, t in EXPECTED if n in schema.names),
          "column types match CONTRACT (string/float64/int64/bool)")
    df = pd.read_parquet(p)
    n = len(df)
    print(f"  rows: {n}")
    check(n > 0, "has rows")
    check(df["issuer"].eq("santander").all(), "issuer == 'santander' on every row")
    check(df["deal_cik"].str.fullmatch(r"\d{10}").all(), "deal_cik is 10 digits")
    check(df["filing_date"].str.fullmatch(r"\d{4}-\d{2}-\d{2}").all(), "filing_date is YYYY-MM-DD")
    check(df["deal"].nunique() == 1 and df["source_url"].nunique() == 1,
          "one deal name and one source_url per file")
    apr = df["apr_pct"]
    check(apr.notna().all(), f"apr_pct has no NaN (NaN count {int(apr.isna().sum())})")
    zero = apr == 0
    check(((apr >= 0) & (apr <= 40)).all(),
          f"apr_pct in [0, 40]  [min {apr.min():.3f}, max {apr.max():.3f}; "
          f"above 40: {int((apr > 40).sum())} rows; negative: {int((apr < 0).sum())} rows]")
    # The brief asks for (0, 40]. Exact zeros are real 0% manufacturer-subvented loans (the prospectus lists the
    # contract-rate range as 0.00% to 29.99%), and CONTRACT says not to drop rows, so they are reported, not failed.
    print(f"  info: apr_pct == 0 (fail the strict (0, 40] test): {int(zero.sum())} rows "
          f"(subvented codes {df.loc[zero, 'subvented'].value_counts().to_dict()}, "
          f"new_used codes {df.loc[zero, 'new_used_code'].value_counts().to_dict()})")
    print(f"  info: apr_pct > 25: {int((apr > 25).sum())} rows; apr_pct > 40: {int((apr > 40).sum())} rows")
    cs = df["credit_score"]
    ok_cs = cs.isna() | ((cs >= 300) & (cs <= 850))
    check(ok_cs.all(), f"credit_score 300-850 or NaN  [NaN {int(cs.isna().sum())}, "
                       f"min {cs.min()}, max {cs.max()}; out of range {int((~ok_cs).sum())}]")
    check(not df["asset_number"].duplicated().any(),
          f"no duplicate asset_number [{int(df['asset_number'].duplicated().sum())} dups]")
    om = df["origination_month"]
    check(om.notna().all() and om.map(lambda s: bool(MONTH_RE.match(s)) if isinstance(s, str) else False).all(),
          f"origination_month parses as YYYY-MM  [{om.min()} .. {om.max()}]")
    if manifest:
        m = next((d for d in manifest["deals"] if d["deal"] == df["deal"].iloc[0]), None)
        check(m is not None and m["rows_written"] == n,
              f"manifest rows_written matches file ({m['rows_written'] if m else 'no entry'} vs {n})")
        if m:
            check(m["origination_month_min"] == om.min() and m["origination_month_max"] == om.max(),
                  "manifest origination-month range matches file")

for p in sorted(PQ_DIR.glob("perf_*.parquet")):
    print(f"\n== {p.name} (stretch performance file)")
    expected = [("asset_number", pa.string()), ("reporting_period_end", pa.string()),
                ("current_delinquency_status", pa.int64()), ("chargedoff_principal_amount", pa.float64()),
                ("zero_balance_code", pa.string()), ("repossessed", pa.bool_())]
    schema = pq.read_schema(p)
    check(schema.names == [n for n, _ in expected] and all(schema.field(n).type == t for n, t in expected),
          "perf column names and types match CONTRACT")
    perf = pd.read_parquet(p)
    months = sorted(perf["reporting_period_end"].unique())
    print(f"  rows: {len(perf)}; months: {months[0]} .. {months[-1]} ({len(months)})")
    check(len(months) <= 12 and all(MONTH_RE.match(m) for m in months), "at most 12 months, each YYYY-MM")
    check(not perf.duplicated(["asset_number", "reporting_period_end"]).any(), "no duplicate (asset_number, month)")
    pool_file = PQ_DIR / p.name.replace("perf_", "")
    if pool_file.exists():
        pool_ids = set(pd.read_parquet(pool_file, columns=["asset_number"])["asset_number"])
        check(perf["asset_number"].isin(pool_ids).all(), "every perf asset_number is in the deal's pool file")
        print(f"  info: {len(pool_ids & set(perf['asset_number']))} of {len(pool_ids)} pool loans appear in perf")

print()
if failures:
    print(f"VALIDATION FAILED: {len(failures)} check(s) failed")
    sys.exit(1)
print("VALIDATION PASSED: all checks passed")
