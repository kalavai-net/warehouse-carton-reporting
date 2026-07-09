"""
Natural-language Q&A over the consolidated carton dataset.

Approach: give Claude a single read-only SQL tool against an in-memory DuckDB
table built from the consolidated data. Claude writes the query, we run it
(SELECT-only, guarded), feed the rows back, and Claude answers in plain English.
SQL (rather than a fixed aggregation) lets it handle open-ended questions like
"How many cartons is RDG sending in August by week?" — it derives the week from
the real driving_date.

Model: claude-opus-4-8 with adaptive thinking (per the Claude API guidance).
Requires ANTHROPIC_API_KEY in the environment.
"""
from __future__ import annotations

import os
import re

import duckdb
import pandas as pd

try:
    import anthropic
except ImportError:  # surfaced nicely in the dashboard
    anthropic = None

MODEL = os.environ.get("WAREHOUSE_QA_MODEL", "claude-opus-4-8")

TABLE = "cartons"
SCHEMA_DOC = """\
Table `cartons` — one row per cleaned order line. Columns:
  source        TEXT  -- one of: catalyst, mlg, novo, americhine, rdg
  rnd_customer  TEXT  -- the CLIENT (master grouping): Catalyst, MLG, Novo, RDG,
                         AMERICHINE LLC, Indochine Intl (US) Co LLC, RND International, LLC.
                         This column holds what the dashboard calls the "Client".
  end_customer  TEXT  -- the end retailer (e.g. WAL-MART STORES, TARGET CORPORATION, KOHLS)
  driving_date  DATE  -- the date that drives month/day_of_week (a real DATE; use it for weeks)
  month         TEXT  -- full month name from driving_date (e.g. 'May'); '(blank)' if no date
  day_of_week   TEXT  -- full weekday name from driving_date (e.g. 'Monday')
  cartons       DOUBLE-- carton count (stored as exact decimals; may be fractional)
  units         DOUBLE-- source unit quantity where available (may be NULL)
  cancel_date   DATE  -- where available
  review_flag   TEXT  -- 'review:sub1_carton' on lines that compute to <1 carton, else ''

Facts to honor:
- The user calls rnd_customer the "Client" (or just "customer" at the master level);
  the end retailer is end_customer. In your written answers, say "client" — not
  "rnd_customer" — when referring to that grouping.
- Cartons can be fractional; SUM them as-is. Round only when presenting a final number.
- For "by week", derive it from driving_date, e.g. date_trunc('week', driving_date).
- Month is a name, not a number; to order months chronologically, sort by
  min(driving_date) or use a CASE/strftime on driving_date.
"""

SYSTEM = f"""You are a data analyst for a warehouse carton-volume report.
Answer questions by querying the dataset with the run_sql tool, then giving a
clear, concise answer in plain English. Always base numbers on query results —
never guess. Round carton counts to whole numbers when stating them, but note
when a total includes fractional cartons only if relevant.

{SCHEMA_DOC}

When a question implies a breakdown (by month, by week, by customer, by day),
return the breakdown. Keep answers short and businesslike. If a question is
ambiguous, make a reasonable assumption and state it."""

TOOLS = [{
    "name": "run_sql",
    "description": "Run a single read-only SELECT query against the `cartons` "
                   "DuckDB table and get rows back as JSON. SELECT statements only.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "A single SELECT query."}
        },
        "required": ["query"],
    },
}]

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|copy|pragma|"
    r"export|import|install|load|call|set|reset)\b", re.IGNORECASE)


class QAError(Exception):
    pass


def _friendly_api_error(e) -> str:
    """Turn an Anthropic API error into a plain-English, actionable message."""
    msg = str(getattr(e, "message", "") or e)
    low = msg.lower()
    if "credit balance is too low" in low or "billing" in low:
        return ("The Anthropic account is out of credits. Add credits at "
                "console.anthropic.com → Plans & Billing, then try again. "
                "(Your API key is valid — this is only a billing issue.)")
    status = getattr(e, "status_code", None)
    if status == 401:
        return "The Anthropic API key is invalid or revoked. Check the key and retry."
    if status == 429:
        return "Rate limited by the Anthropic API. Wait a moment and try again."
    if status and status >= 500:
        return "The Anthropic API had a server error. Try again in a moment."
    return f"Anthropic API error: {msg}"


def _guard_sql(query: str) -> str:
    q = query.strip().rstrip(";").strip()
    if _FORBIDDEN.search(q):
        raise QAError("Only read-only SELECT queries are allowed.")
    low = q.lstrip("(").lower()
    if not (low.startswith("select") or low.startswith("with")):
        raise QAError("Query must be a SELECT (or WITH ... SELECT).")
    if ";" in q:
        raise QAError("Only a single statement is allowed.")
    return q


def answer_question(question: str, df: pd.DataFrame, max_steps: int = 6) -> dict:
    """Return {answer, sql, result_df, steps}. Raises QAError on misconfig."""
    if anthropic is None:
        raise QAError("The 'anthropic' package is not installed.")
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise QAError("ANTHROPIC_API_KEY is not set in the environment.")

    con = duckdb.connect(":memory:")
    con.register("cartons_src", df)
    con.execute(f"CREATE TABLE {TABLE} AS SELECT * FROM cartons_src")

    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": question}]
    last_sql, last_result = None, None

    for _ in range(max_steps):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                system=SYSTEM,
                tools=TOOLS,
                messages=messages,
            )
        except anthropic.APIStatusError as e:
            raise QAError(_friendly_api_error(e)) from e
        if resp.stop_reason != "tool_use":
            answer = "".join(b.text for b in resp.content if b.type == "text").strip()
            return {"answer": answer, "sql": last_sql, "result_df": last_result}

        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            try:
                sql = _guard_sql(block.input["query"])
                rows = con.execute(sql).fetchdf()
                last_sql, last_result = sql, rows
                payload = rows.head(200).to_json(orient="records", date_format="iso")
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": payload})
            except Exception as e:  # feed the error back so Claude can correct
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": f"ERROR: {e}", "is_error": True})
        messages.append({"role": "user", "content": results})

    raise QAError("Could not produce an answer within the step limit.")
