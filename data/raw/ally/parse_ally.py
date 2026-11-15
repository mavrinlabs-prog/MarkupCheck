"""Parse an Ally EX-102 (Reg AB II auto-loan asset data) XML file into the CONTRACT Parquet columns.

Streams with lxml.etree.iterparse so a 150-300 MB file never sits in memory.
Library use:  parse_pool(xml_path, meta) -> (DataFrame, stats)
              parse_perf(xml_path, period_end) -> DataFrame
"""
import collections
import re

import numpy as np
import pandas as pd
import pyarrow as pa
from lxml import etree

NS = "http://www.sec.gov/edgar/document/absee/autoloan/assetdata"
ASSET_TAG = f"{{{NS}}}assets"

SCHEMA = pa.schema([
    ("issuer", pa.string()), ("deal", pa.string()), ("deal_cik", pa.string()),
    ("source_url", pa.string()), ("filing_date", pa.string()), ("asset_number", pa.string()),
    ("origination_month", pa.string()), ("original_loan_amount", pa.float64()),
    ("original_term_months", pa.int64()), ("apr_pct", pa.float64()),
    ("interest_rate_type_code", pa.string()), ("subvented", pa.string()),
    ("vehicle_make", pa.string()), ("vehicle_model", pa.string()), ("new_used_code", pa.string()),
    ("vehicle_model_year", pa.int64()), ("vehicle_type_code", pa.string()),
    ("vehicle_value", pa.float64()), ("vehicle_value_source_code", pa.string()),
    ("credit_score_type", pa.string()), ("credit_score", pa.float64()),
    ("income_verification_code", pa.string()), ("employment_verification_code", pa.string()),
    ("co_obligor", pa.bool_()), ("pti_pct", pa.float64()), ("state", pa.string()),
])

PERF_SCHEMA = pa.schema([
    ("asset_number", pa.string()), ("reporting_period_end", pa.string()),
    ("current_delinquency_status", pa.int64()), ("chargedoff_principal_amount", pa.float64()),
    ("zero_balance_code", pa.string()), ("repossessed", pa.bool_()),
])

# CONTRACT column -> EX-102 element name (string columns kept exactly as written)
STR_FIELDS = {
    "asset_number": "assetNumber",
    "interest_rate_type_code": "originalInterestRateTypeCode",
    "subvented": "subvented",
    "vehicle_make": "vehicleManufacturerName",
    "vehicle_model": "vehicleModelName",
    "new_used_code": "vehicleNewUsedCode",
    "vehicle_type_code": "vehicleTypeCode",
    "vehicle_value_source_code": "vehicleValueSourceCode",
    "credit_score_type": "obligorCreditScoreType",
    "income_verification_code": "obligorIncomeVerificationLevelCode",
    "employment_verification_code": "obligorEmploymentVerificationCode",
    "state": "obligorGeographicLocation",
}
CODE_COLUMNS_FOR_MANIFEST = ["subvented", "new_used_code", "credit_score_type"]
ORIG_RE = re.compile(r"^\s*(\d{1,2})/(\d{4})\s*$")


def _text(rec, name):
    v = rec.get(name)
    if v is None:
        return None
    v = v.strip()
    return v if v != "" else None


def _num(rec, name):
    v = _text(rec, name)
    if v is None:
        return np.nan
    try:
        return float(v)
    except ValueError:
        return np.nan


def _bool(rec, name):
    v = _text(rec, name)
    if v is None:
        return None
    v = v.lower()
    if v in ("true", "1", "y", "yes"):
        return True
    if v in ("false", "0", "n", "no"):
        return False
    return None


def _orig_month(rec):
    v = _text(rec, "originationDate")
    if v is None:
        return None
    m = ORIG_RE.match(v)
    if not m or not 1 <= int(m.group(1)) <= 12:
        return None
    return f"{m.group(2)}-{int(m.group(1)):02d}"


def iter_assets(xml_path):
    """Yield one {localname: text} dict per <assets> element, freeing memory as it goes."""
    for _, elem in etree.iterparse(xml_path, events=("end",), tag=ASSET_TAG, huge_tree=True):
        yield {etree.QName(c).localname: c.text for c in elem if isinstance(c.tag, str)}
        elem.clear()
        while elem.getprevious() is not None:
            del elem.getparent()[0]


def parse_pool(xml_path, meta):
    """meta needs: issuer, deal, deal_cik, source_url, filing_date."""
    rows, tags_seen = [], collections.Counter()
    unparsed_orig = 0
    parsed = 0
    for rec in iter_assets(xml_path):
        parsed += 1
        if parsed == 1:
            tags_seen.update(rec.keys())
        om = _orig_month(rec)
        if om is None:
            unparsed_orig += 1
        apr = _num(rec, "originalInterestRatePercentage")
        pti = _num(rec, "paymentToIncomePercentage")
        row = {
            "issuer": meta["issuer"], "deal": meta["deal"], "deal_cik": meta["deal_cik"],
            "source_url": meta["source_url"], "filing_date": meta["filing_date"],
            "origination_month": om,
            "original_loan_amount": _num(rec, "originalLoanAmount"),
            "original_term_months": _num(rec, "originalLoanTerm"),
            "apr_pct": round(apr * 100, 6) if not np.isnan(apr) else np.nan,
            "vehicle_model_year": _num(rec, "vehicleModelYear"),
            "vehicle_value": _num(rec, "vehicleValueAmount"),
            "credit_score": _num(rec, "obligorCreditScore"),
            "co_obligor": _bool(rec, "coObligorIndicator"),
            "pti_pct": round(pti * 100, 6) if not np.isnan(pti) else np.nan,
        }
        for col, tag in STR_FIELDS.items():
            row[col] = _text(rec, tag)
        rows.append(row)

    df = pd.DataFrame(rows)
    rows_parsed = len(df)
    dups = int(df["asset_number"].duplicated().sum())
    df = df.drop_duplicates(subset="asset_number", keep="first").reset_index(drop=True)

    for col in ("original_term_months", "vehicle_model_year"):
        df[col] = df[col].astype("Int64")
    df["co_obligor"] = df["co_obligor"].astype("boolean")
    df = df[[f.name for f in SCHEMA]]

    codes = {c: {str(k): int(v) for k, v in df[c].fillna("<missing>").value_counts().items()}
             for c in CODE_COLUMNS_FOR_MANIFEST}
    stats = {
        "rows_parsed": rows_parsed, "rows_written": len(df),
        "duplicate_asset_numbers_dropped": dups,
        "origination_month_min": df["origination_month"].min(),
        "origination_month_max": df["origination_month"].max(),
        "origination_month_unparsed": unparsed_orig,
        "code_values_seen": codes,
        "first_record_tags": sorted(tags_seen),
    }
    return df, stats


def write_parquet(df, path):
    pa_table = pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False)
    import pyarrow.parquet as pq
    pq.write_table(pa_table, path, compression="zstd")


def _period_end(rec):
    """reportingPeriodEndingDate is MM-DD-YYYY; return YYYY-MM or None."""
    m = re.match(r"^\s*(\d{2})-\d{2}-(\d{4})\s*$", rec.get("reportingPeriodEndingDate") or "")
    return f"{m.group(2)}-{m.group(1)}" if m else None


def parse_perf(xml_path):
    """Stretch: monthly performance columns from one monthly EX-102 file.

    current_delinquency_status is the spec's integer (days past due, Item 3(f)(25)); zero_balance_code is
    kept as a string (1 Prepaid or Matured, 2 Third-party Sale, 3 Repurchased or Replaced, 4 Charged-off,
    5 Servicing Transfer, 99 Unavailable); repossessed is the repossessedIndicator boolean.
    """
    rows = []
    for rec in iter_assets(xml_path):
        rows.append({
            "asset_number": _text(rec, "assetNumber"),
            "reporting_period_end": _period_end(rec),
            "current_delinquency_status": _num(rec, "currentDelinquencyStatus"),
            "chargedoff_principal_amount": _num(rec, "chargedoffPrincipalAmount"),
            "zero_balance_code": _text(rec, "zeroBalanceCode"),
            "repossessed": _bool(rec, "repossessedIndicator"),
        })
    df = pd.DataFrame(rows)
    df["current_delinquency_status"] = df["current_delinquency_status"].astype("Int64")
    df["repossessed"] = df["repossessed"].astype("boolean")
    return df
