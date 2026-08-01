"""
CI gate: fail the build if extraction accuracy regresses.

Thresholds are set just below the current measured values, so an ordinary
prompt tweak passes but a genuine degradation fails. Raise them as accuracy
improves — that is the point of a ratchet.

Current measured (2026-08-01, 14 golden ads matched):
    skills F1        0.815
    seniority acc    0.571   <- known weak, see README
    years acc        0.929
"""
import json
import sys
from pathlib import Path

REPORT = Path("extract/eval_report.json")

THRESHOLDS = {
    "skills_f1": 0.70,
    "seniority_accuracy": 0.50,
    "years_accuracy": 0.85,
}


def main() -> int:
    if not REPORT.exists():
        print(f"FAIL: {REPORT} not found — run extract/evaluate.py and commit the report")
        return 1

    report = json.loads(REPORT.read_text())
    actual = {
        "skills_f1": report["skills"]["f1"],
        "seniority_accuracy": report["seniority_accuracy"],
        "years_accuracy": report["years_accuracy"],
    }

    failures = []
    for metric, floor in THRESHOLDS.items():
        value = actual[metric]
        status = "ok " if value >= floor else "FAIL"
        print(f"{status} {metric:<22} {value:.3f}  (floor {floor:.2f})")
        if value < floor:
            failures.append(metric)

    if failures:
        print(f"\nExtraction accuracy regressed on: {', '.join(failures)}")
        return 1

    print("\nAll extraction accuracy gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
