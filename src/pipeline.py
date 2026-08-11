"""
Pipeline wrapper around the transform engine.

run_pipeline():
  1. runs transform.run() over the drop folder -> normalized dataframe
  2. saves a timestamped snapshot under output/history/ (retention / season-over-
     season forecasting, per PRD non-functional reqs)
  3. writes output/consolidated.parquet + .csv as the "latest" living dataset
  4. records run metadata (row counts, totals, timestamp) to output/runs.csv

The dashboard calls this on "Refresh now"; a scheduler can call it too.
"""
from __future__ import annotations

import datetime as dt
import os

import pandas as pd

import transform as T

HISTORY_DIR = os.path.join(T.OUT_DIR, "history")
LATEST_PARQUET = os.path.join(T.OUT_DIR, "consolidated.parquet")
RUNS_LOG = os.path.join(T.OUT_DIR, "runs.csv")

# Committed snapshot the cloud reads when there's no live output/ (published by
# publish_snapshot.py: consolidated.parquet + source_status.json + last_run.json).
SNAPSHOT_DIR = os.path.join(T.ROOT, "data")
SNAPSHOT_PARQUET = os.path.join(SNAPSHOT_DIR, "consolidated.parquet")
SNAPSHOT_META = os.path.join(SNAPSHOT_DIR, "last_run.json")
SNAPSHOT_STATUS = os.path.join(SNAPSHOT_DIR, "source_status.json")


def run_pipeline(folder: str | None = None, tag: str | None = None,
                 buffers: dict | None = None, source_dates: dict | None = None,
                 upload_sources: set | None = None) -> dict:
    folder = folder or T.default_folder()  # drop folder lives in config globals
    tag = tag or dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    T.setup_logging(f"pipeline_{tag}")

    df = T.run(folder, buffers=buffers, source_dates=source_dates,
               upload_sources=upload_sources)  # writes parquet/csv/status

    os.makedirs(HISTORY_DIR, exist_ok=True)
    snap = os.path.join(HISTORY_DIR, f"snapshot_{tag}.parquet")
    df.to_parquet(snap, index=False)

    meta = {
        "run_tag": tag,
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "folder": folder,
        "rows": int(len(df)),
        "sources": int(df["source"].nunique()) if len(df) else 0,
        "rnd_customers": int(df["rnd_customer"].nunique()) if len(df) else 0,
        "total_cartons": round(float(df["cartons"].sum()), 4) if len(df) else 0.0,
        "flagged_rows": int((df["review_flag"] != "").sum()) if len(df) else 0,
        "snapshot": snap,
    }
    runs = pd.concat([_load_runs(), pd.DataFrame([meta])], ignore_index=True)
    runs.to_csv(RUNS_LOG, index=False)
    return meta


def _load_runs() -> pd.DataFrame:
    if os.path.exists(RUNS_LOG):
        return pd.read_csv(RUNS_LOG)
    return pd.DataFrame()


def load_latest() -> pd.DataFrame:
    # Prefer the live local output; fall back to the committed cloud snapshot.
    for path in (LATEST_PARQUET, SNAPSHOT_PARQUET):
        if os.path.exists(path):
            return pd.read_parquet(path)
    return pd.DataFrame(columns=T.UNIFIED_COLS)


def last_run_meta() -> dict | None:
    runs = _load_runs()
    if len(runs):
        return runs.iloc[-1].to_dict()
    if os.path.exists(SNAPSHOT_META):  # cloud snapshot
        import json
        with open(SNAPSHOT_META) as fh:
            return json.load(fh)
    return None


def status_path() -> str:
    """source_status.json to display — live output/ or the committed snapshot."""
    live = os.path.join(T.OUT_DIR, "source_status.json")
    return live if os.path.exists(live) else SNAPSHOT_STATUS


if __name__ == "__main__":
    m = run_pipeline()
    print("pipeline run:", m)
