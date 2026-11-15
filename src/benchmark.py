"""Build the monthly 5-year Treasury yield benchmark from the US Treasury's daily par yield curve CSVs.

The model's target is APR minus this benchmark for the loan's origination month, so that market-wide
rate moves between 2019 and 2026 don't look like price differences between borrowers.
Run: .venv/bin/python src/benchmark.py
"""
import io
import pathlib

import pandas as pd
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "benchmark" / "treasury_5y_monthly.csv"
URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
       "{y}/all?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")
UA = {"User-Agent": "MarkupCheck student research project"}


def main(first_year: int = 2015, last_year: int = 2026) -> pd.DataFrame:
    frames = []
    for y in range(first_year, last_year + 1):
        url = URL.format(y=y)
        r = requests.get(url, headers=UA, timeout=60)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        if "5 Yr" not in df.columns:
            raise ValueError(f"{y}: no '5 Yr' column; columns were {list(df.columns)}")
        df = df[["Date", "5 Yr"]].dropna()
        df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y")
        df["source_url"] = url
        frames.append(df)
        print(f"{y}: {len(df)} daily rows")
    daily = pd.concat(frames, ignore_index=True)
    daily["month"] = daily["Date"].dt.strftime("%Y-%m")
    monthly = (daily.groupby("month")
               .agg(five_year_pct=("5 Yr", "mean"), n_days=("5 Yr", "size"), source_url=("source_url", "first"))
               .reset_index())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(OUT, index=False)
    print(f"wrote {OUT} with {len(monthly)} months, {monthly.month.min()} to {monthly.month.max()}")
    return monthly


if __name__ == "__main__":
    main()
