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

## Updating the data Armando sees

The hosted view shows the last snapshot you published. To update it:

```bash
# 1. Refresh locally (pull Gmail + your Americhine/RDG files)
python3 src/gmail_fetch.py           # or the dashboard "Refresh now" button

# 2. Publish the snapshot to the cloud
python3 src/publish_snapshot.py --push
```
(or double-click **"Publish to Cloud.command"**.) The hosted dashboard redeploys
automatically within a minute of the push.

> `--push` needs git auth set up (GitHub Desktop signed in as you, or a token). If
> the push can't run, the snapshot is still committed locally — push it from
> GitHub Desktop.

---

## Notes
- Only the **aggregated** dataset is published (`data/consolidated.parquet` +
  status + run meta). Raw source files never leave your laptop.
- Want Armando's view to auto-refresh the 3 email sources in the cloud (no manual
  publish for those)? That's a later enhancement — the cloud app can IMAP Gmail
  itself if you add the `GMAIL_*` secrets and we flip on live cloud ingestion.
