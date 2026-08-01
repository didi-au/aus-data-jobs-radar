import json

import duckdb
import pandas as pd
from contracts import JobAd
from pydantic import ValidationError

valid_records = []
invalid_records = []

for filename in ["analyst.json", "engineer.json", "mining.json"]:
    with open(f"data/raw/seed/{filename}") as f:
        records = json.load(f)

    for record in records:
        try:
            JobAd(**record)
            valid_records.append({**record, "source_file": filename})
        except ValidationError as e:
            invalid_records.append({
                "id": record.get("id"),
                "source_file": filename,
                "reason": str(e)
            })

print("valid:", len(valid_records))
print("invalid:", len(invalid_records))

valid_df = pd.DataFrame(valid_records)
invalid_df = pd.DataFrame(invalid_records, columns=["id", "source_file", "reason"])

con = duckdb.connect("warehouse.duckdb")
con.execute("CREATE SCHEMA IF NOT EXISTS bronze")

con.execute("""
    CREATE OR REPLACE TABLE bronze.job_ads AS
    SELECT *, CURRENT_TIMESTAMP AS ingested_at FROM valid_df
""")

con.execute("""
    CREATE OR REPLACE TABLE bronze.dead_letter AS
    SELECT *, CURRENT_TIMESTAMP AS ingested_at FROM invalid_df
""")

con.sql("SELECT count(*) FROM bronze.job_ads").show()
con.sql("SELECT count(*) FROM bronze.dead_letter").show()