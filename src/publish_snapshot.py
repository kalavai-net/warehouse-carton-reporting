"""
Publish the current local dataset as the cloud snapshot.

The Streamlit Cloud dashboard is always-on but can't see your Mac. It reads a
committed snapshot in `data/`. This copies your latest local dataset there so the
hosted dashboard shows current numbers.

Workflow when you want to update Armando's hosted view:
  1. Refresh locally (dashboard "Refresh now", or `python3 src/gmail_fetch.py`)
  2. `python3 src/publish_snapshot.py --push`   (or double-click "Publish to Cloud.command")

Only the aggregated dataset is published (parquet + status + run meta) — never the
raw source files.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline  # noqa: E402
import transform as T  # noqa: E402


def publish(push: bool = False) -> None:
    if not os.path.exists(pipeline.LATEST_PARQUET):
        print("No local dataset yet — run a refresh first.")
        sys.exit(1)
    os.makedirs(pipeline.SNAPSHOT_DIR, exist_ok=True)

    shutil.copy(pipeline.LATEST_PARQUET, pipeline.SNAPSHOT_PARQUET)
    live_status = os.path.join(T.OUT_DIR, "source_status.json")
    if os.path.exists(live_status):
        shutil.copy(live_status, pipeline.SNAPSHOT_STATUS)
    meta = pipeline.last_run_meta()
    if meta:
        with open(pipeline.SNAPSHOT_META, "w") as fh:
            json.dump(meta, fh, indent=2, default=str)
    print(f"Snapshot written to {pipeline.SNAPSHOT_DIR} "
          f"({int(meta['rows']) if meta else '?'} rows).")

    if push:
        try:
            subprocess.run(["git", "add", "data/"], cwd=T.ROOT, check=True)
            subprocess.run(["git", "commit", "-m", "Publish data snapshot for cloud dashboard"],
                           cwd=T.ROOT, check=True)
            subprocess.run(["git", "push"], cwd=T.ROOT, check=True)
            print("Pushed to GitHub — the hosted dashboard will update shortly.")
        except subprocess.CalledProcessError:
            print("\nCouldn't push automatically (git auth not set up). The snapshot "
                  "is saved + committed locally — push it via GitHub Desktop to update "
                  "the hosted dashboard.")


if __name__ == "__main__":
    publish(push="--push" in sys.argv)
