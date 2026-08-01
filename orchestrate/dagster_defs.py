"""
Session 15 — Dagster orchestration.

The pipeline is modelled as ASSETS rather than tasks, so Dagster knows what
each step produces and can draw the lineage graph:

    bronze_job_ads -> silver_job_ads -> gold_star_schema
                          |                   ^
                          v                   |
                   llm_extraction ------------+
                          |
                          v
                   extraction_eval

A weekly schedule runs the whole graph; a freshness check alerts if gold has
not been rebuilt within 8 days.
"""
import subprocess
from pathlib import Path

from dagster import (
    AssetCheckResult,
    AssetExecutionContext,
    Definitions,
    ScheduleDefinition,
    asset,
    asset_check,
    define_asset_job,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_script(context: AssetExecutionContext, *args: str) -> str:
    """Run a pipeline script from the repo root and surface its output in the UI."""
    result = subprocess.run(
        args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    context.log.info(result.stdout[-4000:])
    if result.returncode != 0:
        context.log.error(result.stderr[-4000:])
        raise RuntimeError(f"{' '.join(args)} failed with exit {result.returncode}")
    return result.stdout


@asset(description="Raw job ads landed as-is, with a Pydantic validation gate.")
def bronze_job_ads(context: AssetExecutionContext) -> None:
    run_script(context, ".venv/bin/python", "ingest/load_bronze.py")


@asset(
    deps=[bronze_job_ads],
    description="Cleaned: salary parsed, HTML stripped, locations standardised, deduped.",
)
def silver_job_ads(context: AssetExecutionContext) -> None:
    run_script(context, ".venv/bin/python", "transform/build_silver.py")


@asset(
    deps=[silver_job_ads],
    description="LLM-extracted skills, seniority and visa signals (content-hash cached).",
)
def llm_extraction(context: AssetExecutionContext) -> None:
    run_script(context, ".venv/bin/python", "extract/llm_extract.py")


@asset(
    deps=[silver_job_ads],
    description="Embedding-based clusters collapsing reworded reposts.",
)
def semantic_clusters(context: AssetExecutionContext) -> None:
    run_script(context, ".venv/bin/python", "transform/semantic_dedup.py")


@asset(
    deps=[silver_job_ads, llm_extraction],
    description="Star schema built by dbt: fact_job_posting + dimensions + bridge.",
)
def gold_star_schema(context: AssetExecutionContext) -> None:
    run_script(
        context,
        ".venv/bin/dbt",
        "build",
        "--project-dir",
        "transform/dbt_project",
        "--profiles-dir",
        "transform/dbt_project",
    )


@asset(
    deps=[llm_extraction],
    description="Extraction accuracy scored against the hand-labelled golden set.",
)
def extraction_eval(context: AssetExecutionContext) -> None:
    run_script(context, ".venv/bin/python", "extract/evaluate.py")


@asset_check(asset=gold_star_schema, description="Gold must have been rebuilt in the last 8 days.")
def gold_is_fresh() -> AssetCheckResult:
    """Freshness SLA: weekly schedule plus one day of slack."""
    import datetime as dt

    warehouse = REPO_ROOT / "warehouse.duckdb"
    if not warehouse.exists():
        return AssetCheckResult(passed=False, metadata={"reason": "warehouse.duckdb missing"})

    last_built = dt.datetime.fromtimestamp(warehouse.stat().st_mtime, tz=dt.UTC)
    age_days = (dt.datetime.now(tz=dt.UTC) - last_built).days
    return AssetCheckResult(
        passed=age_days <= 8,
        metadata={"age_days": age_days, "sla_days": 8},
    )


weekly_refresh = define_asset_job(name="weekly_refresh", selection="*")

defs = Definitions(
    assets=[
        bronze_job_ads,
        silver_job_ads,
        llm_extraction,
        semantic_clusters,
        gold_star_schema,
        extraction_eval,
    ],
    asset_checks=[gold_is_fresh],
    jobs=[weekly_refresh],
    schedules=[
        ScheduleDefinition(
            job=weekly_refresh,
            cron_schedule="0 6 * * 1",  # Mondays 06:00
            name="weekly_monday_refresh",
        )
    ],
)
