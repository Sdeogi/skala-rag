"""라벨링된 20개 질의로 `retrieve_papers`의 Hit Rate@5 / MRR@5를 측정한다(설계서 E.3)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from skala_rag.tools.retrieve import retrieve_papers

from .metrics import hit_at_k, hit_rate_at_k, mean_reciprocal_rank, reciprocal_rank_at_k

DEFAULT_QUESTIONS_PATH = Path(__file__).with_name("questions.json")
DEFAULT_K = 5


@dataclass
class QuestionResult:
    id: str
    tech_name: str
    category: str
    query: str
    expected_evidence_ids: list[str]
    retrieved_evidence_ids: list[str]
    hit: bool
    reciprocal_rank: float


@dataclass
class EvalReport:
    k: int
    hit_rate: float
    mrr: float
    results: list[QuestionResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "k": self.k,
            "hit_rate_at_k": self.hit_rate,
            "mrr_at_k": self.mrr,
            "results": [
                {
                    "id": r.id,
                    "tech_name": r.tech_name,
                    "category": r.category,
                    "query": r.query,
                    "expected_evidence_ids": r.expected_evidence_ids,
                    "retrieved_evidence_ids": r.retrieved_evidence_ids,
                    "hit": r.hit,
                    "reciprocal_rank": r.reciprocal_rank,
                }
                for r in self.results
            ],
        }

    def to_markdown(self) -> str:
        lines = [
            "# Retrieval 평가 결과",
            "",
            f"- Hit Rate@{self.k}: **{self.hit_rate:.2%}**",
            f"- MRR@{self.k}: **{self.mrr:.3f}**",
            f"- 질의 수: {len(self.results)}",
            "",
            "| id | tech | category | hit | RR | query |",
            "|---|---|---|---|---|---|",
        ]
        for r in self.results:
            lines.append(
                f"| {r.id} | {r.tech_name} | {r.category} | {'O' if r.hit else 'X'} "
                f"| {r.reciprocal_rank:.2f} | {r.query} |"
            )
        return "\n".join(lines) + "\n"


def run_evaluation(questions_path: str | Path = DEFAULT_QUESTIONS_PATH, k: int = DEFAULT_K) -> EvalReport:
    payload = json.loads(Path(questions_path).read_text(encoding="utf-8"))
    results: list[QuestionResult] = []

    for question in payload["questions"]:
        expected_ids = set(question["expected_evidence_ids"])
        chunks = retrieve_papers(
            question["query"],
            question["tech_name"],
            k=k,
            query_en=question.get("query_en"),
        )
        retrieved_ids = [c.evidence_id for c in chunks]

        results.append(
            QuestionResult(
                id=question["id"],
                tech_name=question["tech_name"],
                category=question["category"],
                query=question["query"],
                expected_evidence_ids=question["expected_evidence_ids"],
                retrieved_evidence_ids=retrieved_ids,
                hit=hit_at_k(retrieved_ids, expected_ids, k=k),
                reciprocal_rank=reciprocal_rank_at_k(retrieved_ids, expected_ids, k=k),
            )
        )

    return EvalReport(
        k=k,
        hit_rate=hit_rate_at_k([r.hit for r in results]),
        mrr=mean_reciprocal_rank([r.reciprocal_rank for r in results]),
        results=results,
    )


def save_report(report: EvalReport, output_dir: str | Path = "evaluation/retrieval") -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    (output_path / "results.json").write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (output_path / "report.md").write_text(report.to_markdown(), encoding="utf-8")
