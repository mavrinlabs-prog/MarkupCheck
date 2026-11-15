"""Stretch: monthly performance rows for one deal, from its monthly EX-102 files (at most 12 months).

usage:
  .venv/bin/python -I data/raw/carmax/parse_perf.py tags <xml>            # list element names seen in the first 20000 loans
  .venv/bin/python -I data/raw/carmax/parse_perf.py parse <xml> <out.parquet-part-dir>
The driver (run_perf.sh-style loop) calls `parse` once per month and deletes the XML afterwards; the part files are
concatenated into data/parquet/carmax/perf_<deal_slug>.parquet by `combine`.
"""
import glob
import math
import os
import sys
from collections import Counter

import pyarrow as pa
import pyarrow.parquet as pq
from lxml import etree

NS = "{http://www.sec.gov/edgar/document/absee/autoloan/assetdata}"
PERF_SCHEMA = pa.schema([
    ("asset_number", pa.string()), ("reporting_period_end", pa.string()),
    ("current_delinquency_status", pa.string()), ("chargedoff_principal_amount", pa.float64()),
    ("zero_balance_code", pa.string()), ("repossessed", pa.bool_()),
])


def tags(path, limit=20000):
    seen = Counter()
    n = 0
    for _, elem in etree.iterparse(path, events=("end",), tag=NS + "assets"):
        for c in elem:
            seen[c.tag[len(NS):]] += 1
        elem.clear()
        n += 1
        if n >= limit:
            break
    print(n, "loans scanned")
    for k, v in sorted(seen.items()):
        print(f"  {k}: {v}")


def to_float(t):
    try:
        return float(t)
    except (TypeError, ValueError):
        return math.nan


def parse(path, out_part):
    cols = {n: [] for n in PERF_SCHEMA.names}
    rows = 0
    for _, elem in etree.iterparse(path, events=("end",), tag=NS + "assets"):
        rec = {c.tag[len(NS):]: (c.text.strip() if c.text is not None else None) for c in elem}
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]
        end = rec.get("reportingPeriodEndingDate")  # MM-DD-YYYY
        period = f"{end[6:10]}-{end[0:2]}" if end else None
        rep = rec.get("repossessedIndicator")
        cols["asset_number"].append(rec.get("assetNumber"))
        cols["reporting_period_end"].append(period)
        cols["current_delinquency_status"].append(rec.get("currentDelinquencyStatus"))
        cols["chargedoff_principal_amount"].append(to_float(rec.get("chargedoffPrincipalAmount")))
        cols["zero_balance_code"].append(rec.get("zeroBalanceCode"))
        cols["repossessed"].append(None if rep is None else rep.lower() == "true")
        rows += 1
    pq.write_table(pa.Table.from_pydict(cols, schema=PERF_SCHEMA), out_part, compression="zstd")
    print(os.path.basename(path), "->", out_part, rows, "rows")


def combine(part_dir, out_path):
    parts = sorted(glob.glob(os.path.join(part_dir, "*.parquet")))
    table = pa.concat_tables([pq.read_table(p) for p in parts])
    pq.write_table(table, out_path, compression="zstd")
    print("combined", len(parts), "parts ->", out_path, table.num_rows, "rows")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "tags":
        tags(sys.argv[2])
    elif cmd == "parse":
        parse(sys.argv[2], sys.argv[3])
    elif cmd == "combine":
        combine(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(__doc__)
