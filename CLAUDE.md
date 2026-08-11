# Warehouse Outboard Reporting Automation — agent guide

Automates Armando's carton-volume reporting (PRD: "Americhine Volume Reporting
Automation"). 5 sources (→7) arrive daily by email/VSR portal export; this
system cleans each with source-specific rules, consolidates to one dataset, and
serves a dashboard + natural-language Q&A. Owner: Annie Wang (non-technical —
keep everything click-to-run).

## Folders (IMPORTANT — two separate folders)

- **Production drop folder** = `globals.drop_folder` (`~/Desktop/Warehouse Daily
  Reports`). Live daily files land here: the Gmail fetcher writes Catalyst/MLG/Novo;
  you drop Americhine/RDG portal exports here. The pipeline + dashboard read this.
- **Sample folder** = `globals.sample_folder` (`~/Desktop/warehouse armando final `,
  trailing space real). Pristine manual workbooks with the pivot/notes tabs.
  `reconcile.py` reads ONLY this so live data can never disturb the trust contract.
  Don't write live files here (a fetch-cleanup bug once deleted the Novo sample;
  that's why the folders are now separated and cleanup is date-stamped).

Live delivered files have ONE sheet named `Sheet1`/`Sheet` (not `Original` like the
samples) — `read_raw` falls back to the first sheet when the configured one is absent.
Live exports may also add/drop the preamble rows the samples had (2026-07-20: the new
"RDG- Open Order Detail.xls" export has headers on row 0, not row 3) — `read_raw`
auto-detects the header row by scanning for the driving-date column when the
configured `header_row` doesn't contain it.

## Data flow

```
production drop folder (config globals.drop_folder)
  └─ src/transform.py    per-source rules from config/sources.yaml
       └─ output/consolidated.parquet (+.csv)   ← the living dataset
            ├─ src/pipeline.py   snapshots → output/history/, run log → output/runs.csv
            ├─ src/dashboard.py  Streamlit UI (launched by "Start Dashboard.command")
            └─ src/qa.py         Claude + read-only DuckDB SQL tool (needs ANTHROPIC_API_KEY)
src/reconcile.py  proves computed totals == manual pivot totals (logs/reconciliation.md)
```

## Unified schema (one row per cleaned order line)

`source, rnd_customer, end_customer, driving_date, month, day_of_week, cartons,
units, cancel_date, review_flag`

- **rnd_customer** = master grouping (Catalyst, MLG, Novo, RDG; the Americhine
  file splits into 3 via its `Company` column: AMERICHINE LLC / Indochine /
  RND International). **end_customer** = the retailer (Walmart, Target, Kohls…).
  Don't conflate them — "customer" in the PRD means rnd_customer.
  UI TERMINOLOGY: the dashboard shows rnd_customer to the user as **"Client"**
  (see `CLIENT_LABEL`/`DISPLAY_RENAME` in dashboard.py; qa.py answers say "client").
  The column name stays `rnd_customer` in the data/parquet/SQL — only the label changed.
- month/day_of_week are ALWAYS computed from driving_date (typed months in
  source files contain human typos — formula wins; disagreements are logged to
  logs/month_corrections.csv).
- cartons stored as exact decimals; round only at display. No min-1-carton
  floor; <1 or missing values get a `review_flag` and land in
  logs/carton_review.csv.

## Per-source rules (verified against the manual sample pivots)

| Source | file_glob | Header row | Driving date | Carton rule |
|---|---|---|---|---|
| catalyst | Catalyst*.xlsx | 0 | PO Due Date | Original Quantity ÷ 12 (ignore native Carton Count) |
| mlg | MLG*.xlsx | 5 (4 preamble rows) | Start Date | CTN; if 0 → Pick Qty ÷ 12 |
| novo | Novo*.xlsx | 0 | Ship Date | native `# of Cartons`; if 0 → Pick Qty ÷ 12 **rounded UP (ceil)** |
| americhine | Americhine*.xlsx | 0 | Start Date | native first `Cartons`; if 0 → Open Balance ÷ 30 (NOT the PRD's "All Open ÷ 9" — that was wrong, 37× too high). Ignore col BK (2nd Cartons). |
| rdg | RDG*.xls (legacy!) | 3 (title block) | Start Date | All Open ÷ 9; preclean: drop rows where `Cust. No.` is a date |

Gotchas: RDG is .xls (xlrd; dates are Excel serials like 46148.0). MLG headers
contain newlines ("Pick\nQty") — transform normalizes whitespace. Americhine has
TWO `Cartons` columns; pandas dedupes the 2nd to `Cartons.1` and we use the first.

**Adding source 6/7 = add a block to config/sources.yaml. No code changes.**

## Reconciliation status (the trust contract)

Run `python3 src/reconcile.py` after ANY transform change. Expected:
catalyst / novo / americhine / rdg = EXACT; mlg = −0.75 (one documented human
hand-edit in the sample — see logs/study_log.md). Any other delta is a regression.
(Novo became EXACT on 2026-07-21 when its 0-carton rule started rounding up.)

## Required dashboard outputs (PRD section 10 + Annie's screenshot)

- 10.1 living pivot: cartons by rnd_customer × month (+ totals) AND the
  **calendar pivot**: rows = rnd_customer › end_customer hierarchy, columns =
  month › date › day-of-week — this mirrors the Excel "Calendar Pivot" tabs.
- 10.2 per-customer: by month; by month broken down by end customer; month ×
  day-of-week heatmap.
- 10.3 master: total by customer; by customer × month.
- 10.4 Q&A (Ask tab): claude-opus-4-8 + guarded SELECT-only DuckDB tool.
- Sidebar filters: source, rnd_customer, end_customer, year, month, date range.
  Year + date range only NARROW when changed from full defaults (so no-date rows
  aren't silently dropped at defaults). driving_date is normalized to midnight, so
  the date-range between() is inclusive of the end day. All filters feed `f`, which
  drives every chart, pivot, KPI, and the CRITICAL threshold banner.
- Per-source freshness panel at top ("When each source was last updated"): reads
  output/source_status.json (written by T.run) — Gmail sources show the email
  date, portal sources show the file mtime; ⚠️ if older than 2 days.
- CRITICAL volume banner near top: `volume_breaches(f, limits)` flags any
  day/week/month whose TOTAL cartons exceed the thresholds. Respects the sidebar
  FILTERS (aggregates over `f`, the filtered view; banner shows scope "selection"
  vs "all sources") and uses ADJUSTABLE limits — sidebar "Critical volume
  thresholds" number inputs (Daily/Weekly/Monthly) default to `globals.thresholds`
  (12k/65k/320k) but Armando can change them live. Green "no breaches" note when
  clear. Red st.error summary + expandable full list. Week = Mon–Sun. Sidebar
  filters are defined BEFORE the banner so it can respect them.

## How to run

- Dashboard: double-click "Start Dashboard.command" (port 8520) or
  `streamlit run src/dashboard.py`. Refresh button re-runs the pipeline.
- Pipeline only: `python3 src/pipeline.py`
- One source: `python3 src/transform.py --source rdg`
- Gmail fetch (manual): `python3 src/gmail_fetch.py` or double-click
  `fetch_and_refresh.command`. Daily auto: BUILT INTO THE DASHBOARD — a daemon
  thread (`_start_daily_auto_refresh` in dashboard.py) runs the fetch once per
  day after 11:15 while the dashboard is open; catches up on wake if the Mac
  slept. Do NOT use launchd for this: macOS TCC blocks background agents from
  reading Desktop folders (exit 78, empty logs) — that's why the old
  `Install Daily Email Schedule.command`/plist were removed 2026-07-20.
- Q&A reads `ANTHROPIC_API_KEY` from `config/secrets.env` (git-ignored, chmod 600);
  the launcher sources it. Key must be on an account WITH credits (a valid key on
  an empty account returns a billing 400 — qa.py surfaces a friendly message).
  Never commit secrets.env or echo the key.

## Decisions log (locked with Annie 2026-06-11 — don't re-litigate silently)

1. Keep BOTH rnd_customer and end_customer.
2. Month/DoW computed from date; log every disagreement with typed values.
3. Cartons exact decimals, round on display only.
4. No carton floor; flag <1 / missing for review instead.

## Gmail auto-ingestion (BUILT — src/gmail_fetch.py)

catalyst/mlg/novo are forwarded daily by Armando to annie@kalavai.net. The
fetcher logs into Gmail over IMAP, matches each report by SUBJECT, and pulls the
.xlsx attachment straight **into memory** (bytes) — the raw email files are NEVER
written to the laptop (Annie's request). It then rebuilds the consolidated dataset:
email sources from the in-memory bytes, portal sources (americhine/rdg) from the
drop folder. Only output/consolidated.parquet(+csv)+history snapshots persist.

Plumbing: `gmail_fetch.fetch_bytes()` → `{source: bytes}`; `read_raw()` accepts a
path OR bytes; `T.run(folder, buffers=...)` reads email sources from buffers,
portal from folder; `pipeline.run_pipeline(buffers=...)` threads it through. With
`buffers` given, an email source NOT fetched is skipped (no stale disk fallback).
If Gmail is unreachable, the last good consolidated.parquet is kept (not wiped).

- Subject match + normalized name live in `config/sources.yaml` under each
  source's `email:` block. The actual attachment names do NOT match the source
  (Catalyst's file is `RNDINBOUNDTRACKING.*.xlsx`; MLG's is `RND Open picks…`)
  — that's why we match on subject and rename on save.
- Auth: `GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD` in config/secrets.env (App
  Password, not the real password; git-ignored, chmod 600).
- Cleanup is non-destructive: only removes prior auto-fetched files (its own
  naming), never the sample workbooks. reconcile.py is pinned to the exact
  SAMPLE_FILES, so live fetched files in the folder can't change its numbers.
- Manual upload fallback (dashboard "📤 Upload a report manually" expander, for
  Armando when Annie is away): per-source drag-drop uploaders. Each upload
  REPLACES that source (override, never appended → no duplicates); un-uploaded
  sources still come from Gmail/folder. `gmail_fetch.rebuild_with_uploads()`:
  portal uploads are saved into the drop folder (persist, newest wins, nothing
  deleted); email uploads are a one-off in-memory override (labeled "Manual
  upload" in the freshness panel via `upload_sources`). Gmail is still pulled for
  un-uploaded email sources.
- Triggers: dashboard single "🔄 Refresh now" button (in-memory Gmail pull +
  portal folder + rebuild) AND a launchd job at 11:15 AM local
  (`Install Daily Email Schedule.command` installs
  `config/com.warehouse.gmailfetch.plist`; runs `fetch_and_refresh.command` →
  `gmail_fetch.py` → `fetch_and_run`). There is no separate folder-only rebuild
  button anymore (email data isn't on disk, so a folder-only rebuild would drop it).
- americhine/rdg have NO `email:` block — still manual VSR portal export into the
  drop folder.

## Not built yet

- VSR API pull for americhine/rdg (today: manual portal export into the folder).
- Always-on hosting: dashboard runs locally; the cloudflared quick-tunnel share
  dies when the Mac sleeps. Permanent host (Streamlit Cloud) not set up.
- Role-based access (PRD section 5) — everything is local right now.

## History / context

`logs/study_log.md` = full reverse-engineering record + reconciliation results.
Sample workbooks with the manual process: `~/Desktop/warehouse armando final /`
(folder name has a trailing space). Claude memory also keeps project context in
`~/.claude/projects/-Users-anniewang-Desktop-warehouse-raw-documents/memory/`.
