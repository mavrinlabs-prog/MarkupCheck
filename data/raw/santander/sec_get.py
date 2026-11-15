"""Small polite SEC fetch helper (one request at a time, >=0.3 s apart, so well under 10 requests/s)."""
import time
import requests

# CLAUDE.md's plain User-Agent was rejected by www.sec.gov on Nov 14 2026 ("Undeclared Automated Tool");
# this longer string declares the project, with no personal email, and was accepted (HTTP 200).
UA = ("MarkupCheck student research project (Veritas AI International High School Hackathon 2026; "
      "non-commercial student project; no automated bulk crawling)")
HEADERS = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
_last = [0.0]


def get(url, **kw):
    wait = 0.3 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    r = requests.get(url, headers=HEADERS, timeout=120, **kw)
    _last[0] = time.time()
    return r
