# Setup & Onboarding Guide

For a new engineer (hi Carlos 👋) getting this running locally, making changes, and
moving it toward production. No prior context needed.

---

## 1. What this project is (60 seconds)

It automates a warehouse's daily carton-volume reporting. Every day, 5 source
Excel reports arrive (3 by email, 2 by portal export). This system:

1. **Ingests** each source, **cleans** it with source-specific rules
   (`config/sources.yaml`), and **consolidates** into one dataset.
2. Serves a **Streamlit dashboard** with pivots, charts, freshness/threshold
   alerts, and a natural-language **Q&A** tab (Claude).

```
5 source files ──► src/transform.py (rules) ──► output/consolidated.parquet
                                                      └─► src/dashboard.py (web UI)
3 of the 5 sources are pulled from Gmail in memory (src/gmail_fetch.py);
the 2 portal sources are dropped into a folder by hand.
```

Read `CLAUDE.md` in the repo root for the full architecture and the per-source
rules — it's the source of truth.

---

## 2. Prerequisites

| Tool | Version | Check | Install (macOS) |
|------|---------|-------|-----------------|
| **Python** | 3.11+ | `python3 --version` | [python.org](https://www.python.org/downloads/) or `brew install python@3.11` |
| **pip** | (bundled) | `pip3 --version` | comes with Python |
| **git** | any | `git --version` | preinstalled on macOS, or `xcode-select --install` |

macOS is assumed (the `*.command` double-click launchers are mac-only). On
Linux/Windows everything still works — just run the `python3 …` commands directly
instead of the launchers.

---

## 3. Get the code

```bash
git clone https://github.com/kalavai-net/warehouse-carton-reporting.git
cd warehouse-carton-reporting
```

(You'll need to be a collaborator on the private repo — ask Annie/Carlos.)

---

## 4. Install dependencies

```bash
pip3 install -r requirements.txt
```

That installs: `pandas`, `openpyxl`, `xlrd` (legacy .xls), `pyyaml`, `pyarrow`
(parquet), `streamlit`, `altair`, `duckdb` (Q&A SQL), `anthropic` (Q&A).

> Tip: use a virtualenv to keep it isolated —
> `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`.

---

## 5. Two things that are NOT in the repo (and why)

By design, **code is in git; data and secrets are not**. So after cloning you must
set up two things locally:

### 5a. Secrets — `config/secrets.env`

Create this file (it's git-ignored). It holds credentials:

```bash
# config/secrets.env   (chmod 600 after creating)
export ANTHROPIC_API_KEY=sk-ant-...        # for the Q&A tab (needs an account WITH credits)
export GMAIL_ADDRESS=annie@kalavai.net     # inbox the daily reports land in
export GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx  # 16-char Google App Password (NOT the real pw)
# export SHARE_PASSWORD=some-password       # optional: gates the public shared link
```

- **App Password**: Google Account → Security → 2-Step Verification → App
  passwords. It's a scoped token, not the account password.
- The launchers `source` this file automatically. If you run Python directly,
  do `set -a; source config/secrets.env; set +a` first.
- Ask Annie for the current values, or use your own.

### 5b. The data folders — set in `config/sources.yaml` → `globals`

```yaml
globals:
  drop_folder:   "~/Desktop/Warehouse Daily Reports"      # live files land here
  sample_folder: "~/Desktop/warehouse armando final "     # pristine samples (note trailing space!)
```

- **drop_folder** — the pipeline + dashboard read this. The Gmail fetcher does NOT
  write here (email sources are processed in memory); you drop the 2 **portal**
  exports (Americhine, RDG) here by hand.
- **sample_folder** — pristine copies of the original manual workbooks, used ONLY
  by `reconcile.py` to prove the math still matches. (The path really does have a
  trailing space — leave it or rename the folder and update the config.)
- **On your machine:** change these two paths to wherever you keep the files, then
  create the folders. Ask Annie to share the sample workbooks + a set of the 5
  source files so you have something to run against.

---

## 6. Run it

### The dashboard (what people actually use)
```bash
streamlit run src/dashboard.py --server.port 8520
# macOS shortcut: double-click "Start Dashboard.command"
```
Opens `http://localhost:8520`. Click **🔄 Refresh now** to pull the 3 email reports
(in memory) + read the 2 portal files + rebuild.

### Other entry points
```bash
python3 src/gmail_fetch.py      # pull 3 email reports in memory + rebuild (needs secrets)
python3 src/pipeline.py         # rebuild from the drop folder only (no Gmail)
python3 src/transform.py --source rdg   # transform one source, for debugging
python3 src/reconcile.py        # prove computed totals == the manual sample pivots
```

### Reconciliation = the trust test
After ANY change to the transform logic, run `python3 src/reconcile.py`. Expected:
`catalyst / americhine / rdg = EXACT`, `mlg = −0.75`, `novo = −4.0` (known,
documented sample hand-edits). Anything else is a regression you introduced.

### Daily automation
Built into the dashboard: while it's running, a background thread pulls Gmail and
rebuilds once per day after 11:15 AM (catches up on wake if the Mac was asleep;
skips if a refresh already ran that day). No OS scheduler needed — and note that
launchd/cron can NOT be used here: macOS privacy protection (TCC) blocks
background agents from reading Desktop folders.

---

## 7. Project layout

```
config/sources.yaml     the transform RULES + global settings (the "brain")
src/transform.py        config-driven ingest + clean engine (reads path OR email bytes)
src/gmail_fetch.py      IMAP pull of the 3 email reports, in memory
src/pipeline.py         runs transform, writes parquet/csv + history snapshots + run log
src/reconcile.py        totals vs the manual pivots (the trust contract)
src/dashboard.py        Streamlit UI (pivots, charts, alerts, filters, Q&A)
src/qa.py               Claude + read-only DuckDB SQL for the Ask tab
*.command               macOS double-click launchers
output/  logs/          generated data + logs (git-ignored)
CLAUDE.md               full architecture + per-source rules (read this)
```

**Adding a 6th/7th source = add a block to `config/sources.yaml`. No code changes.**

---

## 8. Making changes & pushing to GitHub

Nothing syncs automatically. The loop is:

```bash
git checkout -b my-change          # work on a branch (don't commit straight to main)
# ...edit files...
python3 src/reconcile.py           # make sure you didn't break the numbers
git add -A
git commit -m "describe the change"
git push -u origin my-change       # then open a Pull Request on GitHub
```

- Before committing, double-check you're not adding data/secrets:
  `git status` should never show `*.xlsx`, `secrets.env`, `output/`, or `logs/`
  (the `.gitignore` already excludes them).
- Prefer branches + Pull Requests over pushing to `main` directly, so changes get
  reviewed.

---

## 9. Path to production (what's left)

Currently everything runs **locally on one Mac**. To productionize:

- **Always-on hosting** — the dashboard runs locally and is shared via a temporary
  Cloudflare tunnel that dies when the Mac sleeps. Move it to a persistent host
  (Streamlit Community Cloud from this repo, or a small always-on VM/container).
  Data would ship as a committed snapshot or a small managed store.
- **Scheduled ingestion off the laptop** — the daily Gmail pull uses macOS launchd.
  In production, run `gmail_fetch.py` on a scheduler on the host (cron/systemd or a
  cloud scheduler).
- **Portal sources via API** — Americhine + RDG are still manual VSR portal exports.
  A VSR API pull would remove the last manual step.
- **Access control** — no auth today beyond the optional shared-link password.
  Add real user auth if it's exposed to more people.
- **Secrets management** — move `secrets.env` values into the host's secret store
  (e.g. Streamlit secrets, or a cloud secret manager) instead of a local file.

---

## 10. Gotchas cheat-sheet

- Live email files have ONE sheet named `Sheet1`/`Sheet`; sample files have an
  `Original` tab. `read_raw` falls back to the first sheet — don't "fix" this.
- Month/Day-of-Week are always **computed from the date**, never trusted from the
  file (the samples contain typos). Disagreements are logged.
- Cartons are stored as exact decimals; rounding is display-only.
- RDG is legacy `.xls` (dates are Excel serials like 46148.0).
- `sample_folder` path has a real trailing space.
- The Q&A tab needs an Anthropic account **with credits**, or it returns a billing
  message.
