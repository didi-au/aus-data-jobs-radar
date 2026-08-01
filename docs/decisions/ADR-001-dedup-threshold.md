# ADR-001: Semantic dedup similarity threshold

**Status:** Accepted
**Date:** 2026-08-01

## Context

Exact-ID deduplication (silver layer) collapses 550 scraped records to 482
distinct job IDs. It cannot catch the same underlying role posted separately by
multiple recruiters, or reposted weeks later with reworded copy — those carry
different SEEK IDs and survive as apparent duplicates.

Embedding each posting and clustering by cosine similarity catches those. The
open question is where to set the similarity threshold.

## Decision

**Threshold = 0.90**, single-link clustering over `gemini-embedding-001`
embeddings (768 dimensions) of `title + first 1200 chars of description`.

## Options considered

| Threshold | Behaviour observed |
|---|---|
| 0.85 | Over-merges. Distinct roles at the same employer collapse together — a "Data Analyst" and a "Senior Data Engineer" at one company share enough boilerplate (company blurb, benefits, EEO statement) to cross the line. Loses real postings. |
| **0.90** | **Chosen.** Catches genuine reposts and multi-recruiter listings while keeping distinct roles separate. |
| 0.95 | Too strict. Genuine reposts with rewritten opening paragraphs stay separate, so the duplicates it was built to remove survive. |

## Consequences

- Clusters are stored in `silver.job_clusters` with an `is_canonical` flag
  (lowest `job_id` per cluster, so the choice is deterministic and stable
  across reruns) rather than deleting rows. Nothing is destroyed — downstream
  models filter on `is_canonical` when they want one row per real job.
- Australian job ads share heavy boilerplate (EEO statements, benefits lists),
  which inflates baseline similarity. This is why 0.85 is unsafe here even
  though it is a common default elsewhere.
- Single-link clustering can chain (A~B, B~C ⇒ A,B,C cluster even if A≁C).
  Acceptable at 0.90 given observed cluster sizes; would need revisiting at a
  lower threshold or much larger corpus.
- Embeddings are cached to `data/embeddings.jsonl`, so re-running costs nothing
  and threshold experiments are fast.
