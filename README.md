# AUS Data Jobs Radar

A data platform that ingests Australian data-job advertisements, models them into a
dimensional warehouse, and extracts structured signal with an LLM — measured against
a hand-labelled evaluation set rather than assumed to be correct.

```
Raw JSON  ->  Bronze  ->  Silver  ->  Gold (star schema)  ->  API / dashboard
   550         550         482            482 facts             CV matcher
             validate     clean         dimensions
             quarantine   dedup         skills bridge
```

## Sample output

Top skills in Data Engineer postings: Python (36), Azure (26), SQL (23), AWS (19),
Terraform (13).

Postings by city: Sydney 146, Melbourne 129, Brisbane 69, Perth 42.

Only ~27% of postings disclose a salary figure; the rest use text such as
"competitive salary".

## Architecture

| Layer | Responsibility | Stack |
|---|---|---|
| Bronze | Land raw postings unmodified with `ingested_at` / `source_file` tracking columns. A Pydantic validation gate routes invalid rows to `dead_letter` with a reason rather than dropping them. | Python, Pydantic, DuckDB |
| Silver | Parse salary strings, strip HTML, standardise locations, deduplicate by exact ID (550 → 482). | Python, regex, pandas |
| Extract | LLM extraction of skills, seniority, visa signal, years required. Cached by content hash. | Gemini API, Pydantic |
| Gold | Dimensional model: `fact_job_posting` plus four dimensions and a skills bridge table. | dbt, DuckDB |
| Serve | CV-matching API and a market-summary draft generator. | FastAPI, embeddings |
| Ops | Asset-based orchestration, weekly schedule, freshness check, CI gates. | Dagster, GitHub Actions |

Grain of the fact table: one row per job posting.

## Design decisions

**Salary parsing.** The corpus contains at least eight distinct salary formats —
`$180k - $200k p.a.`, `AUD 75 - 100 per hour`, `$160,000 to $190,000`,
`Competitive Daily Rate`, `Base + Bonus + Super`. Parsing rules were written in
plain English before any regex was implemented. Hourly and daily rates are stored
raw with a `salary_period` label rather than annualised, since annualising would
require assuming full-time hours the posting does not state — an assumption that
would silently distort every downstream salary statistic.

**Location standardisation.** Suburb-qualified locations (`Norwest, Sydney NSW`,
`Mascot, Sydney NSW`) are collapsed to their parent city and state, which moved
Sydney's true posting count from 99 to 146 after removing the fragmentation.

**Bronze immutability.** Raw data is never edited in place. A validation gate
quarantines invalid rows with a reason instead of dropping them, so cleaning
logic can be corrected and rerun from source without any data loss.

**Idempotent pipeline.** Every stage uses `CREATE OR REPLACE` rather than
`INSERT`, and external API results are cached to disk. Deleting the warehouse
and rerunning the full pipeline produces identical output; this is enforced in
CI on every push.

**Semantic deduplication threshold.** Exact-ID matching cannot catch a role
reposted with reworded copy or listed by multiple recruiters. Postings are
embedded and clustered by cosine similarity at a threshold of 0.90, chosen after
comparing 0.85 (over-merges distinct roles at the same employer) and 0.95 (misses
genuine reposts). Rationale in `docs/decisions/ADR-001-dedup-threshold.md`.

## Two defects found during development

**Content-hash caching dropped rows.** The extraction cache is keyed by
`sha256(title + description)`, which is correct for avoiding redundant API calls.
The output tables were initially rebuilt from that same hash-keyed structure,
which meant two different job IDs sharing identical ad text collapsed into one —
silently dropping 15 postings. Fixed by rebuilding output from the full row list
while using the hash only to decide what needs (re-)extraction. Caught by
asserting row counts against the source table, not by code review.

**Rate limiting used the wrong unit.** The embedding API's free-tier quota is
metered in items per minute, not requests per minute — a batch of 20 texts
consumes 20 units of quota. Pacing had been derived from request count, which
failed at exactly the 101st item. Fixed by deriving the delay from batch size and
the documented items-per-minute limit.

## Evaluation

Extraction quality is measured against a 30-posting hand-labelled set
(`extract/golden_set.jsonl`), scored by `extract/evaluate.py`:

| Field | Score |
|---|---|
| Skills (F1) | 0.815 (precision 0.786, recall 0.846) |
| Years experience | 0.929 |
| Seniority | 0.571 |
| Visa flag | 1.0 (sample contains no positive examples; measures false-positive rate only) |

Seniority accuracy is low: the model assigns a level to postings with no
explicit seniority signal rather than returning `unspecified`. A revised prompt
(v2) adds explicit per-class rules and instructs the model to prefer
`unspecified` over an inferred guess. It has not yet been re-scored — the
evaluation set above reflects prompt v1. The cache key includes prompt version
and model name, so a prompt change invalidates prior extractions rather than
mixing two prompt versions in one dataset.

`scripts/check_eval_thresholds.py` enforces minimum scores in CI; a change that
degrades extraction accuracy fails the build.

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # set GEMINI_API_KEY

python ingest/load_bronze.py
PYTHONPATH=transform python transform/build_silver.py
python extract/llm_extract.py
python transform/semantic_dedup.py
dbt build --project-dir transform/dbt_project --profiles-dir transform/dbt_project
python extract/evaluate.py

pytest tests/ -v
uvicorn serve.api.main:app --reload           # CV matcher, http://127.0.0.1:8000/docs
dagster dev -f orchestrate/dagster_defs.py    # asset graph, http://localhost:3000
```

## Cost

Designed to run near $0/month: DuckDB is embedded (no managed database), the
Gemini free tier covers extraction and embeddings at this volume, and GitHub
Actions is free for public repositories. The Terraform configuration includes a
budget alert as a cost guardrail for the Azure deployment.

## Current status

| Component | Status |
|---|---|
| Bronze / Silver / Gold pipeline | Complete. Idempotent, 17 unit tests. |
| dbt models and data tests | Complete. 35/35 passing. |
| LLM extraction | In progress — 250/482 postings, limited by free-tier daily quota. Resumable from cache. |
| Evaluation harness | Complete, wired into CI. |
| Semantic deduplication | In progress, same quota constraint. |
| Dagster orchestration | Complete — assets, schedule, and freshness check defined. |
| CI/CD | Complete — five gates (lint, unit tests, pipeline rebuild, dbt, accuracy). |
| CV matcher API | Functional; ranking quality depends on embedding completion. |
| Terraform (Azure) | Written and reviewed, not applied — no Azure subscription attached to the project. |
| Power BI dashboard | Not built — Power BI Desktop requires Windows. |

## Repository layout

```
ingest/       load_bronze.py, contracts.py       landing and validation
transform/    parsers.py, build_silver.py, semantic_dedup.py, dbt_project/
extract/      llm_extract.py, evaluate.py, golden_set.jsonl
serve/        api/main.py, linkedin_post.py
orchestrate/  dagster_defs.py
infra/        main.tf
tests/        test_parsers.py
docs/         architecture.md, data_dictionary.md, decisions/
```

## Author

Dilitha Kolonne — [github.com/didi-au](https://github.com/didi-au)
