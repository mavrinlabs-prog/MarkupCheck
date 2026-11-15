"""Reload every Ally deal Parquet and check it against CONTRACT.md.

Run from the project folder:  .venv/bin/python data/raw/ally/validate.py
Exit code 0 only if every check on every file passes.
"""
import glob
import json
import os
import re
import sys

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
OUT_DIR = os.path.join(ROOT, "data", "parquet", "ally")

# Column order and Arrow types exactly as CONTRACT.md lists them.
EXPECTED = [
    ("issuer", pa.string()),
    ("deal", pa.string()),
    ("deal_cik", pa.string()),
    ("source_url", pa.string()),
    ("filing_date", pa.string()),
    ("asset_number", pa.string()),
    ("origination_month", pa.string()),
    ("original_loan_amount", pa.float64()),
    ("original_term_months", pa.int64()),
    ("apr_pct", pa.float64()),
    ("interest_rate_type_code", pa.string()),
    ("subvented", pa.string()),
    ("vehicle_make", pa.string()),
    ("vehicle_model", pa.string()),
    ("new_used_code", pa.string()),
    ("vehicle_model_year", pa.int64()),
    ("vehicle_type_code", pa.string()),
    ("vehicle_value", pa.float64()),
    ("vehicle_value_source_code", pa.string()),
    ("credit_score_type", pa.string()),
    ("credit_score", pa.float64()),
    ("income_verification_code", pa.string()),
    ("employment_verification_code", pa.string()),
    ("co_obligor", pa.bool_()),
    ("pti_pct", pa.float64()),
    ("state", pa.string()),
]
YYYY_MM = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
YYYY_MM_DD = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_file(path):
    """Return a list of (check name, passed, detail) for one Parquet file."""
    results = []

    # kind "hard": must pass for the files to be usable. kind "strict": the literal CONTRACT/brief range check;
    # a failure is real data (kept as written, since CONTRACT says the main session does all filtering) and is
    # reported as FAIL with counts, but does not stop the run.
    def add(name, ok, detail="", kind="hard"):
        results.append((name, bool(ok), detail, kind))

    schema = pq.read_schema(path)
    got = [(f.name, f.type) for f in schema]
    names_ok = [n for n, _ in got] == [n for n, _ in EXPECTED]
    add("column names and order match CONTRACT", names_ok,
        "" if names_ok else f"got {[n for n, _ in got]}")
    type_bad = [(n, str(t), str(dict(EXPECTED).get(n))) for n, t in got
                if n in dict(EXPECTED) and t != dict(EXPECTED)[n]]
    add("column types match CONTRACT", not type_bad,
        "" if not type_bad else f"mismatches (name, got, want): {type_bad}")

    df = pq.read_table(path).to_pandas()
    add("file has rows", len(df) > 0, f"{len(df)} rows")

    apr = df["apr_pct"]
    bad_apr = ~((apr >= 0) & (apr <= 40))  # NaN also counts as bad
    add("apr_pct present and within [0, 40] for every row", not bad_apr.any(),
        f"min {apr.min():.4f}, max {apr.max():.4f}, bad rows {int(bad_apr.sum())}")
    zero_apr = int((apr == 0).sum())
    add("apr_pct strictly in (0, 40] (brief wording)", zero_apr == 0 and not bad_apr.any(),
        f"{zero_apr} rows have apr_pct == 0 (zero-rate loans, kept as written)", kind="strict")

    cs = df["credit_score"]
    ctype = df["credit_score_type"]
    sane_cs = cs.isna() | ((cs >= 1) & (cs <= 999))
    add("credit_score is NaN or within 1-999 (no scale errors)", sane_cs.all(),
        f"min {cs.min()}, max {cs.max()}, NaN {int(cs.isna().sum())}")
    nan_vs_type = (cs.isna() != (ctype == "None"))
    add("credit_score is NaN exactly when credit_score_type == 'None'", not nan_vs_type.any(),
        f"{int(cs.isna().sum())} NaN vs {int((ctype == 'None').sum())} type 'None'; mismatches {int(nan_vs_type.sum())}")
    bad_cs = cs.notna() & ~((cs >= 300) & (cs <= 850))
    by_type = ctype[bad_cs].value_counts().to_dict()
    add("credit_score 300-850 or NaN (brief wording)", not bad_cs.any(),
        f"{int(bad_cs.sum())} rows outside 300-850 ({int((cs > 850).sum())} above 850, {int((cs < 300).sum())} below 300), by score type {by_type}; kept as written",
        kind="strict")

    dups = int(df["asset_number"].duplicated().sum())
    add("no duplicate asset_number", dups == 0, f"{dups} duplicates")

    om = df["origination_month"]
    bad_om = om.isna() | ~om.astype(str).str.match(YYYY_MM)
    add("origination_month parses as YYYY-MM", not bad_om.any(),
        f"range {om.min()} .. {om.max()}, bad rows {int(bad_om.sum())}")

    fd = df["filing_date"]
    add("filing_date is YYYY-MM-DD and constant", fd.astype(str).str.match(YYYY_MM_DD).all() and fd.nunique() == 1,
        f"{fd.nunique()} distinct value(s): {sorted(fd.unique())[:3]}")

    add("issuer == 'ally'", (df["issuer"] == "ally").all())
    add("deal_cik is 10 digits", df["deal_cik"].astype(str).str.fullmatch(r"\d{10}").all(),
        str(sorted(df["deal_cik"].unique())))
    return results, df


def main():
    files = sorted(f for f in glob.glob(os.path.join(OUT_DIR, "*.parquet"))
                   if not os.path.basename(f).startswith("perf_"))
    all_ok = True
    strict_failed = []
    if len(files) < 3:
        print(f"FAIL: expected at least 3 deal Parquets in {OUT_DIR}, found {len(files)}")
        all_ok = False

    manifest_path = os.path.join(OUT_DIR, "manifest.json")
    manifest = json.load(open(manifest_path)) if os.path.exists(manifest_path) else None
    if manifest is None:
        print("FAIL: manifest.json missing")
        all_ok = False

    for path in files:
        results, df = check_file(path)
        print(f"\n== {os.path.relpath(path, ROOT)}  ({len(df):,} rows, {df['deal'].iloc[0]})")
        for name, ok, detail, kind in results:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
            if kind == "hard":
                all_ok &= ok
            elif not ok:
                strict_failed.append((os.path.basename(path), name))
        if manifest:
            entry = next((d for d in manifest["deals"] if os.path.basename(path) == d.get("parquet_file")), None)
            if entry is None:
                print("  [FAIL] manifest has an entry for this file")
                all_ok = False
            else:
                match = entry["rows_written"] == len(df)
                print(f"  [{'PASS' if match else 'FAIL'}] manifest rows_written == rows in Parquet  -- {entry['rows_written']:,} vs {len(df):,}")
                all_ok &= match

    perf_path = os.path.join(OUT_DIR, "perf_ally_2024-1.parquet")
    if os.path.exists(perf_path):
        perf = pq.read_table(perf_path).to_pandas()
        pool_path = os.path.join(OUT_DIR, "ally_2024-1.parquet")
        pool_ids = set(pq.read_table(pool_path, columns=["asset_number"]).to_pandas()["asset_number"])
        want = ["asset_number", "reporting_period_end", "current_delinquency_status",
                "chargedoff_principal_amount", "zero_balance_code", "repossessed"]
        months = sorted(perf["reporting_period_end"].unique())
        perf_checks = [
            ("columns match CONTRACT stretch list", list(perf.columns) == want, ""),
            ("reporting_period_end is YYYY-MM, at most 12 months",
             perf["reporting_period_end"].astype(str).str.match(YYYY_MM).all() and len(months) <= 12,
             f"{len(months)} months, {months[0]} .. {months[-1]}"),
            ("no duplicate (asset_number, month)", not perf.duplicated(["asset_number", "reporting_period_end"]).any(), ""),
            ("every asset_number exists in ally_2024-1.parquet", set(perf["asset_number"]) <= pool_ids,
             f"{perf['asset_number'].nunique():,} distinct of {len(pool_ids):,} pool loans"),
        ]
        print(f"\n== {os.path.relpath(perf_path, ROOT)}  ({len(perf):,} rows)")
        for name, ok, detail in perf_checks:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
            all_ok &= bool(ok)

    print(f"\nSTRICT BRIEF-WORDING CHECKS THAT FAILED ({len(strict_failed)}): data kept as written, main session filters")
    for fname, name in strict_failed:
        print(f"  {fname}: {name}")
    print("OVERALL (hard checks):", "ALL PASSED" if all_ok else "SOME FAILED")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
