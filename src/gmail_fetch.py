"""
Gmail auto-ingestion for the warehouse pipeline.

Connects to Gmail over IMAP, finds the daily report emails (Catalyst, MLG, Novo —
the three sources Armando forwards), downloads each Excel attachment into the
drop folder under a normalized name that matches the source's file_glob, then
runs the existing pipeline so the dashboard shows fresh data.

Americhine + RDG arrive via the VSR portal and are still dropped in manually.

Auth: reads GMAIL_ADDRESS and GMAIL_APP_PASSWORD from the environment
(config/secrets.env). The app password is a 16-char Google token, NOT the real
account password. Nothing is committed; secrets.env is git-ignored, chmod 600.

Run directly:        python3 src/gmail_fetch.py
From the dashboard:  the "Pull latest from Gmail" button calls fetch_and_run().
On a schedule:       launchd runs fetch_and_refresh.command every morning.
"""
from __future__ import annotations

import datetime as dt
import email
import imaplib
import logging
import os
import sys
from email.utils import parsedate_to_datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import transform as T  # noqa: E402  (config + paths + logging helpers)
import pipeline  # noqa: E402

IMAP_HOST = "imap.gmail.com"
LOOKBACK_DAYS = 5  # how far back to look for the most recent report of each source

log = logging.getLogger("gmail_fetch")


class GmailFetchError(Exception):
    pass


def _creds() -> tuple[str, str]:
    addr = os.environ.get("GMAIL_ADDRESS", "").strip()
    pw = os.environ.get("GMAIL_APP_PASSWORD", "").strip().replace(" ", "")
    if not addr or not pw:
        raise GmailFetchError(
            "Gmail not configured. Add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to "
            "config/secrets.env (the app password is a 16-char Google token).")
    return addr, pw


def _email_sources(config: dict) -> dict:
    """Sources that have an `email:` block, i.e. the ones we fetch from Gmail."""
    return {k: c for k, c in config["sources"].items() if c.get("email")}


def _find_latest_attachment(imap: imaplib.IMAP4_SSL, subject: str):
    """Return (filename, payload_bytes, email_date) of the .xlsx on the most
    recent email whose subject contains `subject`, within LOOKBACK_DAYS.
    email_date is a naive LOCAL datetime (when the report arrived). None if not found."""
    since = (dt.date.today() - dt.timedelta(days=LOOKBACK_DAYS)).strftime("%d-%b-%Y")
    # IMAP SUBJECT search is substring + case-insensitive.
    typ, data = imap.search(None, "SINCE", since, "SUBJECT", f'"{subject}"')
    if typ != "OK" or not data or not data[0]:
        return None
    ids = data[0].split()
    for msg_id in reversed(ids):  # newest first
        typ, raw = imap.fetch(msg_id, "(RFC822)")
        if typ != "OK" or not raw or not raw[0]:
            continue
        msg = email.message_from_bytes(raw[0][1])
        try:
            edate = parsedate_to_datetime(msg.get("Date"))
            if edate and edate.tzinfo:  # convert to local, then drop tz for display
                edate = edate.astimezone().replace(tzinfo=None)
        except (TypeError, ValueError):
            edate = None
        for part in msg.walk():
            fn = part.get_filename()
            if fn and fn.lower().endswith((".xlsx", ".xls")):
                payload = part.get_payload(decode=True)
                if payload:
                    return fn, payload, edate
    return None


def fetch_bytes() -> tuple[dict, list, dict]:
    """Pull the latest Catalyst/MLG/Novo attachments straight into memory.
    Returns ({source: bytes}, [missing_sources], {source: email_datetime}).
    Writes nothing to disk."""
    config = T.load_config()
    addr, pw = _creds()
    out, missing, dates = {}, [], {}
    log.info("connecting to Gmail (%s) as %s", IMAP_HOST, addr)
    imap = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        imap.login(addr, pw)
    except imaplib.IMAP4.error as e:
        raise GmailFetchError(
            f"Gmail login failed: {e}. Check GMAIL_ADDRESS / GMAIL_APP_PASSWORD "
            "(use an App Password, not your normal password).") from e
    try:
        imap.select("INBOX")
        for source, cfg in _email_sources(config).items():
            subj = cfg["email"]["subject_contains"]
            found = _find_latest_attachment(imap, subj)
            if not found:
                log.warning("[%s] no email found matching subject '%s' in last %d days",
                            source, subj, LOOKBACK_DAYS)
                missing.append(source)
                continue
            _orig_fn, payload, edate = found
            out[source] = payload
            if edate is not None:
                dates[source] = edate
            log.info("[%s] fetched %d KB into memory (not saved to disk); email date %s",
                     source, len(payload) // 1024, edate)
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return out, missing, dates


def fetch_and_run(folder: str | None = None) -> dict:
    """Fetch the email reports in memory and rebuild the consolidated dataset
    (email sources from Gmail, portal sources read from the drop folder).
    The raw Excel files are never written to the laptop."""
    buffers, missing, dates = fetch_bytes()
    if not buffers:
        raise GmailFetchError(
            "Could not fetch any of the 3 email reports — data was NOT rebuilt "
            "(the dashboard still shows the last successful pull).")
    meta = pipeline.run_pipeline(folder=folder, buffers=buffers, source_dates=dates)
    result = {"fetched": list(buffers), "missing": missing, "pipeline": meta}
    log.info("fetch+pipeline done: fetched %s, missing %s, %d rows",
             result["fetched"], result["missing"], int(meta["rows"]))
    return result


def main() -> None:
    T.setup_logging(dt.datetime.now().strftime("gmail_%Y%m%d_%H%M%S"))
    try:
        res = fetch_and_run()
    except GmailFetchError as e:
        log.error(str(e))
        sys.exit(1)
    if res["missing"]:
        log.warning("Done with WARNINGS — missing: %s (Americhine/RDG are portal "
                    "exports and are expected to be added manually).", res["missing"])
    else:
        log.info("All 3 email reports ingested.")


if __name__ == "__main__":
    main()
