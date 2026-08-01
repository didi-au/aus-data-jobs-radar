"""
Session 10 — evaluation harness.
Scores the LLM extraction against the hand-labelled golden set and writes
extract/eval_report.json. CI enforces thresholds against that report, so a
prompt/model change that quietly degrades accuracy fails the build.

Metrics:
- skills: micro precision / recall / F1 over normalised skill strings
- seniority: accuracy over 4 classes
- visa_friendly: accuracy (NOTE: current golden sample contains no positive
  visa examples, so this measures false-positive rate only — documented)
- years_experience_required: exact-match accuracy (null == null counts)
"""
import json
from pathlib import Path

GOLDEN_PATH = Path("extract/golden_set.jsonl")
CACHE_PATH = Path("data/extract_cache.jsonl")
REPORT_PATH = Path("extract/eval_report.json")


def norm_skill(s: str) -> str:
    return s.strip().lower()


def load_jsonl(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    golden = {row["job_id"]: row for row in load_jsonl(GOLDEN_PATH)}
    extracted = {
        row["job_id"]: row["extraction"] for row in load_jsonl(CACHE_PATH)
    }

    matched = [jid for jid in golden if jid in extracted]
    missing = [jid for jid in golden if jid not in extracted]

    tp = fp = fn = 0
    seniority_hits = visa_hits = years_hits = 0

    for jid in matched:
        g, e = golden[jid], extracted[jid]

        g_skills = {norm_skill(s) for s in g["skills"]}
        e_skills = {norm_skill(s) for s in e["skills"]}
        tp += len(g_skills & e_skills)
        fp += len(e_skills - g_skills)
        fn += len(g_skills - e_skills)

        seniority_hits += g["seniority"] == e["seniority"]
        visa_hits += g["visa_friendly"] == e["visa_friendly"]
        years_hits += g["years_experience_required"] == e["years_experience_required"]

    n = len(matched)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    report = {
        "golden_set_size": len(golden),
        "matched": n,
        "missing_from_extraction": missing,
        "skills": {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
        },
        "seniority_accuracy": round(seniority_hits / n, 3) if n else 0.0,
        "visa_accuracy": round(visa_hits / n, 3) if n else 0.0,
        "visa_note": "golden sample has 0 positive visa examples; measures false-positive rate only",
        "years_accuracy": round(years_hits / n, 3) if n else 0.0,
    }

    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
