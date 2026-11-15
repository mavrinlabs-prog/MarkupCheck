"""Stretch: monthly performance for ONE deal (SDART 2024-1), first 12 monthly EX-102 files.

For each monthly ABS-EE filing of the trust: find the EX-102 XML in the filing's index.json, stream it to disk,
parse the six CONTRACT perf columns, append to data/parquet/santander/perf_santander_2024-1.parquet, then
delete the XML right away. Usage: perf_santander.py   (about 12 downloads of 100-250 MB each)
"""
import json
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from lxml import etree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # run with `python -I`, which drops the script folder from sys.path
import sec_get  # noqa: E402

NS = "http://www.sec.gov/edgar/document/absee/autoloan/assetdata"
OUT = HERE.parent.parent / "parquet" / "santander" / "perf_santander_2024-1.parquet"
CIK = 2004812
# Monthly (trust-own) ABS-EE filings for reporting periods 2024-01-31 .. 2024-12-31, from data.sec.gov submissions.
MONTHLY = [
    ("0000950131-24-000575", "2024-02-15"), ("0000950131-24-000990", "2024-03-15"),
    ("0000950131-24-001433", "2024-04-15"), ("0000950131-24-001970", "2024-05-15"),
    ("0000950131-24-002506", "2024-06-17"), ("0000950131-24-002869", "2024-07-15"),
    ("0000950131-24-003331", "2024-08-15"), ("0000950131-24-003706", "2024-09-16"),
    ("0000950131-24-004125", "2024-10-15"), ("0000950131-24-004544", "2024-11-15"),
    ("0000950131-24-004928", "2024-12-16"), ("0000950131-25-000212", "2025-01-15"),
]
SCHEMA = pa.schema([
    ("asset_number", pa.string()), ("reporting_period_end", pa.string()),
    ("current_delinquency_status", pa.int64()), ("chargedoff_principal_amount", pa.float64()),
    ("zero_balance_code", pa.string()), ("repossessed", pa.bool_()),
])


def period(text):  # reportingPeriodEndingDate is MM-DD-YYYY
    if not text:
        return None
    parts = text.strip().split("-")
    return f"{parts[2]}-{parts[0]}" if len(parts) == 3 else None


def parse_month(xml_path):
    cols = {n: [] for n in SCHEMA.names}
    for _, elem in etree.iterparse(str(xml_path), events=("end",), tag=f"{{{NS}}}assets", huge_tree=True):
        f = {}
        for c in elem:
            t = c.text.strip() if c.text and c.text.strip() else None
            if t is not None:
                name = etree.QName(c).localname
                f[name] = f[name] + "," + t if name in f else t  # zeroBalanceCode may repeat
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]
        dq = f.get("currentDelinquencyStatus")
        co = f.get("chargedoffPrincipalAmount")
        rp = (f.get("repossessedIndicator") or "").lower()
        cols["asset_number"].append(f.get("assetNumber"))
        cols["reporting_period_end"].append(period(f.get("reportingPeriodEndingDate")))
        cols["current_delinquency_status"].append(int(float(dq)) if dq is not None else None)
        cols["chargedoff_principal_amount"].append(float(co) if co is not None else None)
        cols["zero_balance_code"].append(f.get("zeroBalanceCode"))
        cols["repossessed"].append(True if rp == "true" else False if rp == "false" else None)
    return cols


def main():
    log = []
    writer = pq.ParquetWriter(OUT, SCHEMA, compression="zstd")
    try:
        for acc, filed in MONTHLY:
            folder = f"https://www.sec.gov/Archives/edgar/data/{CIK}/{acc.replace('-', '')}"
            items = sec_get.get(folder + "/index.json").json()["directory"]["item"]
            names = [i["name"] for i in items if "ex102" in i["name"].lower() and i["name"].endswith(".xml")]
            assert len(names) == 1, (acc, names)
            name = names[0]
            dest = HERE / name
            t0 = time.time()
            with sec_get.get(f"{folder}/{name}", stream=True) as r:
                r.raise_for_status()
                with open(dest, "wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
            size = dest.stat().st_size
            try:
                cols = parse_month(dest)
            finally:
                dest.unlink()  # CONTRACT: delete each monthly XML right after parsing
            writer.write_table(pa.table({n: pa.array(cols[n], type=SCHEMA.field(n).type) for n in SCHEMA.names},
                                        schema=SCHEMA))
            months = sorted(set(cols["reporting_period_end"]))
            entry = {"accession": acc, "filing_date": filed, "file": name, "bytes": size,
                     "rows": len(cols["asset_number"]), "reporting_period_end": months,
                     "seconds": round(time.time() - t0)}
            log.append(entry)
            print(json.dumps(entry), flush=True)
    finally:
        writer.close()
    (HERE / "stats_perf_santander_2024-1.json").write_text(json.dumps(log, indent=1))
    print("wrote", OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    sys.exit(main())
