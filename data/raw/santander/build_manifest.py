"""Assemble data/parquet/santander/manifest.json from deals.json, the parser's stats files and
facts read from the 424B5 prospectuses and the EDGAR schema zip (each noted where used)."""
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent.parent / "parquet" / "santander" / "manifest.json"
UA = ("MarkupCheck student research project (Veritas AI International High School Hackathon 2026; "
      "non-commercial student project; no automated bulk crawling)")
SPEC_URL = "https://www.sec.gov/files/absxml-31.zip"

# From the 424B5 final prospectuses (text read on Nov 14 2026) and the filing lists in data.sec.gov submissions JSON.
FACTS = {
    "santander_2024-1": {
        "pool_other": ("0000950131-24-000006", "sdart241ex102_0105-1932sp.xml"),
        "prospectus_url": "https://www.sec.gov/Archives/edgar/data/2004812/000119312524008591/d605182d424b5.htm",
        "prospectus_loan_count_if_found": 76569,
        "prospectus_check": (
            "424B5 (0001193125-24-008591, filed 2024-01-16) gives a count only for the STATISTICAL pool as of "
            "2023-12-17: 76,569 receivables, $1,731,789,556.86. It says the final pool differs and gives the "
            "final cut-off (2023-12-31) pool only as 'aggregate initial principal balance of $1,609,643,527'. "
            "The lp file has 70,947 loans whose reportingPeriodActualEndBalanceAmount sums to $1,609,643,527.83, "
            "so the file matches the final pool by balance; the 76,569 vs 70,947 gap (7.3%) is the statistical "
            "pool vs final pool difference, not a parsing loss. The final-pool loan count is not stated in the "
            "424B5 (couldnt_confirm)."),
    },
    "santander_2025-1": {
        "pool_other": ("0000950131-25-000026", "sdart251ex102_0108-1618sp.xml"),
        "prospectus_url": "https://www.sec.gov/Archives/edgar/data/2049903/000119312525008465/d833872d424b5.htm",
        "prospectus_loan_count_if_found": 99060,
        "prospectus_check": (
            "424B5 (0001193125-25-008465, filed 2025-01-17) 'Composition of the Pool of Receivables as of the "
            "Cut-off Date': 99,060 receivables (25,413 new, 73,647 used), $2,248,757,111.37. The lp file has "
            "99,060 rows (25,413 new, 73,647 used) and its reportingPeriodActualEndBalanceAmount sums to "
            "$2,248,757,111.37: exact match."),
    },
    "santander_2026-1": {
        "pool_other": ("0001193125-26-045529", "sdart261ex102_0210-1822sp.xml"),
        "prospectus_url": "https://www.sec.gov/Archives/edgar/data/2105961/000119312526061442/d23657d424b5.htm",
        "prospectus_loan_count_if_found": 86349,
        "prospectus_check": (
            "424B5 (0001193125-26-061442, filed 2026-02-20) 'Composition of the Pool of Receivables as of the "
            "Cut-off Date': 86,349 receivables (19,810 new, 66,539 used), $1,936,166,715.66. The lp file has "
            "86,349 rows (19,810 new, 66,539 used) and its reportingPeriodActualEndBalanceAmount sums to "
            "$1,936,166,715.66: exact match."),
    },
}
HEAD = {
    "santander_2024-1": ("0000950131-24-000008", "0001193125-24-004382", "2024-01-08", "2024-01-16"),
    "santander_2025-1": ("0000950131-25-000028", "0001193125-25-004311", "2025-01-10", "2025-01-17"),
    "santander_2026-1": ("0001193125-26-045549", "0001193125-26-046579", "2026-02-11", "2026-02-20"),
}
CODE_MEANINGS = {  # verbatim from eis_ABS_AutoLoanAssetData.xsd inside SPEC_URL
    "subvented": "0: No, 1: Yes - Rate Subvention, 2: Yes - Cash Rebate, 98: Yes - Other (element may repeat; "
                 "repeated values are stored comma-joined in document order, e.g. '1,98')",
    "new_used_code": "1: New, 2: Used",
    "interest_rate_type_code": "1: Fixed, 2: Adjustable, 98: Other",
    "vehicle_type_code": "1: Car, 2: Truck, 3: SUV, 4: Motorcycle, 98: Other, 99: Unknown",
    "vehicle_value_source_code": "1: Invoice Price, 2: MSRP, 3: Kelly Blue Book, 98: Other",
    "income_verification_code": "1: Not stated, not verified, 2: Stated, not verified, 3: Stated, verified but not "
                                "to level 4 or level 5, 4: Stated, level 4 verified (W-2/tax return + pay stubs), "
                                "5: Stated, level 5 verified (24 months of documents)",
    "employment_verification_code": "1: Not stated, not verified, 2: Stated, not verified, 3: Stated, level 3 "
                                    "verified (direct independent third-party verification)",
    "credit_score_type": "free text in the filing (obligorCreditScoreType); every Santander row says 'Bureau'",
}


def main():
    deals_cfg = json.loads((HERE / "deals.json").read_text())
    deals, merged = [], {}
    for slug in ("santander_2024-1", "santander_2025-1", "santander_2026-1"):
        cfg, st = deals_cfg[slug], json.loads((HERE / f"stats_{slug}.json").read_text())
        sp_cfg = deals_cfg["sp_" + slug]
        sp_st = json.loads((HERE / f"stats_sp_{slug}.json").read_text())
        fa, fa_head = FACTS[slug], HEAD[slug]
        sp_acc, sp_file = fa["pool_other"]
        deals.append({
            "deal": cfg["deal"], "deal_cik": cfg["deal_cik"], "filing_date": cfg["filing_date"],
            "accession": cfg["accession"], "source_url": cfg["source_url"],
            "why_this_is_the_first_pool_filing": (
                f"EDGAR lists two ABS-EE filings for this trust on {cfg['filing_date']} and none earlier: the "
                f"'sp' (small pool) {sp_acc} and the 'lp' (large pool) {cfg['accession']}. Both describe the pool as "
                f"of the cut-off date, are filed under the trust's own CIK, come with the preliminary prospectus "
                f"(424H {fa_head[1]}, {fa_head[2]}) and before the final 424B5 ({fa_head[3]}); the trust's monthly "
                f"ABS-EE filings come later. I used the lp file because it is the one that matches the final "
                f"prospectus pool (see prospectus_check); the sp file is a strict subset of it "
                f"({sp_st['rows_written']:,} of the lp file's loans, all asset numbers also in lp)."),
            "bytes": st["xml_bytes"], "rows_parsed": st["rows_parsed"], "rows_written": st["rows_written"],
            "duplicate_asset_numbers_dropped": st["duplicate_asset_numbers_dropped"],
            "origination_month_min": st["origination_month_min"], "origination_month_max": st["origination_month_max"],
            "prospectus_loan_count_if_found": fa["prospectus_loan_count_if_found"],
            "prospectus_check": fa["prospectus_check"], "prospectus_url": fa["prospectus_url"],
            "credit_score_values_set_to_nan_as_out_of_range": st["credit_score_out_of_range_300_850"],
            "parquet_file": f"{slug}.parquet",
            "alternative_file_not_used": {
                "which": "sp (small pool)", "accession": sp_acc, "source_url": sp_cfg["source_url"],
                "bytes": sp_st["xml_bytes"], "rows_parsed": sp_st["rows_parsed"],
                "note": "strict subset of the lp file; does not match the prospectus pool; parsed only to compare"},
        })
        for k, v in st["code_values_seen"].items():
            merged.setdefault(k, Counter()).update(v)
    score_note = "; ".join(
        f"{d['deal'].split()[-1]}: {d['credit_score_values_set_to_nan_as_out_of_range']}" for d in deals)
    manifest = {
        "issuer": "santander",
        "user_agent": UA,
        "deals": deals,
        "code_values_seen": {k: dict(v) for k, v in merged.items()},
        "code_meanings_from_spec": CODE_MEANINGS,
        "spec_url": SPEC_URL,
        "notes": [
            "Only 'Santander Drive Auto Receivables Trust' (SDART) deals; the separate 'Drive Auto Receivables Trust' shelf is not used. Sponsor/servicer: Santander Consumer USA Inc.",
            "SDART 2026-1 (filed 2026-02-11) is the newest SDART deal in EDGAR on 2026-11-14; no 2026-2 or later exists in the search index or the depositor's filing list.",
            "The plain User-Agent from CLAUDE.md ('MarkupCheck student research project') got HTTP 403 'Undeclared Automated Tool' from www.sec.gov on 2026-11-14. With the team's go-ahead to declare a project contact, requests used the longer project-declaring User-Agent in 'user_agent' (no email in it); it returned HTTP 200. data.sec.gov and efts.sec.gov accepted the plain one.",
            "These are SEASONED pools, not new originations: each pool was assembled from loans originated over many years (see origination_month_min/max per deal: 2017-03..2023-12, 2018-06..2024-12, 2019-11..2026-01). About 72% (2024-1), 71% (2025-1) and 78% (2026-1) of loans were originated in the last 12 months of each deal's range; the rest is a long tail back to 2017-2020 (for example 21% of 2024-1 and 16% of 2025-1 are from 2019 and 2020). The main session should filter on origination_month.",
            "Exact 0.00% APRs exist: 412 rows (2024-1), 457 (2025-1) and 2,369 (2026-1), almost all subvented='1' or '1,98' on new vehicles (0% manufacturer promotions); the prospectuses state the contract-rate range as 0.00% to 29.99%. They are real, so they were kept (CONTRACT says not to filter); the main session decides whether to exclude them. validate.py therefore checks apr_pct in [0, 40] and reports the zero-rate rows separately instead of failing the brief's strict (0, 40] test.",
            "All three pools are Santander Consumer subprime/near-subprime paper (weighted-average rate about 18%). apr_pct values above 25% are real subprime pricing and were kept; prospectus ranges of contract rate are 0.00%-29.99%.",
            "`subvented` may appear more than once per loan (XSD maxOccurs=unbounded). Repeated values are kept comma-joined in document order ('1,98'); 2026-1 also has 96 rows written '0,1' (contradictory as filed, kept as written).",
            "APR sanity check: balance-weighted originalInterestRatePercentage x100 over the whole file is 18.5954% (2024-1), 18.1929% (2025-1) and 18.3750% (2026-1); the prospectuses state weighted-average contract rates of 18.52% (statistical pool, 2024-1), 18.06% and 18.25%. The x100 conversion is right; the 0.07-0.13 point gap is unexplained (the prospectus may define 'contract rate' or its weights slightly differently).",
            "credit_score: kept as written. Santander writes obligorCreditScore = 0 for loans with no score (13-17% of loans) and some values of 851-900 (FICO Auto scale, as at CarMax and Ally). src/mc.py clean() keeps 250-900 for every lender, so 0 (no score) is dropped there. Earlier versions of this parser set both to NaN, which dropped only Santander's 851-900 scores; that was changed on Nov 14 2026 so all lenders are cleaned by one rule.",
            "Stretch file perf_santander_2024-1.parquet (SDART 2024-1, 12 monthly EX-102 files, reporting periods 2024-01..2024-12, 779,160 rows, built by perf_santander.py): in the 2024-07 file 42,421 of 65,453 loans have no currentDelinquencyStatus (field absent in the filing), so current_delinquency_status is null for those rows; the other 11 months have it for every loan. Treat 2024-07 delinquency as missing, not zero.",
            "No exact-duplicate asset numbers were found in any file (duplicate_asset_numbers_dropped = 0 for all three).",
            "Raw XML (the three lp files) stays in data/raw/santander/; the small-pool XML files were deleted after comparison and can be re-downloaded from alternative_file_not_used.source_url.",
        ],
        "couldnt_confirm": [
            "Final-pool loan count of SDART 2024-1: the 424B5 only states the statistical-pool count (76,569 at 2023-12-17). I matched the file to the final pool by aggregate balance ($1,609,643,527.83 vs the prospectus's $1,609,643,527) instead. Looked in: 424B5 d605182d424b5.htm (pool composition tables and 'Statistical Information' section).",
            "What 'sp' and 'lp' stand for: the cover pages (sdart241absee_0105-1250lp.htm) don't say. I inferred small pool / large pool from the file names and checked the relation (sp is a strict subset of lp, lp matches the prospectus pool) from the data.",
            "Why the prospectus weighted-average contract rate differs from the file's balance-weighted originalInterestRatePercentage by 0.07-0.13 points (see notes).",
            "Credit scores: obligorCreditScoreType is 'Bureau' on every row, but the filings do not say which bureau model (FICO vs VantageScore) each score is; the prospectus tables speak of FICO scores. Looked in: EX-102 XML and the XSD documentation.",
        ],
    }
    OUT.write_text(json.dumps(manifest, indent=2))
    print("wrote", OUT, OUT.stat().st_size, "bytes")
    for d in deals:
        print(d["deal"], d["rows_written"], d["origination_month_min"], d["origination_month_max"], d["prospectus_loan_count_if_found"])


if __name__ == "__main__":
    main()
