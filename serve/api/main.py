"""
Session 18 — CV matcher API.

POST a CV, get back the closest-matching live jobs plus the skills you are
missing for each. Reuses the Session 11 embedding approach: the CV is embedded
with the same model as the job ads, then ranked by cosine similarity.

Run:  .venv/bin/uvicorn serve.api.main:app --reload
Docs: http://127.0.0.1:8000/docs
"""
import json
import os
from pathlib import Path

import duckdb
import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from google import genai
from pydantic import BaseModel, Field

load_dotenv()

EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 768
WAREHOUSE = "warehouse.duckdb"
EMBEDDINGS_PATH = Path("data/embeddings.jsonl")

app = FastAPI(
    title="AUS Data Jobs Radar — CV Matcher",
    description="Rank live Australian data jobs against a CV, and show the skill gap.",
    version="1.0.0",
)


class MatchRequest(BaseModel):
    cv_text: str = Field(..., min_length=50, description="Plain-text CV or résumé")
    top_n: int = Field(5, ge=1, le=25)
    city: str | None = Field(None, description="Optional filter, e.g. 'Sydney'")


class JobMatch(BaseModel):
    job_id: str
    title: str
    company: str | None
    city: str | None
    salary_min: float | None
    salary_max: float | None
    similarity: float
    matched_skills: list[str]
    missing_skills: list[str]


class MatchResponse(BaseModel):
    matches: list[JobMatch]
    cv_skills_detected: list[str]


def load_job_embeddings() -> dict[str, list[float]]:
    if not EMBEDDINGS_PATH.exists():
        return {}
    with open(EMBEDDINGS_PATH) as f:
        return {
            row["job_id"]: row["embedding"]
            for row in (json.loads(line) for line in f if line.strip())
        }


def cosine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Cosine similarity of one vector against a matrix of vectors."""
    a_norm = a / max(float(np.linalg.norm(a)), 1e-12)
    b_norm = b / np.clip(np.linalg.norm(b, axis=1, keepdims=True), 1e-12, None)
    return b_norm @ a_norm


@app.get("/health")
def health() -> dict[str, str | int]:
    con = duckdb.connect(WAREHOUSE, read_only=True)
    n_jobs = con.sql("SELECT count(*) FROM gold.fact_job_posting").fetchone()[0]
    con.close()
    return {"status": "ok", "jobs_indexed": n_jobs, "embeddings": len(load_job_embeddings())}


@app.post("/match", response_model=MatchResponse)
def match(req: MatchRequest) -> MatchResponse:
    job_embeddings = load_job_embeddings()
    if not job_embeddings:
        raise HTTPException(
            status_code=503,
            detail="No job embeddings yet — run transform/semantic_dedup.py first.",
        )

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = client.models.embed_content(
        model=EMBED_MODEL,
        contents=[req.cv_text[:4000]],
        config={"output_dimensionality": EMBED_DIM},
    )
    cv_vec = np.array(resp.embeddings[0].values, dtype=np.float32)

    con = duckdb.connect(WAREHOUSE, read_only=True)
    where = "where l.city = ?" if req.city else ""
    params = [req.city] if req.city else []
    jobs = con.sql(f"""
        select f.job_id, f.title, c.company_name, l.city, f.salary_min, f.salary_max
        from gold.fact_job_posting f
        left join gold.dim_company c on f.company_key = c.company_key
        left join gold.dim_location l on f.location_key = l.location_key
        {where}
    """, params=params).fetchall()

    # Skill vocabulary, so we can report the gap rather than just a score.
    skill_rows = con.sql("""
        select b.job_id, s.skill_name
        from gold.bridge_job_skill b
        join gold.dim_skill s on b.skill_key = s.skill_key
    """).fetchall()
    all_skills = {r[0] for r in con.sql("select skill_name from gold.dim_skill").fetchall()}
    con.close()

    job_skills: dict[str, set[str]] = {}
    for job_id, skill in skill_rows:
        job_skills.setdefault(job_id, set()).add(skill)

    cv_lower = req.cv_text.lower()
    cv_skills = {s for s in all_skills if s.lower() in cv_lower}

    scored = [j for j in jobs if j[0] in job_embeddings]
    if not scored:
        return MatchResponse(matches=[], cv_skills_detected=sorted(cv_skills))

    matrix = np.array([job_embeddings[j[0]] for j in scored], dtype=np.float32)
    sims = cosine(cv_vec, matrix)
    order = np.argsort(-sims)[: req.top_n]

    matches = []
    for idx in order:
        job_id, title, company, city, smin, smax = scored[int(idx)]
        required = job_skills.get(job_id, set())
        matches.append(
            JobMatch(
                job_id=job_id,
                title=title,
                company=company,
                city=city,
                salary_min=smin,
                salary_max=smax,
                similarity=round(float(sims[int(idx)]), 4),
                matched_skills=sorted(required & cv_skills),
                missing_skills=sorted(required - cv_skills),
            )
        )

    return MatchResponse(matches=matches, cv_skills_detected=sorted(cv_skills))
