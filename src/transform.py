"""
Config-driven transform engine for the Warehouse Outboard Reporting pipeline.

Reads each source's RAW export, applies the source-specific rules defined in
config/sources.yaml, and emits ONE normalized table with the unified schema:

    source, rnd_customer, end_customer, driving_date, month, day_of_week,
    cartons, units, cancel_date

Design rules (locked with Annie 2026-06-11):
  * Month / Day-of-Week are ALWAYS computed from the driving date.
  * Cartons stored as exact decimals (rounding happens only at display time).
  * Both rnd_customer (master grouping) and end_customer (drill-down) are kept.

Everything of note is written to logs/ so we can see what worked and what didn't.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import io
import json
import logging
import os
import sys

import pandas as pd
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "sources.yaml")
LOG_DIR = os.path.join(ROOT, "logs")
OUT_DIR = os.path.join(ROOT, "output")

UNIFIED_COLS = [
    "source", "rnd_customer", "end_customer", "driving_date",
    "month", "day_of_week", "cartons", "units", "cancel_date", "review_flag",
]

# Excel's day-0 epoch (the 1900 leap-year bug means day 0 = 1899-12-30).
EXCEL_EPOCH = dt.datetime(1899, 12, 30)

log = logging.getLogger("transform")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def setup_logging(run_tag: str) -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    logfile = os.path.join(LOG_DIR, f"transform_run_{run_tag}.log")
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(logfile)]
    # force=True: without it, basicConfig is a no-op after the first call, so a
    # long-lived process (the dashboard) would log every later run to the FIRST
    # run's file.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=handlers,
        force=True,
    )
    log.info("Logging to %s", logfile)


def load_config() -> dict:
    with open(CONFIG_PATH) as fh:
        return yaml.safe_load(fh)


def default_folder() -> str:
    """The PRODUCTION drop folder for live source files (config globals)."""
    folder = load_config().get("globals", {}).get("drop_folder", "")
    return os.path.expanduser(folder)


def sample_folder() -> str:
    """The pristine SAMPLE folder used by reconcile (config globals)."""
    g = load_config().get("globals", {})
    return os.path.expanduser(g.get("sample_folder", g.get("drop_folder", "")))


def normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse newlines / repeated whitespace in column names (MLG has 'Pick\\nQty')."""
    df = df.copy()
    df.columns = [
        " ".join(str(c).split()).strip() if c is not None else c
        for c in df.columns
    ]
    return df


def to_date(val):
    """Robustly coerce a cell to a date: handles datetime, Excel serials, and strings."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return pd.NaT
    if isinstance(val, (dt.datetime, dt.date, pd.Timestamp)):
        ts = pd.Timestamp(val)
        return ts.normalize() if not pd.isna(ts) else pd.NaT
    if isinstance(val, (int, float)):
        # Excel serial date (RDG .xls stores dates as e.g. 46148.0).
        if 20000 < float(val) < 80000:
            return pd.Timestamp(EXCEL_EPOCH + dt.timedelta(days=float(val)))
        return pd.NaT
    s = str(val).strip()
    if not s:
        return pd.NaT
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return pd.Timestamp(dt.datetime.strptime(s, fmt)).normalize()
        except ValueError:
            continue
    parsed = pd.to_datetime(s, errors="coerce")
    return pd.Timestamp(parsed).normalize() if not pd.isna(parsed) else pd.NaT


def is_date_like(val) -> bool:
    """Used by RDG preclean: True if a 'Cust. No.' cell is actually a date value.

    Real customer numbers are codes like 'HSN001'. We only treat a cell as a date
    when it is a datetime, an Excel date serial, or a slash/dash-formatted date
    string -- never a plain numeric customer id.
    """
    if isinstance(val, (dt.datetime, dt.date, pd.Timestamp)):
        return True
    if isinstance(val, (int, float)) and not pd.isna(val) and 20000 < float(val) < 80000:
        return True
    s = str(val).strip()
    if ("/" in s or "-" in s) and not pd.isna(to_date(s)):
        return True
    return False


# --------------------------------------------------------------------------- #
# core transform
# --------------------------------------------------------------------------- #
def read_raw(src, cfg: dict, label: str | None = None) -> pd.DataFrame:
    """Read a source workbook. `src` may be a file PATH or in-memory bytes
    (the Gmail fetcher passes attachment bytes so nothing is written to disk)."""
    sheet = cfg.get("sheet", 0)
    header_row = cfg.get("header_row", 0)
    engine = "xlrd" if cfg.get("file_format") == "xls" else "openpyxl"
    if isinstance(src, (str, os.PathLike)):
        handle, name = src, os.path.basename(str(src))
    elif isinstance(src, (bytes, bytearray)):
        handle, name = io.BytesIO(src), (label or "<in-memory>")
    else:
        handle, name = src, (label or "<in-memory>")
    xls = pd.ExcelFile(handle, engine=engine)
    # The live email/portal files have ONE data sheet (named 'Sheet1'/'Sheet'),
    # while the sample workbooks have an 'Original' tab among several. If the
    # configured sheet name isn't present, fall back to the first sheet.
    if isinstance(sheet, str) and sheet not in xls.sheet_names:
        log.info("  sheet '%s' not in %s; using first sheet '%s'",
                 sheet, name, xls.sheet_names[0])
        sheet = 0
    df = pd.read_excel(xls, sheet_name=sheet, header=header_row, dtype=object)
    df = normalize_headers(df)
    log.info("  read %d rows x %d cols from %s [%s]", len(df), df.shape[1], name, sheet)
    return df


def derive_cartons(df: pd.DataFrame, cfg: dict, source: str) -> pd.Series:
    c = cfg["carton"]
    method = c["method"]
    if method == "divide":
        qty = pd.to_numeric(df[c["qty_col"]], errors="coerce")
        return qty / c["divisor"]
    if method == "column":
        return pd.to_numeric(df[c["carton_col"]], errors="coerce")
    if method == "column_with_fallback":
        cart = pd.to_numeric(df[c["carton_col"]], errors="coerce")
        fb_col = c.get("fallback_col", c.get("qty_col"))
        fb_qty = pd.to_numeric(df[fb_col], errors="coerce")
        fallback = fb_qty / c["fallback_divisor"]
        n_fb = int((cart.fillna(0) == 0).sum())
        log.info("  [%s] carton fallback (%s==0 -> %s/%s) applied to %d rows",
                 source, c["carton_col"], fb_col, c["fallback_divisor"], n_fb)
        return cart.where(cart.fillna(0) != 0, fallback)
    raise ValueError(f"unknown carton method: {method}")


def transform_source(df: pd.DataFrame, cfg: dict, source: str,
                     corrections: list | None = None) -> pd.DataFrame:
    df = df.copy()

    # ---- preclean ------------------------------------------------------- #
    for rule in cfg.get("preclean", []):
        if "drop_rows_where_date" in rule:
            col = rule["drop_rows_where_date"]
            mask = df[col].apply(is_date_like)
            dropped = int(mask.sum())
            if dropped:
                log.info("  [%s] preclean: dropped %d rows where '%s' is a date",
                         source, dropped, col)
            df = df[~mask]

    # ---- driving date + month/dow (always computed) --------------------- #
    drive = df[cfg["driving_date_col"]].apply(to_date)

    # Drop only genuinely empty / total rows (no customer). Rows that have a
    # customer but no date are KEPT -- they belong to the pivot's "(blank)"
    # month, and their cartons still count toward the grand total.
    end_col = cfg["end_customer_col"]
    keep = df[end_col].notna() & ~df[end_col].astype(str).str.strip().isin(["", "nan", "None"])
    n_drop = int((~keep).sum())
    if n_drop:
        log.info("  [%s] dropped %d empty/total rows (no customer)", source, n_drop)
    df, drive = df[keep], drive[keep]

    # Month/DoW blank where the driving date is missing (mirrors pivot "(blank)").
    month = drive.dt.strftime("%B").fillna("(blank)")
    dow = drive.dt.strftime("%A").fillna("(blank)")

    # ---- month-correction check (reconciliation only) ------------------- #
    # Raw feeds carry no typed month, but the human-cleaned sample tabs do.
    if "Month" in df.columns and corrections is not None:
        typed = df["Month"].astype(str).str.strip()
        mism = typed.notna() & (typed != "") & (typed.str.lower() != month.str.lower())
        for idx in df.index[mism]:
            corrections.append({
                "source": source,
                "driving_date": drive.loc[idx].date().isoformat(),
                "typed_month": str(df.loc[idx, "Month"]).strip(),
                "computed_month": month.loc[idx],
            })

    # ---- rnd_customer (static label OR dynamic column) ------------------ #
    if cfg.get("rnd_customer_col"):
        rnd = df[cfg["rnd_customer_col"]].astype(str).str.strip()
    else:
        rnd = pd.Series(cfg["rnd_customer"], index=df.index)

    # ---- units (where available) ---------------------------------------- #
    cc = cfg["carton"]
    units_col = cc.get("qty_col")
    units = pd.to_numeric(df[units_col], errors="coerce") if units_col in df.columns else pd.NA

    cancel_col = cfg.get("cancel_date_col")
    cancel = df[cancel_col].apply(to_date) if cancel_col and cancel_col in df.columns else pd.NaT

    cartons = derive_cartons(df, cfg, source)

    # Flag rows for human spot-check (Annie Q4: keep computed values, surface them):
    #   sub1_carton    — line computes to <1 carton (manual sample sometimes typed "1")
    #   missing_carton — carton source cell was blank/non-numeric (contributes 0)
    review = pd.Series("", index=df.index)
    sub1 = cartons < 1
    review[sub1] = "review:sub1_carton"
    missing = cartons.isna()
    review[missing] = "review:missing_carton"
    if int(sub1.sum()):
        log.info("  [%s] flagged %d sub-1 carton rows for review", source, int(sub1.sum()))
    if int(missing.sum()):
        log.warning("  [%s] flagged %d rows with MISSING carton value (count as 0)",
                    source, int(missing.sum()))

    out = pd.DataFrame({
        "source": source,
        "rnd_customer": rnd.values,
        "end_customer": df[end_col].astype(str).str.strip().values,
        "driving_date": drive.values,
        "month": month.values,
        "day_of_week": dow.values,
        "cartons": cartons.values,
        "units": units.values if hasattr(units, "values") else units,
        "cancel_date": cancel.values if hasattr(cancel, "values") else cancel,
        "review_flag": review.values,
    })
    log.info("  [%s] -> %d normalized rows, %.3f total cartons",
             source, len(out), out["cartons"].sum())
    return out[UNIFIED_COLS]


def find_file(folder: str, cfg: dict) -> str | None:
    """Newest file matching the source's glob — by modification time, not name.

    Lexicographic sort would mis-pick when downloads are renamed, e.g.
    'RDG-Open Order Report (2).xls' sorts before 'RDG-Open Order Report.xls'
    even though it is the newer download.
    """
    matches = glob.glob(os.path.join(folder, cfg["file_glob"]))
    return max(matches, key=os.path.getmtime) if matches else None


def run(folder: str, only: str | None = None, buffers: dict | None = None,
        source_dates: dict | None = None) -> pd.DataFrame:
    """Build the consolidated dataset.

    buffers: optional {source_key: bytes} of in-memory workbooks (e.g. Gmail
    attachments). When given, email sources are read from memory (nothing
    written to disk) and any email source NOT supplied is skipped; portal
    sources (americhine/rdg) are still read from `folder`. When buffers is None,
    every source is read from `folder` (used by reconcile and folder rebuilds).
    """
    config = load_config()
    corrections: list = []
    frames = []
    status: dict = {}  # per-source "last updated" provenance for the dashboard
    for source, cfg in config["sources"].items():
        if only and source != only:
            continue
        disp = cfg.get("display_name", source)
        buf = (buffers or {}).get(source)
        if buf is not None:
            log.info("processing source: %s (from email, in-memory)", source)
            raw = read_raw(buf, cfg, label=f"{source} email attachment")
            ts = (source_dates or {}).get(source) or dt.datetime.now()
            status[source] = {"display": disp, "origin": "Gmail",
                              "last_updated": ts.replace(microsecond=0).isoformat()}
        else:
            if buffers is not None and cfg.get("email"):
                log.warning("[%s] email report not provided this run; skipping", source)
                continue
            path = find_file(folder, cfg)
            if not path:
                log.warning("[%s] no file matching '%s' in %s", source, cfg["file_glob"], folder)
                continue
            log.info("processing source: %s", source)
            raw = read_raw(path, cfg)
            mt = dt.datetime.fromtimestamp(os.path.getmtime(path))
            origin = "Folder (portal export)" if cfg.get("delivery") == "portal" else "Folder"
            status[source] = {"display": disp, "origin": origin,
                              "last_updated": mt.replace(microsecond=0).isoformat()}
        frames.append(transform_source(raw, cfg, source, corrections))

    if not frames:
        log.error("no sources produced output")
        return pd.DataFrame(columns=UNIFIED_COLS)

    consolidated = pd.concat(frames, ignore_index=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "consolidated.parquet")
    consolidated.to_parquet(out_path, index=False)
    csv_path = os.path.join(OUT_DIR, "consolidated.csv")
    consolidated.to_csv(csv_path, index=False)
    log.info("wrote %d rows -> %s (+ .csv)", len(consolidated), out_path)

    # Per-source "last updated" for the dashboard header.
    with open(os.path.join(OUT_DIR, "source_status.json"), "w") as fh:
        json.dump(status, fh, indent=2)

    if corrections:
        cdf = pd.DataFrame(corrections)
        cpath = os.path.join(LOG_DIR, "month_corrections.csv")
        cdf.to_csv(cpath, index=False)
        log.warning("MONTH CORRECTIONS: %d rows where the source's typed month "
                    "disagreed with the computed month -> %s", len(cdf), cpath)

    review = consolidated[consolidated["review_flag"] != ""]
    if len(review):
        rpath = os.path.join(LOG_DIR, "carton_review.csv")
        review.to_csv(rpath, index=False)
        log.warning("CARTON REVIEW: %d rows flagged for spot-check "
                    "(sub-1 or missing carton; values kept as computed) -> %s",
                    len(review), rpath)
    return consolidated


def main() -> None:
    ap = argparse.ArgumentParser(description="Warehouse transform engine")
    ap.add_argument("--folder", default=None,
                    help="folder of dropped source files (default: globals.drop_folder in config)")
    ap.add_argument("--source", default=None, help="run a single source key only")
    args = ap.parse_args()
    folder = args.folder or default_folder()

    run_tag = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    setup_logging(run_tag)
    log.info("transform run %s | folder=%s", run_tag, folder)
    df = run(folder, only=args.source)
    log.info("DONE. %d total rows, %.2f total cartons across %d sources",
             len(df), df["cartons"].sum(), df["source"].nunique())


if __name__ == "__main__":
    main()
