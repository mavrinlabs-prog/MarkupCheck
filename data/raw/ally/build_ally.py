"""Download each chosen Ally first-pool EX-102 XML, parse it, write the Parquet, and emit per-deal stats.

Usage:  .venv/bin/python data/raw/ally/build_ally.py <deal_slug> [<deal_slug> ...]
Deal facts live in deals.json (next to this file); manifest.json is assembled by make_manifest.py
from deals.json + the stats files this script writes (data/raw/ally/stats_<slug>.json).
Only the User-Agent from CLAUDE.md is sent; one request at a time, far below 10 requests/second.
"""
import json
import os
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
import parse_ally  # noqa: E402

# The SEC User-Agent (with its approved contact) comes from the SEC_UA environment variable, taken from
# CLAUDE.md, so it never lands in a project file. Used for sec.gov URLs only.
UA = {"User-Agent": os.environ["SEC_UA"]}


def download(url, dest, expected_bytes):
    """Stream to disk once (no retry loop); keep an existing file only if it has the listed size."""
    if os.path.exists(dest) and os.path.getsize(dest) == expected_bytes:
        print(f"already have {dest} ({expected_bytes:,} bytes)")
        return expected_bytes
    with requests.get(url, headers=UA, stream=True, timeout=120) as r:
        r.raise_for_status()
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        os.replace(tmp, dest)
    size = os.path.getsize(dest)
    if size != expected_bytes:
        raise SystemExit(f"{dest}: got {size:,} bytes, filing index lists {expected_bytes:,}")
    print(f"downloaded {dest} ({size:,} bytes)")
    return size


def main(slugs):
    deals = {d["slug"]: d for d in json.load(open(os.path.join(HERE, "deals.json")))}
    out_dir = os.path.join(ROOT, "data", "parquet", "ally")
    os.makedirs(out_dir, exist_ok=True)
    for slug in slugs:
        d = deals[slug]
        xml_path = os.path.join(HERE, d["xml_name"])
        size = download(d["source_url"], xml_path, d["expected_bytes"])
        t0 = time.time()
        df, stats = parse_ally.parse_pool(xml_path, {
            "issuer": "ally", "deal": d["deal"], "deal_cik": d["deal_cik"],
            "source_url": d["source_url"], "filing_date": d["filing_date"]})
        parquet_path = os.path.join(out_dir, f"{slug}.parquet")
        parse_ally.write_parquet(df, parquet_path)
        stats.update({"slug": slug, "bytes": size, "parquet_file": f"{slug}.parquet",
                      "parse_seconds": round(time.time() - t0, 1)})
        json.dump(stats, open(os.path.join(HERE, f"stats_{slug}.json"), "w"), indent=1)
        print(slug, {k: v for k, v in stats.items() if k not in ("code_values_seen", "first_record_tags")})


if __name__ == "__main__":
    main(sys.argv[1:])
