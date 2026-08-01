"""
Session 11 — semantic deduplication.

Exact-ID dedup (Session 6) cannot catch the same role reposted by three
recruiters with reworded text. This embeds each posting and clusters by
cosine similarity so those collapse to one canonical record.

Threshold choice is documented in docs/decisions/ADR-001-dedup-threshold.md.
Embeddings are cached to disk, so reruns cost nothing and are idempotent.
"""
import json
import os
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from google import genai

EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 768
BATCH_SIZE = 20
SECONDS_BETWEEN_CALLS = 2.0
TEXT_LIMIT = 1200
THRESHOLD = 0.90  # see ADR-001
CACHE_PATH = Path("data/embeddings.jsonl")


def load_cache() -> dict[str, list[float]]:
    cache = {}
    if CACHE_PATH.exists():
        with open(CACHE_PATH) as f:
            for line in f:
                row = json.loads(line)
                cache[row["job_id"]] = row["embedding"]
    return cache


def embed_missing(client: genai.Client, jobs: list[tuple], cache: dict) -> dict:
    pending = [j for j in jobs if j[0] not in cache]
    print(f"embeddings: {len(cache)} cached, {len(pending)} to compute")

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(pending), BATCH_SIZE):
        batch = pending[i : i + BATCH_SIZE]
        texts = [f"{title}\n{descr[:TEXT_LIMIT]}" for _, title, descr in batch]
        try:
            resp = client.models.embed_content(
                model=EMBED_MODEL,
                contents=texts,
                config={"output_dimensionality": EMBED_DIM},
            )
            with open(CACHE_PATH, "a") as f:
                for (job_id, _, _), emb in zip(batch, resp.embeddings, strict=False):
                    vec = list(emb.values)
                    cache[job_id] = vec
                    f.write(json.dumps({"job_id": job_id, "embedding": vec}) + "\n")
            print(f"  batch {i // BATCH_SIZE + 1}: ok")
        except Exception as e:
            print(f"  batch {i // BATCH_SIZE + 1}: FAILED {type(e).__name__}: {e}")
        time.sleep(SECONDS_BETWEEN_CALLS)
    return cache


def cluster(job_ids: list[str], matrix: np.ndarray, threshold: float) -> dict[str, int]:
    """Single-link agglomerative clustering via union-find on the similarity graph."""
    # Cosine similarity == dot product once rows are L2-normalised.
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    normed = matrix / np.clip(norms, 1e-12, None)
    sim = normed @ normed.T

    parent = list(range(len(job_ids)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    n = len(job_ids)
    for i in range(n):
        for j in range(i + 1, n):
            if sim[i, j] >= threshold:
                union(i, j)

    roots = {}
    assignments = {}
    for idx, job_id in enumerate(job_ids):
        root = find(idx)
        if root not in roots:
            roots[root] = len(roots) + 1
        assignments[job_id] = roots[root]
    return assignments


def main() -> None:
    load_dotenv()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    con = duckdb.connect("warehouse.duckdb")

    jobs = con.sql("""
        SELECT id, coalesce(title, ''), coalesce(description_clean, '')
        FROM silver.job_ads
    """).fetchall()

    cache = embed_missing(client, jobs, load_cache())

    job_ids = [j[0] for j in jobs if j[0] in cache]
    matrix = np.array([cache[jid] for jid in job_ids], dtype=np.float32)
    print(f"clustering {len(job_ids)} postings at threshold {THRESHOLD}")

    assignments = cluster(job_ids, matrix, THRESHOLD)
    # ruff flags this as unused: DuckDB resolves `clusters_df` by name from
    # the enclosing Python scope inside the SQL below.
    clusters_df = pd.DataFrame(  # noqa: F841
        [{"job_id": jid, "cluster_id": cid} for jid, cid in assignments.items()]
    )

    # canonical = lowest job_id in each cluster, so the choice is deterministic
    con.execute("CREATE OR REPLACE TABLE silver.job_clusters AS SELECT * FROM clusters_df")
    con.execute("""
        CREATE OR REPLACE TABLE silver.job_clusters AS
        SELECT
            c.job_id,
            c.cluster_id,
            c.job_id = min(c.job_id) OVER (PARTITION BY c.cluster_id) AS is_canonical
        FROM silver.job_clusters c
    """)

    total = len(assignments)
    distinct = len(set(assignments.values()))
    print(f"\n{total} postings -> {distinct} semantic clusters ({total - distinct} reposts collapsed)")
    con.sql("""
        SELECT cluster_id, count(*) AS n
        FROM silver.job_clusters
        GROUP BY cluster_id HAVING count(*) > 1
        ORDER BY n DESC LIMIT 5
    """).show()


if __name__ == "__main__":
    main()
