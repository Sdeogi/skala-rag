"""Clearly synthetic service fixture for graph flow checks only.

Never use its output as a real evaluation result. It exercises every State
field of the contract (sources with reference metadata, evidence with claim
types, nested technical findings, TRL stage details) so the whole report
pipeline can be run without the A/B/C branches.
"""

from __future__ import annotations

from typing import Any

from skala_rag.graph.schemas import LABELS
from skala_rag.graph.workflow import PipelineServices

SAMPLE_LABELS = {
    "market": {"market_size": "관련 시장 자료만 있음", "adoption": "연구 재현 수준", "ecosystem": "일부 있음"},
    "stakeholder": {"competitor_view": "중립", "adopter_view": "우려", "investor_view": "중립"},
    "domain": {"memory": "적용 가능 보고", "quality": "조건부 보고", "latency": "조건부 보고", "throughput": "조건부 보고", "integration": "낮음 보고"},
    "trl": {"trl": "TRL 4"},
}
FIXTURE_NOTE = "통합 흐름 검사용 합성 판정"


def _sources(technologies: list[str]) -> dict[str, dict[str, Any]]:
    return {
        f"sample-source-{technology}": {
            "title": f"Synthetic {technology} source",
            "author_or_org": "Fixture Authors",
            "published_at": "2024-01-01",
            "venue": "Fixture Venue",
            "url": "https://example.org/fixture",
            "source_type": "fixture",
            "pages": 0,
        }
        for technology in technologies
    }


def _evidence(technologies: list[str]) -> dict[str, dict[str, Any]]:
    return {
        f"sample-{technology}": {
            "source_id": f"sample-source-{technology}",
            "technology": technology,
            "claim": "합성 테스트 주장",
            "quote": "실제 자료 아님 (fixture quote)",
            "location": "fixture p.1",
            "claim_type": "reported_fact",
            "conditions": "fixture 조건",
        }
        for technology in technologies
    }


def _judgment(name: str, field: str, technology: str) -> dict[str, Any]:
    judgment: dict[str, Any] = {
        "label": SAMPLE_LABELS[name][field],
        "reason": FIXTURE_NOTE,
        "conditions": "실제 조사 결과가 아닌 fixture",
        "evidence_ids": [f"sample-{technology}"],
    }
    if name == "trl":
        judgment.update(
            {
                "highest_confirmed": "TRL 4",
                "stages": {
                    "TRL 3": {"met": True, "evidence_ids": [f"sample-{technology}"]},
                    "TRL 4": {"met": True, "evidence_ids": [f"sample-{technology}"]},
                    "TRL 5": {"met": False, "note": "프레임워크 통합 근거 미확인(fixture)"},
                },
                "missing_evidence": ["주류 프레임워크 통합 PR(fixture)"],
                "estimation_note": "공개 정보 기반 추정(fixture)",
            }
        )
    return judgment


def _perspective(name: str, state: dict[str, Any]) -> dict[str, Any]:
    technologies = state["run_config"]["technologies"]
    return {
        f"{name}_analysis": {
            "perspective": name,
            "technologies": {technology: {field: _judgment(name, field, technology) for field in LABELS[name]} for technology in technologies},
            "status": "complete",
        },
        "metrics": {"web_search_calls": 0 if name in ("domain",) else 2, "retrieve_calls": 2 if name in ("domain",) else 0},
    }


def create_services() -> PipelineServices:
    def prepare(state: dict[str, Any]) -> dict[str, Any]:
        return {"sources": _sources(state["run_config"]["technologies"]), "metrics": {"indexed_pages": 0}}

    def technical(state: dict[str, Any]) -> dict[str, Any]:
        technologies = state["run_config"]["technologies"]
        return {
            "technical_findings": {
                technology: {
                    "principle": "합성 검사용 기술 설명",
                    "experiment_conditions": ["fixture 모델", "fixture GPU"],
                    "measurements": [
                        {"metric": "fixture metric", "value": 1, "unit": "x", "baseline": "fixture baseline", "model": "fixture", "hardware": "fixture", "location": "fixture p.1"}
                    ],
                    "limitations": ["실제 자료 아님"],
                    "evidence_ids": [f"sample-{technology}"],
                }
                for technology in technologies
            },
            "evidence": _evidence(technologies),
            "metrics": {"retrieve_calls": 2},
        }

    return PipelineServices(
        prepare=prepare,
        technical=technical,
        market=lambda state: _perspective("market", state),
        stakeholder=lambda state: _perspective("stakeholder", state),
        domain=lambda state: _perspective("domain", state),
        trl=lambda state: _perspective("trl", state),
    )
