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
        # Publish to the PRIVATE data repo the hosted app reads.
        import tempfile
        data_repo = os.environ.get("DATA_REPO", "kalavai-net/warehouse-data")
        tok = os.environ.get("DATA_REPO_TOKEN") or os.environ.get("GH_TOKEN")
        url = (f"https://x-access-token:{tok}@github.com/{data_repo}.git" if tok
               else f"https://github.com/{data_repo}.git")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                subprocess.run(["git", "clone", "--depth", "1", url, tmp], check=True)
                dst = os.path.join(tmp, "data")
                os.makedirs(dst, exist_ok=True)
                for fn in ("consolidated.parquet", "source_status.json", "last_run.json"):
                    shutil.copy(os.path.join(pipeline.SNAPSHOT_DIR, fn), os.path.join(dst, fn))
                subprocess.run(["git", "-C", tmp, "add", "-A"], check=True)
                subprocess.run(["git", "-C", tmp, "-c", "user.email=publish@kalavai.net",
                                "-c", "user.name=publish", "commit", "-m",
                                "Publish data snapshot"], check=True)
                subprocess.run(["git", "-C", tmp, "push"], check=True)
            print(f"Published to {data_repo} — the hosted dashboard updates within ~10 min.")
        except subprocess.CalledProcessError:
            print(f"\nCouldn't push to {data_repo} (auth needed). Set DATA_REPO_TOKEN in "
                  "config/secrets.env, or use GitHub Desktop on the warehouse-data repo. "
                  "The snapshot is saved locally in data/.")


if __name__ == "__main__":
    publish(push="--push" in sys.argv)
