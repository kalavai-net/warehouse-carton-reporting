"""
Cloud refresh — used two ways:
  * the daily GitHub Action (.github/workflows/daily-refresh.yml) calls main()
  * the hosted dashboard's "Refresh now" / upload buttons call build()

It pulls the 3 email reports (Catalyst/MLG/Novo) live from Gmail, keeps the last
Americhine/RDG portal rows from the committed snapshot (or uses uploaded files),
and rewrites the data/ snapshot the hosted dashboard reads. No local drop folder
needed — everything is in memory or the snapshot.

Portal sources (Americhine/RDG) can't be pulled from the cloud yet (no VSR API),
so they stay at the last published/uploaded values.

Needs GMAIL_ADDRESS + GMAIL_APP_PASSWORD in the environment (GitHub Actions secrets,
or the Streamlit app's secrets).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import transform as T  # noqa: E402
import pipeline  # noqa: E402
import gmail_fetch  # noqa: E402


def build(uploads: dict | None = None) -> dict:
    """Rebuild the data/ snapshot from Gmail (email) + snapshot/uploads (portal).
    `uploads` = optional {source_key: file_bytes} that override any source.
    Returns the run meta."""
    uploads = uploads or {}
    config = T.load_config()["sources"]

    if os.path.exists(pipeline.SNAPSHOT_PARQUET):
        snap = pd.read_parquet(pipeline.SNAPSHOT_PARQUET)
    else:
        snap = pd.DataFrame(columns=T.UNIFIED_COLS)
    old_status = {}
    if os.path.exists(pipeline.SNAPSHOT_STATUS):
        with open(pipeline.SNAPSHOT_STATUS) as fh:
            old_status = json.load(fh)

    # Pull the email reports live (best effort — uploads can stand in if it fails).
    buffers, missing, dates = {}, [], {}
    try:
        buffers, missing, dates = gmail_fetch.fetch_bytes()
    except gmail_fetch.GmailFetchError:
        pass

    frames, status = [], {}
    for src, cfg in config.items():
        disp = cfg.get("display_name", src)
        data = uploads.get(src) or buffers.get(src)
        if data is not None:
            frames.append(T.transform_source(T.read_raw(data, cfg, label=src), cfg, src))
            if src in uploads:
                status[src] = {"display": disp, "origin": "Manual upload",
                               "last_updated": dt.datetime.now().replace(microsecond=0).isoformat()}
            else:
                ts = dates.get(src) or dt.datetime.now()
                status[src] = {"display": disp, "origin": "Gmail (auto)",
                               "last_updated": ts.replace(microsecond=0).isoformat()}
        else:
            # Not fetched/uploaded — keep this source's rows from the last snapshot.
            frames.append(snap[snap["source"] == src])
            if src in old_status:
                status[src] = old_status[src]

    combined = pd.concat([f for f in frames if len(f)], ignore_index=True)

    os.makedirs(pipeline.SNAPSHOT_DIR, exist_ok=True)
    combined.to_parquet(pipeline.SNAPSHOT_PARQUET, index=False)
    with open(pipeline.SNAPSHOT_STATUS, "w") as fh:
        json.dump(status, fh, indent=2)
    meta = {
        "run_tag": dt.datetime.now().strftime("%Y%m%d_%H%M%S"),
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "rows": int(len(combined)),
        "sources": int(combined["source"].nunique()) if len(combined) else 0,
        "rnd_customers": int(combined["rnd_customer"].nunique()) if len(combined) else 0,
        "total_cartons": round(float(pd.to_numeric(combined["cartons"], errors="coerce").sum()), 4),
        "fetched": list(buffers), "uploaded": list(uploads), "missing": missing,
    }
    with open(pipeline.SNAPSHOT_META, "w") as fh:
        json.dump(meta, fh, indent=2, default=str)
    return meta


def main() -> None:
    meta = build()
    print(f"cloud refresh: {meta['rows']} rows | email pulled: {meta['fetched']} | "
          f"missing: {meta['missing']} | total cartons: {meta['total_cartons']:,.0f}")


if __name__ == "__main__":
    main()
