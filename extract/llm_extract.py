"""
Session 8 — LLM extraction.
Sends each job ad's text to Gemini and gets back schema-enforced JSON:
skills, seniority, visa_friendly (+ evidence), years_experience_required.

Design:
- Content-hash caching: each ad is keyed by sha256(title + description).
  Unchanged ads are never re-extracted — reruns are free and idempotent.
- Batching: 25 ads per request, which keeps the full 482-ad dataset to
  ~20 requests and stays inside the free tier's daily quota.
- Validation: responses are parsed through Pydantic; a bad row goes to the
  failure log, never silently into the warehouse (same dead-letter idea
  as bronze).
"""
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Literal

import duckdb
import pandas as pd
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel

# gemini-flash-latest resolves to the newest flash model, which carries the
# tightest free-tier quota (20 requests/day). gemini-2.0-flash is pinned
# deliberately: a far more generous free tier, and pinning also means a new
# model release can never silently change extraction behaviour mid-project.
MODEL = "gemini-2.0-flash"
BATCH_SIZE = 25
SECONDS_BETWEEN_CALLS = 5.0  # ~12 requests/minute, inside the 15 RPM limit
DESCRIPTION_LIMIT = 1500     # chars; enough signal, keeps tokens low
CACHE_PATH = Path("data/extract_cache.jsonl")
FAILURE_PATH = Path("data/extract_failures.jsonl")


class JobExtraction(BaseModel):
    job_id: str
    skills: list[str]
    seniority: Literal["junior", "mid", "senior", "unspecified"]
    visa_friendly: bool
    visa_evidence: str | None = None
    years_experience_required: float | None = None


PROMPT = """You are extracting structured data from Australian job advertisements.
For EACH job ad below, return one JSON object with:
- job_id: copied exactly from the ad header
- skills: technical skills/tools explicitly mentioned (canonical names, e.g. "Python", "Power BI"); [] if none
- seniority: "junior", "mid", "senior", or "unspecified" — judge from title and requirements
- visa_friendly: true ONLY if the ad explicitly welcomes visa holders or offers sponsorship
- visa_evidence: the exact phrase that proves visa_friendly, else null
- years_experience_required: minimum years explicitly required, else null

Return a JSON array with one object per ad, in the same order.

{ads}"""


def content_hash(title: str, description: str) -> str:
    return hashlib.sha256(f"{title}\n{description}".encode()).hexdigest()


def load_cache() -> dict[str, dict]:
    """Hash -> row, used only to answer 'has this content been extracted?'.

    Deliberately NOT used to rebuild the output tables: two different job_ids
    can share identical text (same ad posted twice), and keying by hash would
    silently drop all but one of them.
    """
    cache = {}
    if CACHE_PATH.exists():
        with open(CACHE_PATH) as f:
            for line in f:
                row = json.loads(line)
                cache[row["hash"]] = row
    return cache


def load_all_rows() -> list[dict]:
    """Every cached row, one per job_id — the source of truth for the tables."""
    if not CACHE_PATH.exists():
        return []
    with open(CACHE_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


def append_cache(rows: list[dict]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "a") as f:
        f.writelines(json.dumps(row) + "\n" for row in rows)


def log_failure(batch_ids: list[str], reason: str) -> None:
    FAILURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FAILURE_PATH, "a") as f:
        f.write(json.dumps({"job_ids": batch_ids, "reason": reason[:500]}) + "\n")


def call_gemini(client: genai.Client, ads_text: str) -> list[JobExtraction]:
    """One API call for one batch, with retry on rate-limit/server errors."""
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=PROMPT.format(ads=ads_text),
                config={
                    "response_mime_type": "application/json",
                    "response_schema": list[JobExtraction],
                },
            )
            return response.parsed
        except Exception as e:
            transient = "429" in str(e) or "500" in str(e) or "503" in str(e)
            if transient and attempt < 2:
                time.sleep(20 * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def main() -> None:
    load_dotenv()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    con = duckdb.connect("warehouse.duckdb")

    jobs = con.sql("""
        SELECT id, title, coalesce(description_clean, '') AS description
        FROM silver.job_ads
    """).fetchall()

    cache = load_cache()
    pending = []
    for job_id, title, description in jobs:
        h = content_hash(title or "", description)
        if h not in cache:
            pending.append((h, job_id, title, description[:DESCRIPTION_LIMIT]))

    print(f"jobs: {len(jobs)} | cached: {len(jobs) - len(pending)} | to extract: {len(pending)}")

    for i in range(0, len(pending), BATCH_SIZE):
        batch = pending[i : i + BATCH_SIZE]
        ads_text = "\n\n".join(
            f"=== JOB job_id={jid} ===\nTITLE: {title}\n{desc}"
            for _, jid, title, desc in batch
        )
        batch_ids = [jid for _, jid, _, _ in batch]
        try:
            results = call_gemini(client, ads_text)
            by_id = {r.job_id: r for r in results}
            rows = []
            for h, jid, _, _ in batch:
                if jid in by_id:
                    rows.append({"hash": h, "job_id": jid, "extraction": by_id[jid].model_dump()})
                else:
                    log_failure([jid], "model omitted this job_id from batch response")
            append_cache(rows)
            print(f"  batch {i // BATCH_SIZE + 1}: ok ({len(rows)}/{len(batch)})")
        except Exception as e:
            log_failure(batch_ids, f"{type(e).__name__}: {e}")
            print(f"  batch {i // BATCH_SIZE + 1}: FAILED — {type(e).__name__}")
        time.sleep(SECONDS_BETWEEN_CALLS)

    # Rebuild warehouse tables from every cached row (idempotent, like bronze).
    attrs, skills = [], []
    seen_job_ids = set()
    for row in load_all_rows():
        if row["job_id"] in seen_job_ids:
            continue
        seen_job_ids.add(row["job_id"])
        ext = row["extraction"]
        attrs.append({
            "job_id": row["job_id"],
            "seniority": ext["seniority"],
            "visa_friendly": ext["visa_friendly"],
            "visa_evidence": ext.get("visa_evidence"),
            "years_experience_required": ext.get("years_experience_required"),
        })
        for s in ext["skills"]:
            skills.append({"job_id": row["job_id"], "skill": s.strip()})

    # ruff flags these as unused: DuckDB resolves `attrs_df` / `skills_df`
    # by name from the enclosing Python scope inside the SQL below.
    attrs_df = pd.DataFrame(attrs)  # noqa: F841
    skills_df = pd.DataFrame(skills)  # noqa: F841
    con.execute("CREATE SCHEMA IF NOT EXISTS extract")
    con.execute("CREATE OR REPLACE TABLE extract.job_attrs AS SELECT * FROM attrs_df")
    con.execute("CREATE OR REPLACE TABLE extract.job_skills AS SELECT DISTINCT * FROM skills_df")

    print("\nextract.job_attrs:", con.sql("SELECT count(*) FROM extract.job_attrs").fetchone()[0])
    print("extract.job_skills:", con.sql("SELECT count(*) FROM extract.job_skills").fetchone()[0])
    con.sql("""
        SELECT skill, count(*) AS n FROM extract.job_skills
        GROUP BY skill ORDER BY n DESC LIMIT 10
    """).show()


if __name__ == "__main__":
    main()
