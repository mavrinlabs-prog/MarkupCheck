# CONTRACT — file formats and folder ownership

Every session follows this exactly, so the pieces fit without anyone re-reading another session's code.

## Folder ownership (write only in your own)

| Owner | Folders |
|---|---|
| Data session — CarMax | `data/raw/carmax/`, `data/parquet/carmax/`, `TASKS_carmax.md` |
| Data session — Ally | `data/raw/ally/`, `data/parquet/ally/`, `TASKS_ally.md` |
| Data session — Santander | `data/raw/santander/`, `data/parquet/santander/`, `TASKS_santander.md` |
| App session | `app/` except `app/markupcheck_model.py` and `app/model/`; `TASKS_app.md` |
| Main session | everything else: `data/benchmark/`, `notebooks/`, `reports/`, `app/markupcheck_model.py`, `app/model/`, `README.md`, `RESULTS.md`, `LEARN.md`, `VIDEO_SCRIPT.md`, `TASKS.md` |

All four sessions finished on Nov 14 (~10:35 ET); from then on the main session owns every folder, including `app/`.

## Data sessions: one Parquet file per deal

Path: `data/parquet/<issuer>/<deal_slug>.parquet` (e.g. `carmax_2026-1.parquet`). One row per loan, taken from the deal's **first pool filing** (the ABS-EE filed with or before the prospectus, describing the pool as of the cutoff date — not a later monthly file, because monthly files have already lost loans that paid off or defaulted).

| Column | Type | Meaning / source field |
|---|---|---|
| issuer | string | `carmax`, `ally`, `santander`, `toyota`, `honda`, `hyundai`, `nissan`, `ford`, `gmf` or `capone` |
| deal | string | Full trust name, e.g. "CarMax Auto Owner Trust 2026-1" |
| deal_cik | string | Trust CIK, 10 digits zero-padded |
| source_url | string | URL of the EX-102 XML the row came from |
| filing_date | string | ABS-EE filing date, YYYY-MM-DD |
| asset_number | string | assetNumber |
| origination_month | string | originationDate converted to YYYY-MM |
| original_loan_amount | float | originalLoanAmount, dollars |
| original_term_months | int | originalLoanTerm |
| apr_pct | float | originalInterestRatePercentage × 100 (file stores 0.0874 for 8.74%) |
| interest_rate_type_code | string | originalInterestRateTypeCode as written |
| subvented | string | subvented as written (codes per the EX-102 spec) |
| vehicle_make | string | vehicleManufacturerName |
| vehicle_model | string | vehicleModelName |
| new_used_code | string | vehicleNewUsedCode as written |
| vehicle_model_year | int | vehicleModelYear |
| vehicle_type_code | string | vehicleTypeCode as written |
| vehicle_value | float | vehicleValueAmount, dollars |
| vehicle_value_source_code | string | vehicleValueSourceCode as written |
| credit_score_type | string | obligorCreditScoreType as written |
| credit_score | float | obligorCreditScore (NaN if missing or non-numeric) |
| income_verification_code | string | obligorIncomeVerificationLevelCode |
| employment_verification_code | string | obligorEmploymentVerificationCode |
| co_obligor | boolean | coObligorIndicator |
| pti_pct | float | paymentToIncomePercentage × 100 (NaN if missing) |
| state | string | obligorGeographicLocation |

Keep codes "as written" (strings) — the main session maps them using the spec. Don't filter rows except exact duplicate asset numbers within one file; the main session applies all filters so every drop is counted in one place.

Also write `data/parquet/<issuer>/manifest.json`:
```json
{"issuer": "...", "user_agent": "MarkupCheck student research project",
 "deals": [{"deal": "...", "deal_cik": "...", "filing_date": "...", "accession": "...", "source_url": "...",
            "why_this_is_the_first_pool_filing": "...", "bytes": 0, "rows_parsed": 0, "rows_written": 0,
            "duplicate_asset_numbers_dropped": 0, "origination_month_min": "YYYY-MM", "origination_month_max": "YYYY-MM",
            "prospectus_loan_count_if_found": null}],
 "code_values_seen": {"subvented": {}, "new_used_code": {}, "credit_score_type": {}},
 "spec_url": "...", "notes": ["..."], "couldnt_confirm": ["..."]}
```

Stretch only (after the required files are done): `data/parquet/<issuer>/perf_<deal_slug>.parquet` for ONE deal — columns asset_number, reporting_period_end (YYYY-MM), current_delinquency_status, chargedoff_principal_amount, zero_balance_code, repossessed — from that deal's monthly EX-102 files (at most 12 months). Delete each downloaded monthly XML after parsing it; keep only the Parquet.

## Model interface for the app

`app/markupcheck_model.py` exposes `predict(offer: dict) -> dict`. Until the real model exists it is a stub that returns `"stub": True`.

Input `offer` keys: `credit_score` (int 250–900; lenders report FICO Auto scores, which run 250–900), `new_or_used` ("new" or "used"), `vehicle_model_year` (int), `vehicle_price` (float), `amount_financed` (float), `term_months` (int), `offered_apr_pct` (float, e.g. 15.9), `lender` (string or None).

Output keys: `stub` (bool), `view` (string: "whole market", or "same lender: <name>" when the buyer named Ally, CarMax or Santander — the main fields then compare with that lender's own similar loans), `market` (None, or when the same-lender view is used a dict with the whole-market `typical_pct`, `range_low_pct`, `range_high_pct`, `percentile`, `flag`), `range_low_pct`, `range_high_pct`, `typical_pct` (floats, APR %), `percentile` (0–100: share of similar loans with a lower APR than the offer), `flag` ("typical", "high" or "likely marked up"), `monthly_payment_offer`, `monthly_payment_typical`, `extra_cost_usd` (total over the term; negative means the offer is cheaper than typical — show it as a saving), `reasons` (list of 1–3 plain-language strings), `same_lender` (None, or a dict with `lender`, `typical_pct`, `difference_pts` (same-lender typical minus whole-market typical) and `n_loans`), `weak_spots` (list of strings for "What the data can't tell you"), `data_note` (string: which data and months the benchmark uses). When `app/model/extras.json` exists (written by `src/build_extras.py`) the result also has: `lenders` (one dict per lender in the data: `key`, `lender`, `yours`, `n_loans`, `typical_pct`, `range_low_pct`, `range_high_pct`, `percentile`, `flag`), `checks` (what-if dicts: `name`, `question`, the same five numbers and flag, and `same_flag`), `evidence` (`n_similar`, `n_loans`, `rare`), `risk` (`months`, `rows` of `lender`, `yours`, `bad_rate_high`, `bad_rate_other`) and `credit_union` (NCUA's closest product: `new_or_used`, `term_months`, `credit_union_pct`, `bank_pct`, `rate_date`, `source_url`). Without that file these keys are None and the app shows the original weak-spots list. Every real result also has `data_months` (`newest_loans` and `rate_benchmark`, both "YYYY-MM"), and, when their files exist in `app/model/`: `rule_of_thumb` (the B1 credit-tier rule for this offer: `tier`, `new_or_used`, `typical_pct`, `range_low_pct`, `range_high_pct`, `test`; from `rule_of_thumb.json`), `fresh_rates` (credit unions' posted rates from NCUA's Call Report: `new_or_used`, `as_of`, `n`, `median_pct`, `p25_pct`, `p75_pct`, and for new cars `g19`, the Federal Reserve's bank and finance-company rates; from `rates_extra.json`) and `forward_test` (the newer-loans test: `lender`, `loans`, `months`, `model_mae`, `rule_mae`, `coverage_pct`, `below_pct`; from `forward_summary.json`); otherwise they are None. Every real result also has `quantiles` (the 19 (probability, APR) points of the predicted distribution), `waterfall` (`start_pct` for a typical loan in the data, `end_pct`, and `steps` of (label, change in points)) and `whatif` (a grid of typical APR, range and flag over credit scores, terms and extra down payments, for the page's sliders). `predict(offer, detail=False)` skips the per-lender table, the checks and the grid (about 20 ms instead of 120 ms), for batch checks.
