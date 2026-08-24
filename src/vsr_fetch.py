"""
VSR (Americhine) API fetcher.

Pulls AMERICHINE LLC inbound orders from the VSR API and returns them as
normalized rows (the unified schema). The API returns the carton value already
computed, so NO carton rule is applied here — we use its `cartons` field as-is.
Month/day-of-week are still recomputed from the start date (our locked rule).

Indochine + RND are NOT on this API; they come from the uploaded combined file
(source `indochine_rnd`, filtered to those two companies).

Needs VSR_API_KEY in the environment (config/secrets.env locally; GitHub Actions
and Streamlit secrets in the cloud).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import ssl
import sys
import urllib.parse
import urllib.request

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import transform as T  # noqa: E402

API_URL = "https://vsr2.americhine.com/rest/icg-api/inbound-orders"
LOOKBACK_DAYS = 60      # include recently-past-dated open orders
WINDOW_DAYS = 365       # 365-day window (API max is 366)
COMPANY = "AMERICHINE LLC"


class VSRError(Exception):
    pass


def _get(params: dict, key: str) -> dict:
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context()) as r:
        return json.loads(r.read())


def fetch_americhine() -> tuple[pd.DataFrame, dict]:
    """Return (normalized_df for source 'americhine', status dict)."""
    key = os.environ.get("VSR_API_KEY", "").strip()
    if not key:
        raise VSRError("VSR_API_KEY not set (config/secrets.env or app secrets).")

    today = dt.date.today()
    start = (today - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
    end = (today - dt.timedelta(days=LOOKBACK_DAYS) + dt.timedelta(days=WINDOW_DAYS)).isoformat()

    rows: list = []
    page, page_size = 1, 1000
    while True:
        resp = _get({"startDate": start, "endDate": end,
                     "page": page, "pageSize": page_size}, key)
        data = resp.get("data") or []
        rows.extend(data)
        total_pages = int(resp.get("meta", {}).get("totalPages", 1) or 1)
        if page >= total_pages or not data:
            break
        page += 1

    status = {"display": "Americhine (API)", "origin": "VSR API (auto)",
              "last_updated": dt.datetime.now().replace(microsecond=0).isoformat()}
    if not rows:
        return pd.DataFrame(columns=T.UNIFIED_COLS), status

    raw = pd.DataFrame(rows)
    # Safety: keep only AMERICHINE LLC (Indochine/RND come from the uploaded file).
    raw = raw[raw["company"].astype(str).str.strip() == COMPANY]
    drive = pd.to_datetime(raw["startDate"], errors="coerce")
    cartons = pd.to_numeric(raw["cartons"], errors="coerce")
    out = pd.DataFrame({
        "source": "americhine",
        "rnd_customer": raw["company"].astype(str).str.strip().values,
        "end_customer": raw["customerName"].astype(str).str.strip().values,
        "driving_date": drive.dt.normalize().values,
        "month": drive.dt.strftime("%B").fillna("(blank)").values,
        "day_of_week": drive.dt.strftime("%A").fillna("(blank)").values,
        "cartons": cartons.values,           # API pre-computes cartons — use as-is
        "units": pd.NA,
        "cancel_date": pd.NaT,
        "review_flag": "",
    })
    out.loc[out["cartons"] < 1, "review_flag"] = "review:sub1_carton"
    out.loc[out["cartons"].isna(), "review_flag"] = "review:missing_carton"
    return out[T.UNIFIED_COLS], status


if __name__ == "__main__":
    if os.path.exists(os.path.join(T.ROOT, "config", "secrets.env")):
        for line in open(os.path.join(T.ROOT, "config", "secrets.env")):
            if line.startswith("export ") and "=" in line:
                k, v = line[len("export "):].strip().split("=", 1)
                os.environ.setdefault(k, v)
    df, st = fetch_americhine()
    print(f"VSR Americhine: {len(df)} rows, {df['cartons'].sum():,.0f} cartons, "
          f"{df['end_customer'].nunique()} end customers")
