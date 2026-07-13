"""
Gold layer — star schema.
Grain of the fact table: ONE ROW PER JOB POSTING.
Dimensions (company, location, date, skill) provide descriptive context.
Skills are attached via keyword matching for now (upgraded to LLM in Session 8).
"""
import re
import duckdb
import pandas as pd

con = duckdb.connect("warehouse.duckdb")
con.execute("CREATE SCHEMA IF NOT EXISTS gold")

# ---------------------------------------------------------------------------
# DIMENSIONS — each gets a surrogate integer key via row_number()
# ---------------------------------------------------------------------------
con.execute("""
    CREATE OR REPLACE TABLE gold.dim_company AS
    SELECT row_number() OVER (ORDER BY company) AS company_key, company AS company_name
    FROM (SELECT DISTINCT company FROM silver.job_ads WHERE company IS NOT NULL)
""")

con.execute("""
    CREATE OR REPLACE TABLE gold.dim_location AS
    SELECT row_number() OVER (ORDER BY state, city) AS location_key, city, state
    FROM (SELECT DISTINCT city, state FROM silver.job_ads WHERE city IS NOT NULL)
""")

con.execute("""
    CREATE OR REPLACE TABLE gold.dim_date AS
    SELECT
        row_number() OVER (ORDER BY d) AS date_key,
        d AS full_date,
        year(d)  AS year,
        month(d) AS month,
        day(d)   AS day,
        dayname(d) AS weekday
    FROM (
        SELECT DISTINCT CAST(CAST(listedAt AS TIMESTAMP) AS DATE) AS d
        FROM silver.job_ads WHERE listedAt IS NOT NULL
    )
""")

# ---------------------------------------------------------------------------
# FACT — one row per job posting, with surrogate FKs into each dimension
# ---------------------------------------------------------------------------
con.execute("""
    CREATE OR REPLACE TABLE gold.fact_job_posting AS
    SELECT
        s.id            AS job_id,
        c.company_key,
        l.location_key,
        dt.date_key,
        s.title,
        s.workArrangements AS work_arrangement,
        s.workTypes        AS work_type,
        s.salary_min,
        s.salary_max,
        s.salary_period
    FROM silver.job_ads s
    LEFT JOIN gold.dim_company  c  ON s.company = c.company_name
    LEFT JOIN gold.dim_location l  ON s.city = l.city AND s.state = l.state
    LEFT JOIN gold.dim_date     dt ON CAST(CAST(s.listedAt AS TIMESTAMP) AS DATE) = dt.full_date
""")

# ---------------------------------------------------------------------------
# SKILLS — dim_skill + bridge_job_skill (many-to-many) via keyword matching
# ---------------------------------------------------------------------------
SKILLS = [
    "Python", "SQL", "Java", "Scala", "AWS", "Azure", "GCP", "Databricks",
    "Snowflake", "dbt", "Airflow", "Dagster", "Spark", "Kafka", "Hadoop",
    "Power BI", "Tableau", "Looker", "Excel", "Pandas", "Terraform", "Docker",
    "Kubernetes", "ETL", "BigQuery", "Redshift", "PostgreSQL", "MySQL",
    "MongoDB", "Fabric", "Synapse", "SAS", "NoSQL",
]

dim_skill = pd.DataFrame({"skill_key": range(1, len(SKILLS) + 1), "skill_name": SKILLS})
con.execute("CREATE OR REPLACE TABLE gold.dim_skill AS SELECT * FROM dim_skill")

silver = con.sql("SELECT id, title, description_clean FROM silver.job_ads").df()
bridge_rows = []
for _, row in silver.iterrows():
    text = f"{row['title'] or ''} {row['description_clean'] or ''}"
    for i, skill in enumerate(SKILLS, start=1):
        if re.search(r"\b" + re.escape(skill) + r"\b", text, re.IGNORECASE):
            bridge_rows.append({"job_id": row["id"], "skill_key": i})

bridge = pd.DataFrame(bridge_rows)
con.execute("CREATE OR REPLACE TABLE gold.bridge_job_skill AS SELECT * FROM bridge")

# ---------------------------------------------------------------------------
# SANITY REPORT + the payoff query
# ---------------------------------------------------------------------------
for t in ["fact_job_posting", "dim_company", "dim_location", "dim_date", "dim_skill", "bridge_job_skill"]:
    n = con.sql(f"SELECT count(*) FROM gold.{t}").fetchone()[0]
    print(f"gold.{t:<20} {n:>6} rows")

print("\n=== TOP 15 SKILLS FOR DATA ENGINEER ROLES ===")
con.sql("""
    SELECT sk.skill_name, count(*) AS n_jobs
    FROM gold.fact_job_posting f
    JOIN gold.bridge_job_skill b ON f.job_id = b.job_id
    JOIN gold.dim_skill sk       ON b.skill_key = sk.skill_key
    WHERE f.title ILIKE '%engineer%'
    GROUP BY sk.skill_name
    ORDER BY n_jobs DESC
    LIMIT 15
""").show()
