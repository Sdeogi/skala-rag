"""Clearly synthetic service fixture for integration smoke tests only."""

from __future__ import annotations

from skala_rag.graph.evidence_check import RUBRICS
from skala_rag.graph.workflow import PipelineServices


SAMPLE_LABELS = {
    "market": {"market_size": "관련 시장 자료만 있음", "adoption": "연구 재현 수준", "ecosystem": "일부 있음"},
    "stakeholder": {"competitor_view": "중립", "adopter_view": "중립", "investor_view": "중립"},
    "domain": {"memory": "조건부 보고", "quality": "조건부 보고", "latency": "조건부 보고", "throughput": "조건부 보고", "integration": "보고 없음"},
    "trl": {"trl": "TRL 4"},
}


def _perspective(name, state):
    return {
        f"{name}_analysis": {
            "perspective": name,
            "technologies": {
                technology: {
                    field: {
                        "label": SAMPLE_LABELS[name][field],
                        "reason": "통합 흐름 검사용 합성 판정",
                        "conditions": "실제 조사 결과가 아닌 fixture",
                        "evidence_ids": [f"sample-{technology}"],
                    }
                    for field in RUBRICS[name]
                }
                for technology in state["run_config"]["technologies"]
            },
            "status": "complete",
        }
    }


def create_services() -> PipelineServices:
    def prepare(state):
        return {"sources": {f"sample-source-{technology}": {"title": f"Synthetic {technology} source", "url": "https://example.org/fixture", "source_type": "fixture"} for technology in state["run_config"]["technologies"]}}

    def technical(state):
        return {
            "technical_findings": {technology: {"principle": "합성 검사용 기술 설명"} for technology in state["run_config"]["technologies"]},
            "evidence": {f"sample-{technology}": {"source_id": f"sample-source-{technology}", "technology": technology, "claim": "합성 테스트", "quote": "실제 자료 아님", "location": "fixture", "claim_type": "reported_fact"} for technology in state["run_config"]["technologies"]},
        }

    return PipelineServices(
        prepare=prepare,
        technical=technical,
        market=lambda state: _perspective("market", state),
        stakeholder=lambda state: _perspective("stakeholder", state),
        domain=lambda state: _perspective("domain", state),
        trl=lambda state: _perspective("trl", state),
        retry=lambda state: {},
    )
