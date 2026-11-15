"""Assemble data/parquet/ally/manifest.json from deals.json (facts found by hand) and stats_<slug>.json (printed by build_ally.py)."""
import collections
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

cfg = json.load(open(os.path.join(HERE, "manifest_facts.json")))
deals_out, merged = [], collections.defaultdict(lambda: collections.Counter())
by_deal = {}
for d in cfg["deals"]:
    s = json.load(open(os.path.join(HERE, f"stats_{d['slug']}.json")))
    deals_out.append({
        "deal": d["deal"], "deal_cik": d["deal_cik"], "filing_date": d["filing_date"],
        "accession": d["accession"], "source_url": d["source_url"],
        "why_this_is_the_first_pool_filing": d["why"],
        "bytes": s["bytes"], "rows_parsed": s["rows_parsed"], "rows_written": s["rows_written"],
        "duplicate_asset_numbers_dropped": s["duplicate_asset_numbers_dropped"],
        "origination_month_min": s["origination_month_min"], "origination_month_max": s["origination_month_max"],
        "prospectus_loan_count_if_found": d.get("prospectus_loan_count"),
        "prospectus_loan_count_source": d.get("prospectus_loan_count_source"),
        "parquet_file": s["parquet_file"],
    })
    by_deal[d["deal"]] = s["code_values_seen"]
    for col, counts in s["code_values_seen"].items():
        merged[col].update(counts)

manifest = {
    "issuer": "ally",
    "user_agent": cfg["user_agent"],
    "deals": deals_out,
    "code_values_seen": {c: dict(merged[c]) for c in ("subvented", "new_used_code", "credit_score_type")},
    "code_values_seen_by_deal": by_deal,
    "spec_url": cfg["spec_url"],
    "notes": cfg["notes"],
    "couldnt_confirm": cfg["couldnt_confirm"],
}
out = os.path.join(ROOT, "data", "parquet", "ally", "manifest.json")
json.dump(manifest, open(out, "w"), indent=1)
print("wrote", out)
