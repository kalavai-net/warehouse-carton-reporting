# Deploy the dashboard always-on (Streamlit Community Cloud)

Goal: a permanent link Armando can use **even when Annie's Mac is off**. Free.

**How it works:** the cloud dashboard displays a **snapshot** of the data committed
to this repo (`data/`). Annie refreshes locally and publishes a new snapshot; the
hosted dashboard updates. The cloud app is view-only (no local Gmail/folder there),
so the Refresh/Upload buttons are automatically hidden when hosted.

---

## One-time setup (≈10 minutes — Annie does this)

### 1. Make sure the code + a snapshot are on GitHub
Already handled if `data/consolidated.parquet` is in the repo. (To refresh it later,
see "Updating the data" below.)

### 2. Create a Streamlit Community Cloud account
- Go to **https://share.streamlit.io** → **Sign in with GitHub** (use your
  `anniewang436-cmd` account) → authorize.

### 3. Let Streamlit see the private org repo
- During sign-in (or at github.com/settings/applications), grant Streamlit access
  to the **`kalavai-net`** organization. If it's blocked, **Carlos** (org owner)
  approves the "Streamlit" app at
  `github.com/organizations/kalavai-net/settings/oauth_application_policy`.

### 4. Create the app
- Click **"Create app"** → **"Deploy a public app from GitHub"** (private repos are
  fine on the free tier).
- **Repository:** `kalavai-net/warehouse-carton-reporting`
- **Branch:** `main`
- **Main file path:** `src/dashboard.py`

### 5. Add secrets (Advanced settings → Secrets)
Paste this (TOML format), filling in your values:
```toml
ANTHROPIC_API_KEY = "sk-ant-..."      # only needed for the Ask (Q&A) tab
# Optional (only if you later enable cloud Gmail pulls):
# GMAIL_ADDRESS = "annie@kalavai.net"
# GMAIL_APP_PASSWORD = "xxxxxxxxxxxxxxxx"
# Optional password gate (or use Streamlit's viewer invites instead):
# SHARE_PASSWORD = "choose-one"
```

### 6. Deploy
Click **Deploy**. First build takes a couple of minutes. You'll get a permanent URL
like `https://warehouse-carton-reporting.streamlit.app`.

### 7. Restrict who can see it
- App → **Settings → Sharing** → set to **private** and **invite Armando's email**
  (and anyone else). Only invited Google accounts can open it.
- (Or skip that and set `SHARE_PASSWORD` above to gate it with a password.)

Send Armando the link. It stays live regardless of your Mac.

---

## Automatic daily refresh (no Mac needed)

A GitHub Action (`.github/workflows/daily-refresh.yml`) runs every day at ~11am PT,
**in GitHub's cloud**. It pulls the 3 email reports (Catalyst/MLG/Novo) from Gmail,
rebuilds the snapshot, commits it, and Streamlit Cloud redeploys — so Armando's view
updates on its own, whether your Mac is on or off.

**One-time setup to turn it on:**
1. Repo → **Settings → Secrets and variables → Actions → New repository secret**, add:
   - `GMAIL_ADDRESS` = `annie@kalavai.net`
   - `GMAIL_APP_PASSWORD` = your 16-char Gmail app password
2. Repo → **Settings → Actions → General → Workflow permissions** → select
   **"Read and write permissions"** → Save. (Lets the daily job push the snapshot.)
3. Test it: repo → **Actions** tab → **"Daily data refresh"** → **Run workflow**.
   After it finishes, the hosted dashboard updates within a minute.

> **Portal sources:** Americhine + RDG can't be pulled from the cloud yet (no VSR
> API), so the daily job keeps their last published values. Refresh those from your
> Mac when you have new exports (below). Once the Americhine VSR API is wired up,
> the daily job can pull it too.

## Updating the portal sources (Americhine / RDG) from your Mac

When you have fresh Americhine/RDG exports:
```bash
python3 src/gmail_fetch.py            # refresh locally (or dashboard "Refresh now")
python3 src/publish_snapshot.py --push   # or double-click "Publish to Cloud.command"
```
> `--push` needs git auth (GitHub Desktop signed in as you, or a token). If the push
> can't run, the snapshot is still committed locally — push it from GitHub Desktop.

---

## Notes
- Only the **aggregated** dataset is published (`data/consolidated.parquet` +
  status + run meta). Raw source files never leave your laptop.
- Want Armando's view to auto-refresh the 3 email sources in the cloud (no manual
  publish for those)? That's a later enhancement — the cloud app can IMAP Gmail
  itself if you add the `GMAIL_*` secrets and we flip on live cloud ingestion.
