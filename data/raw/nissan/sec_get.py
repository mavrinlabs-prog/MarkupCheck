"""One polite sec.gov request at a time, logged.

usage: SEC_UA="<the User-Agent from CLAUDE.md>" .venv/bin/python -I sec_get.py <url> <dest_file_in_this_folder> [...]

At least 1 s between requests (other helpers download from SEC in parallel). No retries: a non-200 answer is logged
and the script stops, so the caller can wait 10 minutes and try once more by hand.
"""
import os
import sys
import time
from datetime import datetime

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "sec_requests.log")
UA = os.environ["SEC_UA"]


def fetch(url, dest):
    part = dest + ".part"
    with requests.get(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}, stream=True,
                      timeout=300) as r:
        n = 0
        if r.status_code == 200:
            with open(part, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    n += len(chunk)
            os.replace(part, dest)
        with open(LOG, "a") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {r.status_code} {n} {url}\n")
        print(r.status_code, n, url, flush=True)
        return r.status_code


if __name__ == "__main__":
    args = sys.argv[1:]
    for i in range(0, len(args), 2):
        if i:
            time.sleep(1.1)
        if fetch(args[i], os.path.join(HERE, args[i + 1])) != 200:
            sys.exit(1)
