"""
Daily cloud refresh — run by the GitHub Action (.github/workflows/daily-refresh.yml),
NOT on Annie's Mac.

Pulls the 3 email reports (Catalyst/MLG/Novo) live from Gmail, merges them with the
last Americhine/RDG portal snapshot already in `data/`, and rewrites the data/
snapshot the hosted dashboard reads. Then the Action commits + pushes it, and
Streamlit Cloud redeploys automatically.

Email sources refresh every day on their own. Portal sources (Americhine/RDG) can't
be pulled from the cloud yet (no VSR API), so they stay at whatever Annie last
published from her Mac — until the VSR API lands.

Needs GMAIL_ADDRESS + GMAIL_APP_PASSWORD in the environment (GitHub Actions secrets).
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

PORTAL = {"americhine", "rdg"}


def main() -> None:
    config = T.load_config()["sources"]

    # Last snapshot — source of the portal rows (and a fallback for email).
    if os.path.exists(pipeline.SNAPSHOT_PARQUET):
        snap = pd.read_parquet(pipeline.SNAPSHOT_PARQUET)
    else:
        snap = pd.DataFrame(columns=T.UNIFIED_COLS)
    old_status = {}
    if os.path.exists(pipeline.SNAPSHOT_STATUS):
        with open(pipeline.SNAPSHOT_STATUS) as fh:
            old_status = json.load(fh)

    # Pull the email reports live and transform them in memory.
    buffers, missing, dates = gmail_fetch.fetch_bytes()
    frames, status = [], {}
    for src, data in buffers.items():
        cfg = config[src]
        frames.append(T.transform_source(T.read_raw(data, cfg, label=src), cfg, src))
        ts = dates.get(src) or dt.datetime.now()
        status[src] = {"display": cfg.get("display_name", src), "origin": "Gmail (auto)",
                       "last_updated": ts.replace(microsecond=0).isoformat()}

    # Email sources we couldn't fetch today: keep yesterday's rows + status.
    for src, cfg in config.items():
        if cfg.get("email") and src not in buffers:
            frames.append(snap[snap["source"] == src])
            if src in old_status:
                status[src] = old_status[src]

    # Portal rows + status come from the last snapshot unchanged.
    frames.append(snap[snap["source"].isin(PORTAL)])
    for src in PORTAL:
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
    }
    with open(pipeline.SNAPSHOT_META, "w") as fh:
        json.dump(meta, fh, indent=2, default=str)

    print(f"cloud refresh: {len(combined)} rows | email pulled: {list(buffers)} | "
          f"missing: {missing} | total cartons: {meta['total_cartons']:,.0f}")


if __name__ == "__main__":
    main()
