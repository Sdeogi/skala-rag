from __future__ import annotations

from copy import deepcopy

from skala_rag.graph.workflow import PipelineServices

TECHS = ("KIVI", "InfiniGen")
FIELDS = {
    "market": ("market_size", "adoption", "ecosystem"),
    "stakeholder": ("competitor_view", "adopter_view", "investor_view"),
    "domain": ("memory", "quality", "latency", "throughput", "integration"),
    "trl": ("trl",),
}
LABELS = {
    "market": ("직접 자료 있음", "상용 서비스 적용 확인", "활발"),
    "stakeholder": ("지지",) * 3,
    "domain": ("적용 가능 보고",) * 4 + ("낮음 보고",),
    "trl": ("TRL 4",),
}


def perspective(name: str, missing: bool = False) -> dict:
    return {
        "perspective": name,
        "technologies": {
            tech: {
                field: {
                    "label": label,
                    "reason": f"{tech} {field} 근거에 따른 설명",
                    "evidence_ids": [] if missing and field == FIELDS[name][0] else [f"{tech}-1"],
                    "conditions": "공개 실험 조건",
                }
                for field, label in zip(FIELDS[name], LABELS[name])
            }
            for tech in TECHS
        },
        "status": "insufficient_evidence" if missing else "complete",
    }


def sample_sources() -> dict:
    return {
        f"{tech}-paper": {
            "title": f"{tech} paper",
            "author_or_org": f"{tech} Authors",
            "published_at": "2024-06-01",
            "venue": "ICML 2024" if tech == "KIVI" else "OSDI 2024",
            "url": f"https://example.org/{tech.lower()}",
            "source_type": "paper",
            "pages": 16,
        }
        for tech in TECHS
    }


def sample_evidence() -> dict:
    return {
        f"{tech}-1": {
            "source_id": f"{tech}-paper",
            "technology": tech,
            "claim": "실험 결과",
            "quote": "fixture quote",
            "location": "p.1",
            "claim_type": "reported_fact",
        }
        for tech in TECHS
    }


def make_services(missing: bool = False, retry=None) -> PipelineServices:
    def technical(state):
        return {"technical_findings": {tech: {"principle": "fixture"} for tech in TECHS}, "evidence": sample_evidence()}

    return PipelineServices(
        prepare=lambda state: {"sources": sample_sources()},
        technical=technical,
        market=lambda state: {"market_analysis": perspective("market", missing)},
        stakeholder=lambda state: {"stakeholder_analysis": perspective("stakeholder")},
        domain=lambda state: {"domain_analysis": perspective("domain")},
        trl=lambda state: {"trl_analysis": perspective("trl")},
        retry=retry,
    )


class FakeModel:
    """Stands in for a chat model with structured output."""

    def __init__(self, response, *, fail: Exception | None = None):
        self.response = response
        self.fail = fail
        self.calls = 0

    def with_structured_output(self, schema, **kwargs):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.fail is not None:
            raise self.fail
        return deepcopy(self.response)
