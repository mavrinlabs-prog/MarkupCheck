"""Stretch: build data/parquet/ally/perf_ally_2024-1.parquet from the first 12 monthly EX-102 files of Ally 2024-1.

For each month: read the filing's index.json, download its EX-102 XML, parse the performance columns,
delete the XML. One request at a time, one pass, no retry loop. Needs SEC_UA in the environment (see build_ally.py).
"""
import json
import os
import re
import sys
import time

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
import parse_ally  # noqa: E402

UA = {"User-Agent": os.environ["SEC_UA"]}
CIK = "2010413"
# Trust-filed monthly ABS-EE accessions for reporting periods Feb 2024 .. Jan 2025, from the trust's data.sec.gov submissions list
MONTHS = [
    ("2024-02", "0002010413-24-000014"), ("2024-03", "0002010413-24-000015"), ("2024-04", "0002010413-24-000022"),
    ("2024-05", "0002010413-24-000028"), ("2024-06", "0002010413-24-000034"), ("2024-07", "0002010413-24-000039"),
    ("2024-08", "0002010413-24-000046"), ("2024-09", "0002010413-24-000052"), ("2024-10", "0002010413-24-000057"),
    ("2024-11", "0002010413-24-000063"), ("2024-12", "0002010413-25-000004"), ("2025-01", "0002010413-25-000009"),
]


def main():
    frames, log = [], []
    for month, acc in MONTHS:
        nodash = acc.replace("-", "")
        r = requests.get(f"https://www.sec.gov/Archives/edgar/data/{CIK}/{nodash}/index.json", headers=UA, timeout=60)
        r.raise_for_status()
        items = [i for i in r.json()["directory"]["item"] if re.match(r"^ex102.*\.xml$", i["name"], re.I)]
        if len(items) != 1:
            raise SystemExit(f"{acc}: expected one EX-102 xml, found {[i['name'] for i in items]}")
        name, size = items[0]["name"], int(items[0]["size"])
        url = f"https://www.sec.gov/Archives/edgar/data/{CIK}/{nodash}/{name}"
        dest = os.path.join(HERE, name)
        time.sleep(1)
        with requests.get(url, headers=UA, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(dest + ".part", "wb") as f:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        os.replace(dest + ".part", dest)
        got = os.path.getsize(dest)
        if got != size:
            raise SystemExit(f"{name}: got {got:,} bytes, index lists {size:,}")
        df = parse_ally.parse_perf(dest)
        periods = sorted(df["reporting_period_end"].dropna().unique())
        os.remove(dest)
        entry = {"month_expected": month, "accession": acc, "xml": name, "bytes": size, "rows": len(df),
                 "periods_in_file": periods, "zero_balance_codes": df["zero_balance_code"].fillna("<none>").value_counts().to_dict(),
                 "xml_deleted": not os.path.exists(dest)}
        log.append(entry)
        frames.append(df)
        print(json.dumps(entry), flush=True)
        time.sleep(1)
    out = pd.concat(frames, ignore_index=True)
    path = os.path.join(ROOT, "data", "parquet", "ally", "perf_ally_2024-1.parquet")
    pq.write_table(pa.Table.from_pandas(out, schema=parse_ally.PERF_SCHEMA, preserve_index=False), path, compression="zstd")
    json.dump(log, open(os.path.join(HERE, "stats_perf_ally_2024-1.json"), "w"), indent=1)
    print("wrote", path, len(out), "rows")


if __name__ == "__main__":
    main()
