# AUS Data Jobs Radar

**An end-to-end data platform that answers a question I actually needed answered: what do Australian employers hiring data people actually ask for?**

I scraped ~550 Australian data-job ads, built a pipeline that turns that mess into a
queryable warehouse, and used an LLM to pull out structure the raw data doesn't have —
then measured how accurate that LLM actually is instead of assuming.

```
Raw JSON  →  Bronze  →  Silver  →  Gold (star schema)  →  API / dashboard
   550       550        482          482 facts              CV matcher
            +validate  +clean      +dimensions
            +quarantine +dedup      +skills bridge
```

---

## What it answers

Real output from the pipeline, not illustrative:

**Top skills in Data Engineer ads** — Python (36), Azure (26), SQL (23), AWS (19), Terraform (13)

**Where the jobs are** — Sydney 146 · Melbourne 129 · Brisbane 69 · Perth 42

**Salary reality** — only ~27% of ads publish a number at all. The rest say "competitive salary".

---

## Architecture

| Layer | What happens | Tech |
|---|---|---|
| **Bronze** | Land raw ads untouched + `ingested_at` / `source_file`. Pydantic gate quarantines invalid rows to `dead_letter` with a reason. | Python, Pydantic, DuckDB |
| **Silver** | Parse salaries, strip HTML, standardise locations, exact-ID dedup (550 → 482). | Python, regex, pandas |
| **Extract** | LLM pulls skills, seniority, visa signals, years required. Content-hash cached. | Gemini, Pydantic |
| **Gold** | Star schema: `fact_job_posting` + 4 dimensions + skills bridge. | dbt, DuckDB |
| **Serve** | CV matcher API, LinkedIn draft generator. | FastAPI, embeddings |
| **Ops** | Asset graph, weekly schedule, freshness SLA, CI gates. | Dagster, GitHub Actions |

**Grain of the fact table:** one row per job posting.

---

## Hard problems I actually hit

**Salary is free text, not a number.** Eight distinct shapes across the corpus:
`$180k – $200k p.a.`, `AUD 75 - 100 per hour`, `$160,000 to $190,000`,
`Competitive Daily Rate`, `Base + Bonus + Super`. I wrote the rules in plain
English before writing any regex, and made a deliberate call: **hourly and daily
rates are kept raw with a `salary_period` label rather than annualised**, because
annualising requires assuming full-time hours the ad never states. Guessing would
have silently corrupted every downstream salary statistic.

The tests caught two bugs I'd otherwise have shipped: the word `"to"` wasn't
recognised as a range separator (so `$160,000 to $190,000` parsed as
min=max=160,000), and pandas represents missing values as `NaN` — a float, not
`None` — which crashed the null check.

**Sydney was 30+ different strings.** `Sydney NSW`, `Norwest, Sydney NSW`,
`Mascot, Sydney NSW`. Standardising suburbs to their parent city moved Sydney's
count from 99 to its true 146.

**Content-hash caching silently dropped 15 jobs.** Keying the extraction cache by
`sha256(title + description)` is right for cost — identical text should never be
re-extracted. But I *also* rebuilt the output tables from that hash-keyed dict, so
15 job IDs sharing identical ad text with another posting vanished. Cache by hash;
rebuild from the full row list. Caught it by asserting row counts, not by reading
the code.

**Free-tier quotas are counted in items, not requests.** The embedding endpoint
allows 100 *items* per minute — batching 20 texts per call consumes 20 units of
quota, not 1. My pacing assumed calls, so it died at exactly item 101. Rate limiting
has to be derived from whatever unit the provider actually meters.

---

## I measure the LLM instead of trusting it

30 ads hand-labelled into `extract/golden_set.jsonl`, scored by `extract/evaluate.py`:

| Field | Score |
|---|---|
| Skills (F1) | **0.815** — precision 0.786, recall 0.846 |
| Years experience | **0.929** |
| Seniority | **0.571** ⚠️ |
| Visa flag | 1.0 *(no positive examples in sample — measures false-positive rate only)* |

**Seniority is weak and I'm not hiding it.** The model disagrees with my labels on
nearly half of cases, mostly on ads with no explicit seniority signal where it guesses
a level rather than returning `unspecified`. That's a prompt problem, and it's exactly
what the eval harness exists to surface. CI enforces floors via
`scripts/check_eval_thresholds.py` — a prompt change that degrades accuracy fails the build.

**Prompt v2 is written but not yet measured.** It replaces "judge from title and
requirements" with explicit rules and an instruction to prefer `unspecified` over a
guess. Whether that actually helps is unknown until it is re-run and scored — the
free-tier daily quota was exhausted when it was written. The table above still reports
**v1 numbers**, because reporting an unmeasured improvement would defeat the entire
point of building an eval harness. The cache key includes the prompt version, so
re-running regenerates every extraction under one consistent prompt rather than
mixing versions.

---

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add GEMINI_API_KEY

python ingest/load_bronze.py                              # bronze
PYTHONPATH=transform python transform/build_silver.py     # silver
python extract/llm_extract.py                             # LLM extraction
python transform/semantic_dedup.py                        # embeddings + clusters
dbt build --project-dir transform/dbt_project --profiles-dir transform/dbt_project
python extract/evaluate.py                                # accuracy report

pytest tests/ -v                                          # 17 tests
uvicorn serve.api.main:app --reload                       # CV matcher on :8000
dagster dev -f orchestrate/dagster_defs.py                # asset graph UI
```

**The whole pipeline is idempotent.** Delete `warehouse.duckdb`, rerun everything,
get identical output — verified, and enforced in CI on every push. Every stage uses
`CREATE OR REPLACE` rather than `INSERT`, and API results are cached on disk so
reruns cost nothing.

---

## Cost

**~$0/month.** DuckDB is embedded (no server), Gemini free tier covers extraction and
embeddings, GitHub Actions is free for public repos. The Azure Terraform config
includes a $10 budget alert as a guardrail.

---

## Honest status

| Component | State |
|---|---|
| Bronze → Silver → Gold pipeline | ✅ Working, idempotent, 17 tests |
| dbt models + data tests | ✅ 35/35 passing |
| LLM extraction | ⚠️ 250/482 ads — free-tier daily quota. Resumes from cache; rerunning tomorrow completes it. |
| Eval harness | ✅ Working, wired into CI |
| Semantic dedup | ⚠️ Embeddings in progress, same quota constraint |
| Dagster orchestration | ✅ Assets + schedule + freshness check defined |
| CI/CD | ✅ 5 gates |
| CV matcher API | ✅ Responds; ranking needs embeddings complete |
| Terraform (Azure) | 📝 Written and reviewable, **not applied** — no Azure subscription attached |
| Power BI dashboard | ❌ Not built — Power BI Desktop is Windows-only |

I'd rather this table be accurate than impressive.

---

## Repo layout

```
ingest/       load_bronze.py, contracts.py      — landing + validation
transform/    parsers.py, build_silver.py, semantic_dedup.py, dbt_project/
extract/      llm_extract.py, evaluate.py, golden_set.jsonl
serve/        api/main.py, linkedin_post.py
orchestrate/  dagster_defs.py
infra/        main.tf
tests/        test_parsers.py
docs/         decisions/ADR-001-dedup-threshold.md
```

Built by [Dilitha Kolonne](https://github.com/didi-au).
