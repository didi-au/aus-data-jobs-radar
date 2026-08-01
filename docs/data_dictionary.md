# Data dictionary

Every column in the gold layer. Grain of the fact table: **one row per job posting**.

## gold.fact_job_posting

| Column | Type | Description |
|---|---|---|
| `job_id` | VARCHAR | SEEK job ID. Primary key; unique, not null. |
| `company_key` | BIGINT | FK → `dim_company`. Null if the ad had no advertiser name. |
| `location_key` | BIGINT | FK → `dim_location`. Null if location was unparseable. |
| `date_key` | BIGINT | FK → `dim_date`, from the ad's listing date. |
| `title` | VARCHAR | Job title as advertised. Not null. |
| `work_arrangement` | VARCHAR | On-site / Hybrid / Remote, as given by the source. |
| `work_type` | VARCHAR | Full time / Contract-Temp / Part time / Casual. |
| `salary_min` | DOUBLE | Lower bound of the advertised range. Null when the ad gave no number. |
| `salary_max` | DOUBLE | Upper bound. Equals `salary_min` when a single figure was advertised. |
| `salary_period` | VARCHAR | `annual` / `hourly` / `daily`. **Rates are not annualised** — see README. |
| `seniority` | VARCHAR | LLM-extracted: `junior` / `mid` / `senior` / `unspecified`. Accuracy 0.571 — treat as indicative. |
| `visa_friendly` | BOOLEAN | LLM-extracted: true only when the ad explicitly mentions sponsorship or visa holders. |
| `years_experience_required` | DOUBLE | LLM-extracted minimum years. Null when unstated. Accuracy 0.929. |

## gold.dim_company

| Column | Type | Description |
|---|---|---|
| `company_key` | BIGINT | Surrogate key. Unique, not null. |
| `company_name` | VARCHAR | Advertiser name. Unique, not null. |

## gold.dim_location

| Column | Type | Description |
|---|---|---|
| `location_key` | BIGINT | Surrogate key. Unique, not null. |
| `city` | VARCHAR | Canonical city — suburbs collapsed to parent (e.g. "Mascot, Sydney NSW" → Sydney). |
| `state` | VARCHAR | One of NSW, VIC, QLD, WA, SA, ACT, TAS, NT. |

## gold.dim_date

| Column | Type | Description |
|---|---|---|
| `date_key` | BIGINT | Surrogate key. Unique, not null. |
| `full_date` | DATE | The listing date. Unique. |
| `year` / `month` / `day` | BIGINT | Calendar parts, for grouping without date functions. |
| `weekday` | VARCHAR | Day name, e.g. "Monday". |

## gold.dim_skill

| Column | Type | Description |
|---|---|---|
| `skill_key` | BIGINT | Surrogate key. Unique, not null. |
| `skill_name` | VARCHAR | Canonical display name, e.g. "Power BI". Unique. |
| `pattern` | VARCHAR | Regex used to detect the skill in ad text, word-boundary anchored. |

## gold.bridge_job_skill

Resolves the many-to-many between postings and skills.

| Column | Type | Description |
|---|---|---|
| `job_id` | VARCHAR | FK → `fact_job_posting`. |
| `skill_key` | BIGINT | FK → `dim_skill`. |

## Upstream tables

### bronze.job_ads
Raw ads exactly as scraped, plus `ingested_at` (load timestamp) and `source_file`
(which scrape it came from). Never edited — this is the recovery point.

### bronze.dead_letter
Rows that failed Pydantic validation, with `job_id`, `source_file` and the
validation `reason`. Currently 0 rows: only `id` and `title` are required, because
a missing salary is incomplete data, not invalid data.

### silver.job_ads
Cleaned and deduplicated (482 rows). Adds `salary_min/max/period`, `city`, `state`,
`description_clean`.

### silver.job_clusters
| Column | Type | Description |
|---|---|---|
| `job_id` | VARCHAR | The posting. |
| `cluster_id` | BIGINT | Semantic cluster — same underlying role reposted or reworded. |
| `is_canonical` | BOOLEAN | True for the lowest `job_id` in each cluster. Filter on this for one row per real job. |

### extract.job_attrs / extract.job_skills
LLM output, one row per posting (`job_attrs`) and one row per posting-skill pair
(`job_skills`). Rebuilt from `data/extract_cache.jsonl` on every run.
