import duckdb
import pandas as pd
from parsers import parse_salary, strip_html, standardise_location

con = duckdb.connect("warehouse.duckdb")
con.execute("CREATE SCHEMA IF NOT EXISTS silver")

# Pull the columns we care about out of bronze. content is a nested struct,
# so we reach into content.unEditedContent for the raw HTML description,
# and advertiser.name / joblocationInfo.displayLocation out of their structs.
# Dedup first: the same job id can appear in more than one source file
# (matched multiple search queries). Keep one row per id.
bronze = con.sql("""
    SELECT
        id,
        title,
        salary AS salary_raw,
        content.unEditedContent AS description_raw,
        workArrangements,
        workTypes,
        advertiser.name AS company,
        joblocationInfo.displayLocation AS location_raw,
        listedAt,
        source_file,
        ingested_at
    FROM bronze.job_ads
    QUALIFY row_number() OVER (PARTITION BY id ORDER BY source_file) = 1
""").df()

# Apply the salary parser row by row → three new columns
salary_parsed = bronze["salary_raw"].apply(parse_salary).apply(pd.Series)
bronze["salary_min"] = salary_parsed["salary_min"]
bronze["salary_max"] = salary_parsed["salary_max"]
bronze["salary_period"] = salary_parsed["salary_period"]

# Standardise location → clean city + state (collapses suburb variants)
loc_parsed = bronze["location_raw"].apply(standardise_location).apply(pd.Series)
bronze["city"] = loc_parsed["city"]
bronze["state"] = loc_parsed["state"]

# Strip HTML from the description
bronze["description_clean"] = bronze["description_raw"].apply(strip_html)

silver = bronze.drop(columns=["description_raw"])

con.execute("CREATE OR REPLACE TABLE silver.job_ads AS SELECT * FROM silver")

# --- quick sanity report ---
print("silver.job_ads rows (deduped):", con.sql("SELECT count(*) FROM silver.job_ads").fetchone()[0])
print("distinct ids:", con.sql("SELECT count(DISTINCT id) FROM silver.job_ads").fetchone()[0])
print()
print("salary_period breakdown:")
con.sql("SELECT salary_period, count(*) AS n FROM silver.job_ads GROUP BY salary_period ORDER BY n DESC").show()
print("top cities AFTER standardisation (suburbs collapsed):")
con.sql("SELECT city, state, count(*) AS n FROM silver.job_ads GROUP BY city, state ORDER BY n DESC LIMIT 8").show()
