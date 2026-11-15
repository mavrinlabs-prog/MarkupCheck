"""One-at-a-time sec.gov fetch for the Capital One data helper.

usage:
  .venv/bin/python -I data/raw/capone/sec_get.py <url> <out_path>

The User-Agent is read from CLAUDE.md (git-ignored) so the contact address never lands in a committed file.
Every request is appended to data/raw/capone/sec_requests.log (also git-ignored). Other helpers download at the
same time, so this script sleeps 1 s before each request. No retries: a 403 is reported and the caller waits.
"""
import os
import re
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
LOG = os.path.join(HERE, "sec_requests.log")


def user_agent():
    text = open(os.path.join(ROOT, "CLAUDE.md")).read()
    m = re.search(r"use exactly this User-Agent[^`]*`([^`]+)`", text)
    if not m:
        raise SystemExit("User-Agent line not found in CLAUDE.md")
    return m.group(1)


def fetch(url, out_path):
    host = re.match(r"https://([^/]+)/", url).group(1)
    if not (host == "sec.gov" or host.endswith(".sec.gov")):
        raise SystemExit(f"not a sec.gov URL: {url}")
    time.sleep(1)
    headers = {"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"}
    n = 0
    with requests.get(url, headers=headers, timeout=600, stream=True) as r:
        if r.status_code == 200:
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
                    n += len(chunk)
        status = r.status_code
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {status} {n} {url}\n")
    print(status, n, url)
    return status


if __name__ == "__main__":
    sys.exit(0 if fetch(sys.argv[1], sys.argv[2]) == 200 else 1)
