"""One sec.gov request per call, paced and counted.

usage: .venv/bin/python -I data/raw/hyundai/sec_fetch.py <url> <out_path>

Sleeps 1 s before the request (other helpers download in parallel; the brief allows this session 1 request per
second), never retries, and appends one line per request to data/raw/hyundai/sec_requests.log. A 403 exits with code 3
so the caller can wait 10 minutes and try once more by hand. The User-Agent is the one CLAUDE.md approves for sec.gov
only; it is read from CLAUDE.md so the contact address is not copied into this file.
"""
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
LOG = os.path.join(HERE, "sec_requests.log")


def user_agent():
    text = open(os.path.join(ROOT, "CLAUDE.md")).read()
    return re.search(r"use exactly this User-Agent[^`]*`([^`]+)`", text).group(1)


def main(url, out):
    host = re.match(r"https://([^/]+)/", url).group(1)
    if host not in ("www.sec.gov", "data.sec.gov", "efts.sec.gov"):
        raise SystemExit(f"refusing non-sec.gov host {host}")
    time.sleep(1)
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = requests.get(url, headers={"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"},
                     stream=True, timeout=600)
    n = 0
    if r.status_code == 200:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                n += len(chunk)
    with open(LOG, "a") as f:
        f.write(f"{started}\t{r.status_code}\t{n}\t{url}\n")
    count = sum(1 for _ in open(LOG))
    print(f"HTTP {r.status_code}  {n:,} bytes  -> {out}  (request #{count} in {os.path.basename(HERE)} log)")
    if r.status_code == 403:
        sys.exit(3)
    if r.status_code != 200:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
