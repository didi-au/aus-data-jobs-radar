"""
Session 19 — weekly LinkedIn insight post.

Reads the gold layer and DRAFTS a market-stat post to
serve/drafts/linkedin_YYYY-MM-DD.md.

Deliberately draft-only: it never posts. A human reads it, edits it, and
publishes it. Auto-posting to a personal brand account is not something a
cron job should be trusted with.
"""
import datetime as dt
from pathlib import Path

import duckdb

DRAFTS_DIR = Path("serve/drafts")


def main() -> None:
    con = duckdb.connect("warehouse.duckdb", read_only=True)

    total = con.sql("SELECT count(*) FROM gold.fact_job_posting").fetchone()[0]

    top_skills = con.sql("""
        SELECT s.skill_name, count(*) AS n
        FROM gold.bridge_job_skill b
        JOIN gold.dim_skill s ON b.skill_key = s.skill_key
        GROUP BY s.skill_name
        ORDER BY n DESC
        LIMIT 5
    """).fetchall()

    top_cities = con.sql("""
        SELECT l.city, count(*) AS n
        FROM gold.fact_job_posting f
        JOIN gold.dim_location l ON f.location_key = l.location_key
        GROUP BY l.city
        ORDER BY n DESC
        LIMIT 3
    """).fetchall()

    salary = con.sql("""
        SELECT
            median(salary_min) AS med_min,
            median(salary_max) AS med_max,
            count(*) AS n
        FROM gold.fact_job_posting
        WHERE salary_period = 'annual' AND salary_min IS NOT NULL
    """).fetchone()

    cloud = con.sql("""
        SELECT s.skill_name, count(*) AS n
        FROM gold.bridge_job_skill b
        JOIN gold.dim_skill s ON b.skill_key = s.skill_key
        WHERE s.skill_name IN ('Azure', 'AWS', 'GCP')
        GROUP BY s.skill_name
        ORDER BY n DESC
    """).fetchall()
    con.close()

    today = dt.datetime.now(tz=dt.UTC).date()
    skills_lines = "\n".join(f"{i}. {name} — {n} ads" for i, (name, n) in enumerate(top_skills, 1))
    cities_line = " · ".join(f"{city} ({n})" for city, n in top_cities)
    cloud_line = " vs ".join(f"{name} {n}" for name, n in cloud) if cloud else "n/a"

    salary_line = (
        f"Median advertised range: ${salary[0]:,.0f} – ${salary[1]:,.0f} "
        f"(from {salary[2]} ads that actually disclosed a number)"
        if salary and salary[0]
        else "Not enough disclosed salaries this week."
    )

    post = f"""# LinkedIn draft — {today}

I scraped and modelled {total} Australian data job ads. Here's what the market
is actually asking for:

**Most in-demand skills**
{skills_lines}

**Cloud platform race:** {cloud_line}

**Where the jobs are:** {cities_line}

**Salary reality check**
{salary_line} — most ads still don't publish one at all.

Built with Python, DuckDB, dbt and a star schema; skills extracted by an LLM
and scored against a hand-labelled set so I know the accuracy rather than
assuming it.

Full pipeline: github.com/didi-au/aus-data-jobs-radar

---
*Draft only — review and edit before posting.*
"""

    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    out = DRAFTS_DIR / f"linkedin_{today}.md"
    out.write_text(post)
    print(f"Draft written to {out}\n")
    print(post)


if __name__ == "__main__":
    main()
