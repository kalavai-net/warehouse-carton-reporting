# Warehouse Outboard — Carton Volume Reporting

Automates the daily manual process: ingest 5 source exports → apply each source's
cleaning rules → one consolidated carton dataset → web dashboard with pivot, charts,
and natural-language Q&A.

> **New here / setting up on a fresh machine?** Read **[SETUP.md](SETUP.md)** — a
> step-by-step install, run, dependencies, and "path to production" guide.

## How to use it (no terminal needed)

1. Drop the latest source files into the **drop folder**
   (currently `~/Desktop/warehouse armando final/` — one file per source, names
   matching the patterns in `config/sources.yaml`).
2. Double-click **`Start Dashboard.command`**. Your browser opens the dashboard.
3. Click **🔄 Refresh now** to re-run everything on the newest files.
4. Close the Terminal window when done.

## What the dashboard shows

- **Master charts** — total cartons by RND customer; cartons by customer × month; the living pivot; and the **calendar pivot** (each RND customer with its end retailers underneath, one column per ship/start date — mirrors the Excel "Calendar Pivot" tab).
- **Per-customer** — a customer's cartons by month, cartons by month broken down by retailer, a month × day-of-week calendar heatmap, and an end-customer table.
- **Filters** (sidebar) — source, RND customer, end customer (retailer), month. They drive every chart and pivot.
- **Ask (Q&A)** — ask questions in plain English (e.g. *"How many cartons is RDG sending in August by week?"*) and get an answer + chart. Powered by Claude over the consolidated data.
- **Data quality** — sub-1 carton rows flagged for spot-check; any month corrections.
- **Raw data** — the full consolidated table, downloadable as CSV.

### Enabling the Q&A tab

The Ask tab needs an Anthropic API key. It lives in **`config/secrets.env`** (a
local, git-ignored file) as one line:

```
export ANTHROPIC_API_KEY=sk-ant-...
```

**Start Dashboard.command** loads it automatically — just relaunch after editing.
The Ask tab uses Claude to translate your question into a safe, read-only query
over the data, runs it, and answers. (Without a key, every other tab still works.)

> The key must belong to an Anthropic account **with credits**. A valid key on an
> empty account returns a billing error (the dashboard shows a plain-English note).
> Add credits at console.anthropic.com → Plans & Billing.

## The 5 sources & rules

See `logs/study_log.md` for the full reverse-engineered spec and
`logs/reconciliation.md` for proof the numbers match the manual reports
(Catalyst, Americhine, RDG match exactly; MLG/Novo differ only by a few
hand-typed cells in the sample).

Adding source 6 or 7 = add a block to `config/sources.yaml`. No code changes.

## Project layout

```
config/sources.yaml     transform rules (the "instructions" the system follows)
src/transform.py        config-driven ingestion + transform engine
src/pipeline.py         runs transform, saves snapshots + history
src/reconcile.py        checks computed totals against the manual pivots
src/dashboard.py        the web dashboard (Streamlit)
output/                 consolidated.csv/.parquet + history snapshots
logs/                   study log, reconciliation, run logs, review files
```

## Requirements

Python 3.11+. Install dependencies once: `pip install -r requirements.txt`.
