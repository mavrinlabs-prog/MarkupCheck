"""Credit-union new- and used-vehicle loan rates from NCUA's quarterly Call Report (Form 5300) bulk data.

Each federally insured credit union reports, on Form 5300 Schedule A Section 1, the interest rate it is offering
as of the quarter-end date for new-vehicle loans (account 523) and used-vehicle loans (account 524); if more than one
rate applies, it reports the most common one (Call Report instructions, Schedule A "Interest Rates"). It reports a
rate only when it has loans outstanding in that category. It is not a rate for a given credit score or term.

Writes data/benchmark/ncua_callreport_<YYYY-MM>.zip (the download), ncua_callreport_vehicle_rates_<YYYY-MM>.csv
(one row per credit union), ncua_callreport_state_stats_<YYYY-MM>.csv, and the "ncua_callreport" section of
app/model/rates_extra.json: count, 25th percentile, median and 75th percentile, nationally and by state.
Outliers: a rate is dropped if it lies more than 3 interquartile ranges below the national 25th percentile or
above the national 75th percentile for that product (Tukey's "far out" fences), the same fences for every state.
Run: .venv/bin/python src/fetch_ncua_callreport.py [YYYY-MM, default: newest on NCUA's page]
"""
import datetime
import json
import pathlib
import re
import sys
import zipfile

import pandas as pd
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
BENCH = ROOT / "data" / "benchmark"
JSON_OUT = ROOT / "app" / "model" / "rates_extra.json"
UA = {"User-Agent": "MarkupCheck student research project"}
PAGE = "https://ncua.gov/analysis/credit-union-corporate-call-report-data/quarterly-data"
FORM = "https://ncua.gov/files/publications/regulations/call-report-form-march-2025.pdf"
INSTRUCTIONS = "https://ncua.gov/files/publications/regulations/call-report-instructions-september-2025.pdf"
FENCE_IQR = 3.0
# product: (rate account, number-of-loans account, amount account), per Form 5300 Schedule A Section 1 lines 5 and 6
ACCOUNTS = {"new": ("Acct_523", "Acct_958", "Acct_385"), "used": ("Acct_524", "Acct_968", "Acct_370")}
FIELD_MEANING = (
    "The interest rate the credit union was offering on {kind}-vehicle loans as of {as_of}, as reported on NCUA Form "
    "5300 Schedule A Section 1 line {line} (account {acct}). The instructions say to report rates 'being offered as "
    "of the reporting period' and, if more than one rate applies, 'the most common rate' in the category. Reported "
    "only by credit unions with {kind}-vehicle loans outstanding. One rate per credit union: not tied to a credit "
    "score or term, and not an average of loans made. Label it 'a rate this credit union offers', never 'your rate'.")


def get(url):
    r = requests.get(url, headers=UA, timeout=300)
    r.raise_for_status()
    return r


def write_section(key, section, sources):
    """Replace one section of rates_extra.json, keeping the other script's section."""
    doc = json.loads(JSON_OUT.read_text()) if JSON_OUT.exists() else {}
    built = doc.get("built", {})
    built[key] = datetime.date.today().isoformat()
    srcs = doc.get("sources", {})
    srcs[key] = sources
    doc[key] = section
    out = {"built": {k: built[k] for k in sorted(built)}, "sources": {k: srcs[k] for k in sorted(srcs)}}
    for k in ("g19", "ncua_callreport"):
        if k in doc:
            out[k] = doc[k]
    JSON_OUT.write_text(json.dumps(out, indent=1) + "\n")


def stats(s):
    return {"n": int(len(s)), "p25": round(float(s.quantile(0.25)), 2), "median": round(float(s.median()), 2),
            "p75": round(float(s.quantile(0.75)), 2)}


# 1. Newest quarterly zip listed on NCUA's page (or the one asked for).
if len(sys.argv) > 1:
    cycle = sys.argv[1]
else:
    cycle = max(re.findall(r"call-report-data-(\d{4}-\d{2})\.zip", get(PAGE).text))
zip_url = f"https://ncua.gov/files/publications/analysis/call-report-data-{cycle}.zip"
zpath = BENCH / f"ncua_callreport_{cycle}.zip"
zpath.write_bytes(get(zip_url).content)

with zipfile.ZipFile(zpath) as z:
    def read(name, **kw):
        return pd.read_csv(z.open(name), **kw)

    desc = read("AcctDesc.txt").drop_duplicates("Account").set_index("Account")
    needed = [a for accts in ACCOUNTS.values() for a in accts]
    for a in needed:
        if a not in desc.index or str(desc.at[a, "STATUS"]) != "True":
            raise SystemExit(f"{a} is missing or not STATUS=True in AcctDesc.txt for {cycle}; recheck the form.")
    for a in ("Acct_523", "Acct_524"):
        if not desc.at[a, "AcctName"].startswith("Interest Rate of "):
            raise SystemExit(f"{a} is now '{desc.at[a, 'AcctName']}'; recheck the form.")
    cus = read("FOICU.txt", usecols=["CU_NUMBER", "CYCLE_DATE", "CU_NAME", "CITY", "STATE"])
    for table in sorted({desc.at[a, "TableName"] for a in needed}):
        cols = [a.upper() for a in needed if desc.at[a, "TableName"] == table]
        cus = cus.merge(read(f"{table}.txt", usecols=["CU_NUMBER"] + cols), on="CU_NUMBER", how="left",
                        validate="one_to_one")

dates = cus["CYCLE_DATE"].unique()
if len(dates) != 1:
    raise SystemExit(f"Expected one cycle date, found {dates}")
as_of = datetime.datetime.strptime(dates[0].split()[0], "%m/%d/%Y").date()
quarter = f"{as_of.year} Q{(as_of.month - 1) // 3 + 1}"
for c in ("CU_NAME", "CITY", "STATE"):
    cus[c] = cus[c].astype(str).str.strip()

# 2. Per credit union. The bulk file stores the rate x100 (546 means 5.46%, 668.42 means 6.6842%); the median
# check below would fail if NCUA ever switched to the form's own "6.5 for 6.5%" style.
out = cus[["CU_NUMBER", "CU_NAME", "CITY", "STATE"]].rename(columns=str.lower)
summary = {}
for prod, (rate, number, amount) in ACCOUNTS.items():
    r = cus[rate.upper()].fillna(0) / 100
    out[f"{prod}_rate_pct"] = r.where(r > 0).round(4)
    out[f"{prod}_loans_n"] = cus[number.upper()].fillna(0).astype(int)
    out[f"{prod}_loans_usd"] = cus[amount.upper()].fillna(0).astype("int64")
    reported = out[f"{prod}_rate_pct"].dropna()
    if not 1 < reported.median() < 20:
        raise SystemExit(f"{prod} median rate {reported.median()} looks like a unit change; check the bulk file.")
    q1, q3 = reported.quantile([0.25, 0.75])
    lo, hi = q1 - FENCE_IQR * (q3 - q1), q3 + FENCE_IQR * (q3 - q1)
    out[f"{prod}_outlier"] = out[f"{prod}_rate_pct"].notna() & ~out[f"{prod}_rate_pct"].between(lo, hi)
    summary[prod] = {
        "fences_pct": [round(float(lo), 2), round(float(hi), 2)],
        "reporting": int(len(reported)),
        "dropped_low": int((reported < lo).sum()), "dropped_high": int((reported > hi).sum()),
        "loans_but_no_rate": int(((out[f"{prod}_loans_usd"] > 0) & out[f"{prod}_rate_pct"].isna()).sum()),
    }
out = out.sort_values("cu_number")
out.to_csv(BENCH / f"ncua_callreport_vehicle_rates_{cycle}.csv", index=False)

# 3. National and by-state stats on the kept rates.
national, by_state, rows = {}, {}, []
for prod in ACCOUNTS:
    kept = out.loc[out[f"{prod}_rate_pct"].notna() & ~out[f"{prod}_outlier"], ["state", f"{prod}_rate_pct"]]
    national[prod] = stats(kept[f"{prod}_rate_pct"])
    for st, g in kept.groupby("state"):
        by_state.setdefault(st, {})[prod] = stats(g[f"{prod}_rate_pct"])
by_state = {st: by_state[st] for st in sorted(by_state)}
for st, v in by_state.items():
    for prod, s in v.items():
        rows.append({"state": st, "product": prod, **s})
pd.DataFrame(rows).to_csv(BENCH / f"ncua_callreport_state_stats_{cycle}.csv", index=False)

section = {
    "quarter": quarter, "as_of": as_of.isoformat(),
    "credit_unions_filed": int(len(cus)),
    "field_meanings": {
        "new": FIELD_MEANING.format(kind="new", as_of=as_of.isoformat(), line=5, acct=523),
        "used": FIELD_MEANING.format(kind="used", as_of=as_of.isoformat(), line=6, acct=524),
        "stats": "n = credit unions kept; p25, median, p75 in percent (pandas linear interpolation), one value per "
                 "credit union, unweighted. State = the credit union's mailing-address state in FOICU.txt, not "
                 "where its members live. Small n (under about 10) gives unstable percentiles.",
        "outlier_rule": f"Dropped rates more than {FENCE_IQR:g} interquartile ranges outside the national 25th-75th "
                        "percentile for that product; fences_pct shows the kept range.",
    },
    "national": {prod: {**national[prod], **summary[prod]} for prod in ACCOUNTS},
    "by_state": by_state,
}
sources = [
    {"title": f"NCUA 5300 Call Report quarterly data, {cycle}", "url": zip_url, "page": PAGE},
    {"title": "NCUA Form 5300 (Version 2025.1, effective March 31 2025), Schedule A Section 1 lines 5-6", "url": FORM},
    {"title": "NCUA Call Report instructions (effective September 30 2025), Schedule A Interest Rates",
     "url": INSTRUCTIONS},
    {"title": "Terms of use: NCUA public data inventory, checked 2026-11-15", "url": "https://ncua.gov/data.json",
     "note": "Lists 'NCUA Natural Person 5300 Call Report Data' (the quarterly-data page) under the public asset "
             "'Credit Union and Call Report Data': license https://www.usa.gov/government-works, use restriction "
             "'Unrestricted' ('Use of this dataset is not restricted'). NCUA's website policies page "
             "(https://ncua.gov/about/open-government/website-policies) states no copyright terms. Cite NCUA."},
]
write_section("ncua_callreport", section, sources)

print(f"NCUA Call Report {cycle}: {len(cus)} credit unions, rates as of {as_of} ({quarter})")
for prod in ACCOUNTS:
    n, s = national[prod], summary[prod]
    print(f"  {prod}: n={n['n']} median={n['median']}% p25={n['p25']}% p75={n['p75']}% | {s['reporting']} reported, "
          f"dropped {s['dropped_low']} low + {s['dropped_high']} high outside {s['fences_pct']}, "
          f"{s['loans_but_no_rate']} with loans but no rate")
print(f"  states/territories: {len(by_state)}")
