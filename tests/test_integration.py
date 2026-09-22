"""Integration layer tests with stubbed A/B/C branch functions (offline, no model calls)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from skala_rag.graph.workflow import build_graph, initial_state
from skala_rag.integration.services import IntegrationSettings, create_services
from skala_rag.schemas.state import RubricItem

TECHS = ("KIVI", "InfiniGen")


def chunk(evidence_id, tech, page=3, text="This technique reduces peak memory usage by 2.6x while keeping accuracy. More details follow."):
    return SimpleNamespace(evidence_id=evidence_id, source_id=tech, tech_name=tech, page=page, section="Experiments", text=text)


def fake_retrieve(query, tech, k=5):
    return [chunk(f"{tech}-p3-1", tech), chunk(f"{tech}-p4-1", tech, page=4)]


def fake_judge_domain(spec, tech, candidates, model):
    verdict = "낮음 보고" if spec.item_key == "integration" else "조건부 보고"
    return RubricItem(item_key=spec.item_key, tech=tech, verdict=verdict, reason=f"{tech.value} {spec.item_key} stub", evidence_ids=[candidates[0].evidence_id] if candidates else [], conditions="Llama-2-7B, A100")


def fake_judge_stage(spec, tech, candidates, model):
    met = spec.evidence_mode == "rag" or spec.stage_key == "trl_4"
    return SimpleNamespace(
        verdict="충족" if met else "미충족",
        reason=f"{spec.trl_label} stub",
        evidence_ids=[c.evidence_id for c in candidates[:1]] if met else [],
        missing_evidence_note="" if met else f"{spec.trl_label} 근거 없음",
    )


def fake_search(query, max_results, mode, cache_dir=None):
    return [{"url": "https://example.org/repo", "title": "Repo", "content": "..."}]


def fake_fetch(url, mode, cache_dir=None):
    return {"url": url, "title": "Repo page", "raw_content": "The official repository provides reproduction scripts."}


def fake_summarize(source, question, topic="", mode="live", cache_dir=None):
    return {
        "evidence_status": "direct", "quote_verified": True, "claim": "공식 저장소가 재현 스크립트를 제공한다",
        "quote": "provides reproduction scripts", "location": "웹 추출문 1~1행", "source_url": source["url"],
        "source_title": source["title"], "content_hash": "abc", "collected_at": "2026-09-22", "limitation": "",
        "relation_kind": "derived_implementation", "related_entity": "repository",
    }


def fake_technical(tech_names, model=None):
    def record(tech):
        return {"evidence_id": f"{tech}-p1-1", "source_id": tech, "tech_name": tech, "page": 1, "section": "Intro", "claim": f"{tech} claim", "quote": f"{tech} quote", "claim_type": "reported_fact", "experimental_condition": None}

    evidence = {f"{tech}-p1-1": SimpleNamespace(model_dump=lambda tech=tech: record(tech)) for tech in tech_names}
    findings = {
        tech: {
            "tech_name": tech,
            "principle": {"claims": [f"{tech} principle"], "evidence_ids": [f"{tech}-p1-1"]},
            "experimental_setup": {"claims": ["A100"], "evidence_ids": [f"{tech}-p1-1"]},
            "performance": {"claims": ["2.6x memory"], "evidence_ids": [f"{tech}-p1-1"]},
            "limitations": {"claims": ["quality loss"], "evidence_ids": [f"{tech}-p1-1"]},
        }
        for tech in tech_names
    }
    return SimpleNamespace(evidence=evidence, technical_findings=findings, errors=[{"node": "technical_research", "reason": "no_evidence_found"}])


def web_agent(name):
    labels = {
        "market": {"market_size": "관련 시장 자료만 있음", "adoption": "연구 재현 수준", "ecosystem": "일부 있음"},
        "stakeholder": {"competitor_view": "우려", "adopter_view": "우려", "investor_view": "중립"},
    }[name]
    calls = []

    def run(technologies=TECHS, mode="live", **kwargs):
        calls.append(tuple(technologies))
        evidence, sources, judgments = {}, {}, {}
        for tech in technologies:
            evidence_id, source_id = f"web-evidence-{name}-{tech}", f"web-source-{name}"
            evidence[evidence_id] = {"source_id": source_id, "technology": tech, "claim": "c", "quote": "q", "location": "웹", "claim_type": "reported_fact", "conditions": ""}
            sources[source_id] = {"source_id": source_id, "title": "Web", "url": "https://example.org/w", "source_type": "web"}
            judgments[tech] = {field: {"label": label, "reason": "r", "conditions": "", "evidence_ids": [evidence_id]} for field, label in labels.items()}
        return {
            f"{name}_analysis": {"perspective": name, "technologies": judgments, "unresolved_questions": [], "status": "complete"},
            "evidence": evidence, "sources": sources,
            "errors": {f"{name}-x-0": {"node": name, "reason": "search failed", "fatal": False, "recovered": False, "kind": "service"}},
            "metrics": {"web_search_calls": 3},
        }

    run.calls = calls
    return run


@pytest.fixture
def papers_dir(tmp_path):
    papers = [
        {"source_id": tech, "tech_name": tech, "filename": f"{tech}.pdf", "title": f"{tech} paper", "authors": "A et al.", "venue": "ICML 2024", "source_url": f"https://arxiv.org/abs/{tech}", "published_date": "2024-06-01", "collected_at": "2026-09-22", "page_count": 15, "sha256": "x", "source_type": "arxiv_paper"}
        for tech in TECHS
    ]
    (tmp_path / "manifest.json").write_text(json.dumps({"papers": papers}), encoding="utf-8")
    return tmp_path


def make_settings(papers_dir, tmp_path):
    built = []
    settings = IntegrationSettings(
        papers_dir=str(papers_dir), index_dir=str(tmp_path / "idx"),
        retrieve=fake_retrieve, build_index=lambda papers_dir, index_dir: built.append(index_dir),
        technical_research=fake_technical, market_agent=web_agent("market"), stakeholder_agent=web_agent("stakeholder"),
        judge_domain=fake_judge_domain, judge_stage=fake_judge_stage,
        search_results=fake_search, fetch_source=fake_fetch, summarize=fake_summarize,
    )
    return settings, built


def test_prepare_registers_paper_sources_and_builds_missing_index(papers_dir, tmp_path):
    settings, built = make_settings(papers_dir, tmp_path)
    update = create_services(settings).prepare(initial_state(mode="replay"))
    assert update["sources"]["KIVI"]["source_type"] == "paper" and update["sources"]["KIVI"]["pages"] == 15
    assert update["sources"]["KIVI"]["venue"] == "ICML 2024" and update["sources"]["KIVI"]["author_or_org"] == "A et al."
    assert built == [str(tmp_path / "idx")] and update["metrics"]["indexed_pages"] == 30


def test_technical_adapter_converts_evidence_findings_and_errors(papers_dir, tmp_path):
    settings, _ = make_settings(papers_dir, tmp_path)
    update = create_services(settings).technical(initial_state(mode="replay"))
    assert update["evidence"]["KIVI-p1-1"]["technology"] == "KIVI" and update["evidence"]["KIVI-p1-1"]["location"] == "p.1 Intro"
    assert update["technical_findings"]["KIVI"]["principle"] == "KIVI principle"
    assert update["technical_findings"]["KIVI"]["performance"] == ["2.6x memory"] and update["technical_findings"]["KIVI"]["evidence_ids"] == ["KIVI-p1-1"]
    assert update["errors"]["technical-0"]["kind"] == "service"


def test_domain_adapter_produces_graph_format_and_registers_new_chunks(papers_dir, tmp_path):
    settings, _ = make_settings(papers_dir, tmp_path)
    state = initial_state(mode="replay")
    state["evidence"] = {"KIVI-p3-1": {"source_id": "KIVI", "technology": "KIVI", "claim_type": "reported_fact"}}
    update = create_services(settings).domain(state)
    judgment = update["domain_analysis"]["technologies"]["KIVI"]["memory"]
    assert judgment["label"] == "조건부 보고" and judgment["evidence_ids"] == ["KIVI-p3-1"] and judgment["conditions"] == "Llama-2-7B, A100"
    assert update["domain_analysis"]["technologies"]["InfiniGen"]["integration"]["label"] == "낮음 보고"
    assert "KIVI-p4-1" in update["evidence"] and "KIVI-p3-1" not in update["evidence"]
    assert update["evidence"]["KIVI-p4-1"]["technology"] == "KIVI" and update["evidence"]["KIVI-p4-1"]["location"] == "p.4 Experiments"
    assert update["metrics"]["llm_calls"] == 10 and update["domain_analysis"]["status"] == "complete"


def test_domain_repair_rejudges_only_missing_items(papers_dir, tmp_path):
    settings, _ = make_settings(papers_dir, tmp_path)
    state = initial_state(mode="replay")
    previous = {tech: {field: {"label": "보고 없음", "reason": "old", "conditions": "", "evidence_ids": []} for field in ("memory", "quality", "latency", "throughput", "integration")} for tech in TECHS}
    state.update(retry_mode=True, retry_count=1, domain_analysis={"perspective": "domain", "technologies": previous, "status": "insufficient_evidence"})
    state["missing_questions"] = [{"perspective": "domain", "technology": "KIVI", "field": "quality", "question": "?", "reasons": ["missing_evidence"]}]
    update = create_services(settings).domain(state)
    technologies = update["domain_analysis"]["technologies"]
    assert technologies["KIVI"]["quality"]["label"] == "조건부 보고" and technologies["KIVI"]["memory"]["label"] == "보고 없음"
    assert technologies["InfiniGen"]["quality"]["label"] == "보고 없음" and update["metrics"]["llm_calls"] == 1


def test_trl_adapter_builds_stage_details_and_web_evidence(papers_dir, tmp_path):
    settings, _ = make_settings(papers_dir, tmp_path)
    update = create_services(settings).trl(initial_state(mode="replay"))
    judgment = update["trl_analysis"]["technologies"]["KIVI"]["trl"]
    assert judgment["label"] == "TRL 4" and judgment["highest_confirmed"] == "TRL 4"
    assert judgment["stages"]["TRL 5"]["met"] is False and "TRL 5 근거 없음" in judgment["stages"]["TRL 5"]["note"]
    assert judgment["missing_evidence"] == ["[TRL 5] TRL 5 근거 없음"] and judgment["conditions"] == "[TRL 5] TRL 5 근거 없음"
    assert judgment["reason"].startswith("확인된 최고 단계 TRL 4:") and "다음 단계 TRL 5 미충족" in judgment["reason"]
    assert judgment["estimation_note"].startswith("공개 정보 기반 추정")
    web_ids = [identifier for identifier in update["evidence"] if identifier.startswith("web-evidence-")]
    assert web_ids and judgment["evidence_ids"][0] in web_ids
    assert all(source["source_type"] == "web" for source in update["sources"].values())
    assert update["metrics"]["web_search_calls"] == 10 and update["metrics"]["fetch_calls"] == 10 and update["metrics"]["llm_calls"] == 14


def test_web_perspective_repair_keeps_previous_judgments_without_new_searches(papers_dir, tmp_path):
    settings, _ = make_settings(papers_dir, tmp_path)
    services = create_services(settings)
    state = initial_state(mode="live")
    first = services.stakeholder(state)
    state.update(retry_mode=True, retry_count=1, stakeholder_analysis=first["stakeholder_analysis"])
    state["missing_questions"] = [{"perspective": "stakeholder", "technology": "InfiniGen", "field": "adopter_view", "question": "?", "reasons": ["unsupported_claim"]}]
    second = services.stakeholder(state)
    assert settings.stakeholder_agent.calls == [("KIVI",), ("InfiniGen",)]  # no second collection
    assert second["stakeholder_analysis"]["technologies"] == first["stakeholder_analysis"]["technologies"]
    assert second["metrics"] == {"repair_skipped": 1} and second["errors"] == {} and list(first["errors"]) == ["stakeholder-x-0"]


def test_web_perspective_repair_recollects_only_failed_technologies(papers_dir, tmp_path):
    settings, _ = make_settings(papers_dir, tmp_path)
    attempts = {"InfiniGen": 0}

    def flaky(technologies=TECHS, mode="live", **kwargs):
        if "InfiniGen" in technologies:
            attempts["InfiniGen"] += 1
            if attempts["InfiniGen"] == 1:
                raise RuntimeError("웹 검색: results가 list[dict]가 아닙니다")
        return web_agent("stakeholder")(technologies=technologies, mode=mode, **kwargs)

    settings.stakeholder_agent = flaky
    services = create_services(settings)
    state = initial_state(mode="live")
    first = services.stakeholder(state)
    assert first["stakeholder_analysis"]["technologies"]["InfiniGen"]["adopter_view"]["label"] == "미확인"
    state.update(retry_mode=True, retry_count=1, stakeholder_analysis=first["stakeholder_analysis"])
    state["missing_questions"] = [
        {"perspective": "stakeholder", "technology": tech, "field": "adopter_view", "question": "?", "reasons": ["missing_evidence"]} for tech in TECHS
    ]
    second = services.stakeholder(state)
    assert second["stakeholder_analysis"]["technologies"]["InfiniGen"]["adopter_view"]["label"] == "우려"  # re-collected
    assert second["stakeholder_analysis"]["technologies"]["KIVI"] == first["stakeholder_analysis"]["technologies"]["KIVI"]  # kept
    assert second["metrics"]["repair_skipped"] == 1 and attempts["InfiniGen"] == 2


def test_trl_repair_reads_web_pages_from_cache(papers_dir, tmp_path):
    settings, _ = make_settings(papers_dir, tmp_path)
    seen_modes = []

    def search(query, max_results, mode, cache_dir=None):
        seen_modes.append(mode)
        return fake_search(query, max_results, mode, cache_dir)

    settings.search_results = search
    services = create_services(settings)
    state = initial_state(mode="live")
    first = services.trl(state)
    assert set(seen_modes) == {"live"}
    seen_modes.clear()
    state.update(retry_mode=True, retry_count=1, trl_analysis=first["trl_analysis"])
    state["missing_questions"] = [{"perspective": "trl", "technology": "KIVI", "field": "trl", "question": "?", "reasons": ["unsupported_claim"]}]
    services.trl(state)
    assert seen_modes and set(seen_modes) == {"replay"} and len(seen_modes) == 5


def test_web_perspective_failure_degrades_to_unknown_labels(papers_dir, tmp_path):
    settings, _ = make_settings(papers_dir, tmp_path)

    def broken(technologies=TECHS, mode="live", **kwargs):
        if "InfiniGen" in technologies:
            raise FileNotFoundError("캐시가 없습니다")
        return web_agent("market")(technologies=technologies, mode=mode, **kwargs)

    settings.market_agent = broken
    update = create_services(settings).market(initial_state(mode="replay"))
    technologies = update["market_analysis"]["technologies"]
    assert technologies["KIVI"]["adoption"]["label"] == "연구 재현 수준"
    assert set(technologies["InfiniGen"]) == {"market_size", "adoption", "ecosystem"}
    assert technologies["InfiniGen"]["adoption"]["label"] == "미확인" and "FileNotFoundError" in technologies["InfiniGen"]["adoption"]["reason"]
    assert update["errors"]["market-InfiniGen-collect"]["reason"].startswith("FileNotFoundError")
    assert update["market_analysis"]["status"] == "insufficient_evidence" and update["metrics"]["failures"] == 1


def test_full_graph_with_stubbed_branches_completes(papers_dir, tmp_path):
    settings, _ = make_settings(papers_dir, tmp_path)
    result = build_graph(create_services(settings), output_dir=tmp_path / "out").invoke(initial_state(mode="replay"), config={"recursion_limit": 50})
    assert result["evidence_check"]["passed"] and result["retry_count"] == 0
    assert set(result["artifacts"]) == {"markdown", "html", "pdf", "sources", "manifest"}
    manifest = json.loads((tmp_path / "out" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete" and manifest["metrics"]["totals"]["llm_calls"] >= 40
    assert "TRL 4" in result["report"]["markdown"] and "KIVI의 성능 보고: 2.6x memory" in result["report"]["markdown"]
    assert result["sources"]["KIVI"]["source_type"] == "paper" and any(key.startswith("web-source-") for key in result["sources"])


def test_web_search_errors_are_aggregated_per_stage_and_type(papers_dir, tmp_path):
    settings, _ = make_settings(papers_dir, tmp_path)

    def failing_search(query, max_results, mode, cache_dir=None):
        raise FileNotFoundError("캐시가 없습니다")

    settings.search_results = failing_search
    update = create_services(settings).trl(initial_state(mode="replay"))
    assert list(update["errors"]) == ["trl-web-0"]
    reason = update["errors"]["trl-web-0"]["reason"]
    assert reason.startswith("search FileNotFoundError ×10 (") and "trl-trl_4" in reason
    assert update["trl_analysis"]["technologies"]["KIVI"]["trl"]["label"] == "TRL 3"
