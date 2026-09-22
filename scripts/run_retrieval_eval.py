#!/usr/bin/env python
"""Retrieval 평가(Hit Rate@5, MRR@5)를 실행하고 evaluation/retrieval/에 결과를 저장한다."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from skala_rag.evaluation.retrieval import run_evaluation, save_report  # noqa: E402


def main() -> None:
    report = run_evaluation()
    save_report(report)
    print(f"Hit Rate@{report.k}: {report.hit_rate:.2%}")
    print(f"MRR@{report.k}: {report.mrr:.3f}")
    print("evaluation/retrieval/results.json, report.md 에 저장했습니다.")
    for r in report.results:
        if not r.hit:
            print(f"  [MISS] {r.id}: {r.query}")


if __name__ == "__main__":
    main()
