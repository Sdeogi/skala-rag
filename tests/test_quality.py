from __future__ import annotations

import json
import re
from copy import deepcopy

from conftest import FIELDS, LABELS, TECHS, FakeModel
from langchain_core.messages import AIMessage

from skala_rag.agents.quality import (
    MARKER_RUN,
    QualityEvaluator,
    QualityResult,
    JudgeVerdict,
    parse_report,
    resolve_citations,
    split_sentences,
)
from skala_rag.agents.report import build_report

DISCLOSURE = "도메인 적용 판정은 기술별 논문 한 편에 의존하는 단일 출처 근거다."


def make_state(*, domain_disclosed: bool = True, single_source: bool = False, all_missing: str | None = None) -> dict:
    """출처가 둘 이상인 근거로 판정을 채운 State와 그 State로 만든 보고서를 돌려준다."""
    evidence, sources = {}, {}
    for tech in TECHS:
        sources[f"{tech}-paper"] = {"title": f"{tech} paper", "source_type": "paper", "url": f"https://arxiv.org/abs/{tech}"}
        for number in (1, 2):
            sources[f"{tech}-web{number}"] = {"title": f"{tech} web {number}", "source_type": "web", "url": f"https://site{number}.example.com/{tech}"}
        for key, source_id in (("p", f"{tech}-paper"), ("w1", f"{tech}-web1"), ("w2", f"{tech}-web2")):
            evidence[f"{tech}-{key}"] = {
                "source_id": source_id,
                "technology": tech,
                "claim": f"{tech} 근거 {key}",
                "quote": f"{tech} quote {key}",
                "location": "p.1",
                "claim_type": "reported_fact",
            }

    state: dict = {
        "run_config": {"technologies": list(TECHS), "domain": "클라우드 LLM 서빙", "mode": "replay"},
        "evidence": evidence,
        "sources": sources,
        "technical_findings": {tech: {"principle": "원리 설명", "evidence_ids": [f"{tech}-p"]} for tech in TECHS},
        "synthesis": {"agreements": [], "conflicts": [], "limitations": [DISCLOSURE] if domain_disclosed else []},
    }
    checks = []
    for name in FIELDS:
        technologies = {}
        for tech in TECHS:
            judgments = {}
            for field, label in zip(FIELDS[name], LABELS[name]):
                ids = [f"{tech}-p"] if name == "domain" or single_source else [f"{tech}-w1", f"{tech}-w2"]
                missing = all_missing == name
                if missing:
                    label, ids = ("보고 없음" if name == "domain" else "미확인"), []
                judgments[field] = {"label": label, "reason": f"{tech} {field} 판정 이유", "evidence_ids": ids, "conditions": "공개 실험 조건"}
                checks.append(
                    {
                        "perspective": name,
                        "technology": tech,
                        "field": field,
                        "passed": not missing,
                        "reasons": ["not_found_label"] if missing else [],
                        "warnings": [],
                        "review_reason": "",
                    }
                )
            technologies[tech] = judgments
        state[f"{name}_analysis"] = {"perspective": name, "technologies": technologies, "status": "complete"}
    state["evidence_check"] = {"passed": all_missing is None, "items": checks}
    state["report"] = build_report(state)
    # 6장의 도메인 단일 출처 언급은 보고서 작성기가 만드는 문구와 무관하게 이 인자로만 정한다
    section(state, "6.")["paragraphs"] = [DISCLOSURE] if domain_disclosed else ["일부 항목은 공개 자료에서 근거를 찾지 못했다."]
    return state


EVIDENCE_SECTION = "부록"  # 보고서 작성기가 근거 목록 절에 붙이는 제목의 앞부분("부록. 근거 목록")


def section(state: dict, prefix: str) -> dict:
    return next(item for item in state["report"]["sections"] if item["heading"].startswith(prefix))


def add_paragraph(state: dict, prefix: str, text: str) -> None:
    section(state, prefix)["paragraphs"].append(text)


def as_evidence_ids(state: dict) -> dict:
    """인용 번호 ``[n]``을 ``[근거 ID]``로 되돌리고 근거 목록 절과 ``citation_map``을 뗀 State 사본(번호 이전 형식 보고서)."""
    copy = deepcopy(state)
    mapping = copy["report"].pop("citation_map")

    def convert(text: str) -> str:
        return re.sub(r"\[(\d{1,3})\]", lambda match: f"[{mapping.get(match.group(1), match.group(1))}]", text)

    copy["report"]["sections"] = [item for item in copy["report"]["sections"] if not item["heading"].startswith(EVIDENCE_SECTION)]
    for item in copy["report"]["sections"]:
        if item["heading"].startswith("REFERENCE"):
            continue
        item["paragraphs"] = [convert(text) for text in item["paragraphs"]]
        if item.get("table"):
            item["table"]["rows"] = [[convert(cell).strip() for cell in row] for row in item["table"]["rows"]]
    return copy


def evaluate(state: dict, **kwargs):
    evaluator = QualityEvaluator(**kwargs)
    output = evaluator(state)
    return output["quality_result"], output["metrics"], evaluator


def verdict(score: int, issues: list | None = None, reasons: list | None = None) -> dict:
    return {"score": score, "reasons": reasons or [], "issues": issues or []}


# ── 인용 해석 ──
def test_resolve_citations_handles_both_formats_and_ignores_tags():
    evidence = {"a-1": {}, "b-2": {}}
    assert resolve_citations("[a-1] 그리고 [b-2]", {}, evidence) == (["a-1", "b-2"], [])
    assert resolve_citations("[1, 2]", {"1": "a-1", "2": "b-2"}, evidence) == (["a-1", "b-2"], [])
    assert resolve_citations("[3]", {"1": "a-1"}, evidence) == ([], ["[3]"])
    assert resolve_citations("[ghost]", {}, evidence) == ([], ["[ghost]"])
    assert resolve_citations("[상충] [REDACTED] [R1] 본문", {"1": "a-1"}, evidence) == ([], [])


def test_split_sentences_attaches_trailing_citation():
    assert split_sentences("첫 문장이다. [1] 둘째 문장이다 [2].") == ["첫 문장이다. [1]", "둘째 문장이다 [2]."]


# ── 문제없는 보고서 ──
def test_clean_report_passes_with_rules_only():
    result, metrics, _ = evaluate(make_state())
    assert result["passed"] and result["action"] == "pass"
    assert {name: item["score"] for name, item in result["items"].items()} == {"groundedness": 5, "neutrality": 5, "bias": 4, "coverage": 5}
    assert all(item["llm_score"] is None for item in result["items"].values())
    assert result["instructions"] == [] and result["rework_requests"] == []
    assert metrics and metrics[-1]["node"] == "quality"
    QualityResult.model_validate(result)


def test_without_judge_the_result_is_deterministic():
    state = make_state()
    first, _, _ = evaluate(state)
    second, _, _ = evaluate(deepcopy(state))
    assert first == second


def test_evaluation_without_evidence_check_still_works():
    state = make_state()
    del state["evidence_check"]
    result, _, _ = evaluate(state)
    assert result["items"]["coverage"]["score"] >= 4


# ── 중립성 ──
def test_explicit_superiority_is_rule_score_one_and_asks_for_rewrite():
    state = make_state()
    add_paragraph(state, "5.", "KIVI가 InfiniGen보다 더 우수하다 [KIVI-w1].")
    result, _, _ = evaluate(state)
    assert result["items"]["neutrality"]["score"] == 1 and result["action"] == "rewrite_report"
    hit = next(item for item in result["instructions"] if item["item"] == "neutrality")
    assert hit["section"] == "5. 시사점" and "더 우수하다" in hit["quote"]


def test_comparative_phrase_lowers_neutrality_without_being_explicit():
    state = make_state()
    add_paragraph(state, "5.", "클라우드 서빙에는 KIVI가 더 적합하다 [KIVI-w1].")
    result, _, _ = evaluate(state)
    assert result["items"]["neutrality"]["rule_score"] == 2 and not result["passed"]


def test_weak_comparative_phrases_are_scored_by_count():
    state = make_state()
    scores = []
    for number in range(5):
        add_paragraph(state, "5.", f"문맥 {number}에서는 InfiniGen이 유리하다 [InfiniGen-w1].")
        scores.append(evaluate(state)[0]["items"]["neutrality"]["rule_score"])
    assert scores == [4, 4, 3, 3, 2]  # 1~2건은 통과, 3건부터 감점


def test_negated_expressions_are_not_counted():
    state = make_state()
    add_paragraph(state, "5.", "이 보고서는 두 기술의 우열이나 도입 추천을 제시하지 않으며 총점이나 순위 대신 조건을 나란히 적는다.")
    result, _, _ = evaluate(state)
    assert result["items"]["neutrality"]["score"] == 5


# ── Groundedness ──
def test_citation_to_missing_evidence_is_groundedness_one():
    state = make_state()
    add_paragraph(state, "5.", "KIVI는 대부분의 모델에서 잘 동작한다 [ghost-evidence].")
    result, _, _ = evaluate(state)
    assert result["items"]["groundedness"]["score"] == 1 and result["action"] == "rewrite_report"
    instruction = result["instructions"][0]
    assert instruction["item"] == "groundedness" and "ghost-evidence" in instruction["problem"] and instruction["section"] == "5. 시사점"


def test_both_citation_formats_give_the_same_result():
    state = make_state()
    assert state["report"]["citation_map"]  # 보고서가 각주 표시 (n)을 쓴다
    old_format = as_evidence_ids(state)
    assert "citation_map" not in old_format["report"] and "[KIVI-w1]" in str(old_format["report"]["sections"])
    assert evaluate(state)[0] == evaluate(old_format)[0]
    for broken in (state, old_format):  # 존재하지 않는 인용은 두 형식 모두 Groundedness 1점
        for token in ("[ghost]", "[99]"):
            copy = deepcopy(broken)
            add_paragraph(copy, "5.", f"KIVI는 잘 동작한다 {token}.")
            assert evaluate(copy)[0]["items"]["groundedness"]["score"] == 1


def test_sentences_without_citation_lower_the_ratio():
    state = make_state()
    for number in range(8):
        add_paragraph(state, "3.", f"InfiniGen은 시나리오 {number}에서 잘 동작한다.")
        add_paragraph(state, "SUMMARY", f"KIVI는 시나리오 {number}에서 잘 동작한다.")
    result, _, _ = evaluate(state)
    assert result["items"]["groundedness"]["rule_score"] <= 3
    assert any("근거 인용을 달거나" in item["fix"] for item in result["instructions"])


def test_meta_sentences_without_citation_are_not_claims():
    state = make_state()
    add_paragraph(state, "SUMMARY", "이 보고서는 두 기술을 같은 틀로 검토했다.")
    add_paragraph(state, "4.1", "이 표는 시장성 판정을 정리했다.")
    result, _, _ = evaluate(state)
    assert result["items"]["groundedness"]["score"] == 5


def test_failed_check_shown_as_confirmed_caps_groundedness():
    state = make_state()
    check = next(item for item in state["evidence_check"]["items"] if (item["perspective"], item["technology"], item["field"]) == ("market", "KIVI", "adoption"))
    check["passed"], check["reasons"] = False, ["unsupported_claim"]
    state["report"] = build_report(state)  # 보고서는 '(근거 미확인)'을 스스로 표시한다
    marked, _, _ = evaluate(state)
    assert marked["items"]["groundedness"]["score"] == 5
    for row in section(state, "4.1")["table"]["rows"]:
        row[2] = row[2].replace(" (근거 미확인)", "")
    unmarked, _, _ = evaluate(state)
    assert unmarked["items"]["groundedness"]["score"] == 3
    assert any("근거 검사를 통과하지 못했는데" in item["problem"] for item in unmarked["instructions"])


# ── 편향 통제 ──
def test_judgments_with_a_single_source_score_three_and_pass_the_bias_line():
    result, _, evaluator = evaluate(make_state(single_source=True))
    bias = result["items"]["bias"]
    assert bias["score"] == 3 and bias["threshold"] == 3 and result["passed"] and result["action"] == "pass"
    assert evaluator.last_measurements["bias"]["mean_source_score"] == 3.0
    assert any("평균 3.0점" in reason for reason in bias["reasons"])
    assert result["rework_requests"] == [] and result["threshold"] == 4  # 다른 항목의 통과선은 그대로 4점


def test_a_missing_disclosure_is_a_rewrite_even_when_judgments_have_single_sources():
    result, _, _ = evaluate(make_state(single_source=True, domain_disclosed=False))
    assert result["items"]["bias"]["score"] == 2 and not result["passed"]
    assert result["action"] == "rewrite_report" and result["rework_requests"] == []  # 출처를 더 모아도 풀리지 않는 미달이다
    assert any("한계점에 밝히지 않음" in item["problem"] for item in result["instructions"])


def test_one_dominant_source_is_recollected_when_single_source_judgments_exist(monkeypatch):
    import skala_rag.agents.quality as quality

    monkeypatch.setattr(quality, "MAX_SOURCE_SHARE_CAP", (0.3, 2))
    result, _, evaluator = evaluate(make_state(single_source=True))
    assert evaluator.last_measurements["bias"]["max_source_share"] > 0.3
    assert result["items"]["bias"]["score"] == 2 and result["action"] == "recollect"
    assert result["rework_requests"] and all(item["perspective"] != "domain" for item in result["rework_requests"])


def test_each_item_reports_its_own_pass_line():
    result, _, _ = evaluate(make_state())
    assert {name: item["threshold"] for name, item in result["items"].items()} == {"groundedness": 4, "neutrality": 4, "bias": 3, "coverage": 4}
    QualityResult.model_validate(result)


def test_the_bias_line_can_be_raised_and_then_single_source_judgments_are_recollected():
    state = make_state(single_source=True)
    result, _, evaluator = evaluate(state, item_thresholds={"bias": 4})
    assert evaluator.pass_line("bias") == 4 and not result["passed"] and result["action"] == "recollect"
    requests = result["rework_requests"]
    assert requests and all(item["reasons"] == ["missing_evidence"] and item["perspective"] != "domain" for item in requests)
    assert all(item["review_reason"] == "단일 출처 의존: 다른 출처의 근거 필요" and item["attempt"] == 0 for item in requests)
    lowered, _, low = evaluate(state, threshold=3)  # 전체 통과선을 낮춰도 항목별 값이 더 높아지지는 않는다
    assert low.pass_line("bias") == 3 and low.pass_line("coverage") == 3 and lowered["passed"]
    requests = result["rework_requests"]
    assert requests and all(item["reasons"] == ["missing_evidence"] for item in requests)
    assert all(item["review_reason"] == "단일 출처 의존: 다른 출처의 근거 필요" and item["attempt"] == 0 for item in requests)
    assert all(item["perspective"] != "domain" for item in requests)  # 도메인은 구조적으로 단일 출처
    assert result["instructions"]


def test_domain_single_source_must_be_disclosed_in_limitations():
    undisclosed, _, _ = evaluate(make_state(domain_disclosed=False))
    assert undisclosed["items"]["bias"]["score"] == 2 and not undisclosed["passed"] and undisclosed["action"] == "rewrite_report"  # 통과선(3점) 아래로 제한
    assert any(item["section"] == "6. 한계점" for item in undisclosed["instructions"])
    assert undisclosed["rework_requests"] == []
    disclosed, _, _ = evaluate(make_state(domain_disclosed=True))
    assert disclosed["items"]["bias"]["score"] >= 4


def test_one_sided_evidence_counts_are_flagged():
    state = make_state()
    for number in range(6):  # KIVI 근거만 보고서에 더 인용되게 한다
        state["evidence"][f"KIVI-x{number}"] = {**state["evidence"]["KIVI-w1"], "claim": f"추가 {number}"}
        add_paragraph(state, "5.", f"KIVI는 항목 {number}에서 보고됐다 [KIVI-x{number}].")
    result, _, evaluator = evaluate(state)
    assert evaluator.last_measurements["bias"]["evidence_count_ratio"] < 0.4
    assert result["items"]["bias"]["score"] == 2 and not result["passed"]  # 통과선(3점) 아래로 제한


# ── 관점 커버리지 ──
def test_a_perspective_without_evidence_fails_coverage_and_asks_for_recollection():
    result, _, _ = evaluate(make_state(all_missing="market"))
    assert result["items"]["coverage"]["score"] <= 3 and result["action"] == "recollect"
    requests = result["rework_requests"]
    assert {item["perspective"] for item in requests} == {"market"}
    assert {(item["technology"], item["field"]) for item in requests} == {(tech, field) for tech in TECHS for field in FIELDS["market"]}
    assert all(item["reasons"] == ["not_found_label"] for item in requests)
    assert all("판정을 뒷받침하는 원문 근거" in item["question"] for item in requests)
    assert any(item["item"] == "coverage" and "시장성" in item["problem"] for item in result["instructions"])


def test_missing_perspective_section_is_coverage_one():
    state = make_state()
    state["report"]["sections"] = [item for item in state["report"]["sections"] if not item["heading"].startswith("4.3")]
    result, _, _ = evaluate(state)
    assert result["items"]["coverage"]["score"] == 1
    assert any("도메인 적용 관점 절이 보고서에 없음" in item["problem"] for item in result["instructions"])


def test_item_missing_from_report_but_confirmed_in_state_is_a_rewrite_not_a_recollection():
    state = make_state()
    table = section(state, "4.1")["table"]
    table["rows"] = [row for row in table["rows"] if not (row[0] == "KIVI" and row[1] == "생태계 지지")]
    for _ in range(4):  # 한 칸 빠진 것만으로는 미달이 아니므로 더 빼서 구간을 낮춘다
        section(state, "4.2")["table"]["rows"].pop()
        section(state, "4.3")["table"]["rows"].pop()
    result, _, _ = evaluate(state)
    assert result["items"]["coverage"]["score"] < 4 and result["action"] == "rewrite_report"
    assert result["rework_requests"] == []
    assert any("표에 없음" in item["problem"] for item in result["instructions"])


def test_neutrality_and_coverage_failing_together_recollect_and_keep_instructions():
    state = make_state(all_missing="trl")
    add_paragraph(state, "5.", "KIVI가 InfiniGen보다 더 우수하다 [KIVI-w1].")
    result, _, _ = evaluate(state)
    assert result["items"]["neutrality"]["score"] == 1 and result["items"]["coverage"]["score"] <= 3
    assert result["action"] == "recollect" and result["rework_requests"]
    assert {item["item"] for item in result["instructions"]} >= {"neutrality", "coverage"}


def test_instructions_are_capped_and_start_with_the_lowest_score():
    state = make_state(all_missing="market", single_source=True, domain_disclosed=False)
    for number in range(12):
        add_paragraph(state, "5.", f"KIVI가 더 우수하다 {number} [KIVI-w1].")
    result, _, _ = evaluate(state)
    assert 0 < len(result["instructions"]) <= 10
    lowest = min(result["items"], key=lambda name: (result["items"][name]["score"], list(result["items"]).index(name)))
    assert result["instructions"][0]["item"] == lowest
    assert {item["item"] for item in result["instructions"]} >= {"neutrality"}


def test_empty_report_is_rewritten():
    state = make_state()
    state["report"] = {}
    result, _, _ = evaluate(state)
    assert not result["passed"] and result["action"] == "rewrite_report"
    assert all(item["score"] == 1 for item in result["items"].values())


# ── LLM Judge ──
def sample_sentence(state: dict) -> str:
    return next(text.text for text in parse_report(state["report"], list(TECHS), state["evidence"]).texts if text.section == "SUMMARY" and "판정됐다" in text.text)


def test_low_judge_score_wins_over_the_rule_score():
    state = make_state()
    quote = sample_sentence(state)
    judge = FakeModel(verdict(2, [{"quote": quote, "problem": "구절보다 넓게 일반화함", "fix": "조건을 덧붙임"}], ["근거가 문장보다 좁음"]))
    result, metrics, _ = evaluate(state, judge_model=judge)
    item = result["items"]["groundedness"]
    assert item["rule_score"] == 5 and item["llm_score"] == 2 and item["score"] == 2
    assert not result["passed"] and result["action"] == "rewrite_report"
    assert any(entry["quote"] == quote and entry["section"] == "SUMMARY" for entry in result["instructions"])
    assert any("근거가 문장보다 좁음" in reason for reason in item["reasons"])
    assert judge.calls <= 6 and sum(event.get("llm_calls", 0) for event in metrics) == judge.calls


def test_judge_cannot_cite_sentences_that_are_not_in_the_report():
    state = make_state()
    judge = FakeModel(verdict(2, [{"quote": "보고서에 없는 문장이다", "problem": "문제", "fix": "삭제"}]))
    result, _, _ = evaluate(state, judge_model=judge)
    assert all("보고서에 없는 문장이다" not in entry["quote"] for entry in result["instructions"])
    item = result["items"]["groundedness"]
    assert item["llm_score"] is None and item["score"] == item["rule_score"]
    assert any("보고서에 없어 버림" in reason for reason in item["reasons"])
    assert result["passed"]


def test_judge_failure_falls_back_to_rule_scores_and_continues():
    state = make_state()
    judge = FakeModel(verdict(5), fail=RuntimeError("boom"))
    result, metrics, _ = evaluate(state, judge_model=judge)
    assert result["passed"] and all(item["llm_score"] is None for item in result["items"].values())
    assert any("Judge 호출" in reason and "실패" in reason for reason in result["items"]["groundedness"]["reasons"])
    errors = [event for event in metrics if event.get("judge_errors")]
    assert errors and "RuntimeError" in errors[0]["error"]


def test_judge_calls_stay_within_the_budget_and_record_tokens():
    state = make_state()
    raw = AIMessage(content="", usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    judge = FakeModel({"parsed": JudgeVerdict(score=5), "raw": raw})
    _, metrics, _ = evaluate(state, judge_model=judge, max_judge_calls=2)
    assert judge.calls == 2
    judged = [event for event in metrics if event.get("purpose", "").endswith("_judge")]
    assert {event["purpose"] for event in judged} == {"groundedness_judge", "neutrality_judge"}
    assert all(event["tokens"]["total_tokens"] == 15 for event in judged)


def test_neutrality_judge_runs_on_summary_and_implications_only():
    state = make_state()
    seen: list[str] = []

    class Spy(FakeModel):
        def invoke(self, messages):
            seen.append(messages[1].content)
            return super().invoke(messages)

    evaluate(state, judge_model=Spy(verdict(5)), max_judge_calls=1)
    assert len(seen) == 1 and "5. 시사점" in seen[0] and "SUMMARY" in seen[0] and "4.1 시장성" not in seen[0]


def test_judge_quotes_are_found_across_cells_citations_and_sentences():
    state = make_state()
    parsed = parse_report(state["report"], list(TECHS), state["evidence"])
    evaluator = QualityEvaluator()
    row = next(unit for unit in parsed.units if unit.kind == "row")
    cross_cells = f"{row.cells['항목']} | {row.cells['판정']}"  # 칸 둘에 걸친 인용
    assert evaluator._locate(cross_cells, parsed).text == row.cells["판정 이유"]
    sentence = sample_sentence(state)
    without_citations = MARKER_RUN.sub("", re.sub(r"\s*\[[^\[\]]+\]", "", sentence))  # 각주 표시(범위 포함)를 생략한 인용
    assert evaluator._locate(without_citations, parsed).text == sentence
    assert evaluator._locate("…" + sentence[:20] + "…", parsed) is not None
    assert evaluator._locate("보고서에 없는 문장이다", parsed) is None
    assert evaluator._locate("", parsed) is None


def test_bias_score_follows_the_number_of_sources_per_judgment():
    base = make_state()
    assert evaluate(base)[0]["items"]["bias"]["score"] == 4  # 전부 출처 2개: 4점
    mixed = make_state()
    for name in ("market", "stakeholder", "trl"):  # 일부는 출처 하나, 일부는 셋
        for tech, judgments in mixed[f"{name}_analysis"]["technologies"].items():
            for index, judgment in enumerate(judgments.values()):
                judgment["evidence_ids"] = [f"{tech}-w1"] if index % 2 else [f"{tech}-w1", f"{tech}-w2", f"{tech}-p"]
    result, _, evaluator = evaluate(mixed)
    histogram = evaluator.last_measurements["bias"]["judgments_by_source_count"]
    assert histogram["1"] > 0 and histogram["3+"] > 0 and histogram["2"] == 0
    assert result["items"]["bias"]["score"] in (3, 4)
    assert 3.0 < evaluator.last_measurements["bias"]["mean_source_score"] < 5.0


# ── 각주 표시와 각주 절 ──
def footnote_rows(state: dict) -> list[list[str]]:
    return section(state, EVIDENCE_SECTION)["table"]["rows"]


def test_report_with_footnotes_has_no_inline_tokens_and_every_marker_is_listed():
    state = make_state()
    report = state["report"]
    assert report["citation_map"] and footnote_rows(state)
    body = "\n".join(p for item in report["sections"] if not item["heading"].startswith((EVIDENCE_SECTION, "REFERENCE")) for p in item["paragraphs"])
    assert "[KIVI-" not in body and "[InfiniGen-" not in body  # 근거 ID가 문장 중간에 끼지 않는다
    parsed = parse_report(report, list(TECHS), state["evidence"])
    assert set(parsed.footnotes) == set(report["citation_map"]) and parsed.references and not parsed.unknown
    result, _, evaluator = evaluate(state)
    assert evaluator.last_measurements["groundedness"]["footnote_problems"] == 0 and result["items"]["groundedness"]["score"] == 5


def test_list_numbers_and_years_are_not_read_as_footnote_markers():
    evidence = {"a-1": {}}
    citation_map = {"1": "a-1"}
    assert resolve_citations("(2) 둘째 항목이다(1).", citation_map, evidence, parens=True) == (["a-1"], [])  # 맨 앞 (2)는 목록 번호
    assert resolve_citations("KIVI(2024)는 발표됐다.", citation_map, evidence, parens=True) == ([], [])
    assert resolve_citations("본문이다(1)(1).", citation_map, evidence, parens=True) == (["a-1"], [])
    assert resolve_citations("본문이다(1, 2).", citation_map, evidence, parens=True) == (["a-1"], ["(2)"])
    assert resolve_citations("본문이다(1).", {}, evidence, parens=True) == ([], [])  # citation_map이 없으면 (1)은 인용이 아니다
    assert resolve_citations("본문이다(1).", citation_map, evidence) == ([], [])  # 인용을 쓰지 않는 장
    assert resolve_citations("본문이다(1).", citation_map, evidence, parens=True) == (["a-1"], [])


def test_enumerations_in_static_sections_do_not_count_as_citations():
    state = make_state()
    add_paragraph(state, "6.", "설계는 (1) 대칭 조사, (2) 반례 질의, (99) 라벨 통제로 이뤄진다.")
    add_paragraph(state, "5.", "(99) 첫 항목: KIVI는 잘 동작한다(1).")
    result, _, _ = evaluate(state)
    assert result["items"]["groundedness"]["score"] == 5


def test_marker_to_a_missing_footnote_is_an_untraceable_citation():
    state = make_state()
    state["report"]["sections"] = [item for item in state["report"]["sections"] if not item["heading"].startswith(EVIDENCE_SECTION)]
    result, _, _ = evaluate(state)
    assert result["items"]["groundedness"]["score"] == 1 and result["action"] == "rewrite_report"
    assert any("각주 절이 없음" in item["problem"] for item in result["instructions"])
    state = make_state()
    removed = "(" + footnote_rows(state).pop(0)[0].strip("[]()") + ")"  # 평가기는 번호를 (n)으로 적어 알린다
    result, _, _ = evaluate(state)
    assert result["items"]["groundedness"]["score"] == 1
    assert any(removed in item["problem"] and "각주가 없음" in item["problem"] for item in result["instructions"])


def test_footnote_with_unregistered_or_missing_source_is_untraceable():
    state = make_state()
    footnote_rows(state)[0][2] = "미등록"
    assert evaluate(state)[0]["items"]["groundedness"]["score"] == 1
    state = make_state()
    state["report"]["sections"] = [item for item in state["report"]["sections"] if not item["heading"].startswith("REFERENCE")]
    result, _, _ = evaluate(state)
    assert result["items"]["groundedness"]["score"] == 1
    assert any("REFERENCE에 없음" in item["problem"] for item in result["instructions"])


def test_footnote_that_disagrees_with_the_evidence_caps_groundedness_at_two():
    wrong_quote = make_state()
    footnote_rows(wrong_quote)[0][-1] = "근거에 없는 전혀 다른 문장이 인용 구절로 적혀 있다"
    result, _, _ = evaluate(wrong_quote)
    assert result["items"]["groundedness"]["score"] == 2 and not result["passed"]
    assert any("인용 구절이 근거의 원문과 다름" in item["problem"] for item in result["instructions"])
    wrong_technology = make_state()
    row = footnote_rows(wrong_technology)[0]
    row[1] = "InfiniGen" if row[1] == "KIVI" else "KIVI"
    assert evaluate(wrong_technology)[0]["items"]["groundedness"]["score"] == 2
    wrong_source = make_state()
    row = footnote_rows(wrong_source)[0]
    other = next(label for label in ("[R1]", "[R2]") if not row[2].startswith(label))
    row[2] = other + " 다른 출처"
    assert evaluate(wrong_source)[0]["items"]["groundedness"]["score"] == 2


def test_empty_quote_column_from_the_length_budget_is_not_a_mismatch():
    state = make_state()
    for row in footnote_rows(state):
        row[-1] = ""  # 쪽수 제한으로 인용 구절 칸을 비운 판
    result, _, _ = evaluate(state)
    assert result["items"]["groundedness"]["score"] == 5


# ── Judge 점수에 반영하는 장 ──
class ChapterJudge(FakeModel):
    """``low`` 장의 묶음에는 낮은 점수와 그 묶음의 첫 문장에 대한 지적을, 나머지에는 5점을 주는 가짜 Judge."""

    def __init__(self, low: tuple[str, ...], score: int = 2):
        super().__init__({})
        self.low, self.score = low, score
        self.seen: list[str] = []  # 호출마다 묶음이 속한 장

    def invoke(self, messages):
        self.calls += 1
        payload = json.loads(messages[1].content)
        sentences = payload.get("sentences") or []
        chapter = sentences[0]["section"] if sentences else ""
        self.seen.append(chapter)
        if any(chapter.startswith(prefix) for prefix in self.low):
            return {"score": self.score, "reasons": ["구절보다 넓게 서술함"], "issues": [{"quote": sentences[0]["text"], "problem": "근거 구절에 없는 서술", "fix": "구절 범위로 줄임"}]}
        return {"score": 5, "reasons": [], "issues": []}


def state_with_cited_chapter_five() -> dict:
    state = make_state()
    add_paragraph(state, "5.", "KIVI는 대부분의 시나리오에서 보고됐다(1).")
    return state


def test_judge_flags_in_chapters_three_and_four_are_noted_but_not_scored():
    state = state_with_cited_chapter_five()
    judge = ChapterJudge(low=("3.", "4."))
    result, _, _ = evaluate(state, judge_model=judge)
    item = result["items"]["groundedness"]
    assert item["llm_score"] == 5 and item["score"] == 5 and result["passed"] and result["action"] == "pass"
    assert result["instructions"] == []  # 작성기가 못 고치는 장이라 수정 지시를 만들지 않는다
    notes = [reason for reason in item["reasons"] if reason.startswith("참고(점수·수정 지시에 반영 안 함)")]
    assert any("3장" in note for note in notes) and any("4장" in note for note in notes)
    assert any(chapter.startswith("3.") for chapter in judge.seen) and any(chapter.startswith("4.") for chapter in judge.seen)  # Judge는 호출한다


def test_judge_flags_in_summary_and_chapter_five_are_scored_and_become_instructions():
    for chapter, heading in (("SUMMARY", "SUMMARY"), ("5.", "5. 시사점")):
        result, _, _ = evaluate(state_with_cited_chapter_five(), judge_model=ChapterJudge(low=(chapter,)))
        item = result["items"]["groundedness"]
        assert item["llm_score"] == 2 and item["score"] == 2 and not result["passed"] and result["action"] == "rewrite_report"
        assert any(entry["section"] == heading and entry["problem"] == "근거 구절에 없는 서술" for entry in result["instructions"])
        assert not any(reason.startswith("참고(") for reason in item["reasons"])


def test_a_short_judge_budget_goes_to_the_chapters_that_count():
    judge = ChapterJudge(low=("5.",))
    result, _, _ = evaluate(state_with_cited_chapter_five(), judge_model=judge, max_judge_calls=3)  # 중립성 1회를 빼면 Groundedness는 2회
    called = [chapter for chapter in judge.seen if chapter]
    assert len(called) == 2 and called[0] == "SUMMARY" and called[1].startswith("5.")  # 3·4장보다 5장이 먼저 호출된다
    assert result["items"]["groundedness"]["llm_score"] == 2 and result["action"] == "rewrite_report"
    assert any("호출 예산 때문에" in reason for reason in result["items"]["groundedness"]["reasons"])


def test_a_failed_reference_call_does_not_touch_the_score():
    class FailsOnReference(ChapterJudge):
        def invoke(self, messages):
            payload = json.loads(messages[1].content)
            sentences = payload.get("sentences") or []
            if sentences and sentences[0]["section"].startswith(("3.", "4.")):
                self.calls += 1
                raise RuntimeError("boom")
            return super().invoke(messages)

    result, metrics, _ = evaluate(state_with_cited_chapter_five(), judge_model=FailsOnReference(low=()))
    item = result["items"]["groundedness"]
    assert item["llm_score"] == 5 and result["passed"]
    assert any("참고용 Groundedness Judge 호출" in reason and "실패" in reason for reason in item["reasons"])
    assert any(event.get("judge_errors") for event in metrics)


def test_neutrality_instructions_target_only_the_expressions_that_lowered_the_score():
    state = make_state()
    add_paragraph(state, "5.", "KIVI가 InfiniGen보다 더 우수하다(1).")  # 명시 표현이면서 강한 비교 표현이기도 하다
    add_paragraph(state, "5.", "긴 문맥에서는 InfiniGen이 유리하다고 논문이 보고한다(1).")  # 약한 비교 표현 1건: 정당한 보고 문장
    result, _, _ = evaluate(state)
    quotes = [entry["quote"] for entry in result["instructions"] if entry["item"] == "neutrality"]
    assert quotes == ["KIVI가 InfiniGen보다 더 우수하다(1)."]  # 같은 문장을 한 번만, 약한 표현은 제외


def test_weak_expressions_get_instructions_only_when_they_alone_fail_the_item():
    state = make_state()
    for number in range(3):
        add_paragraph(state, "5.", f"문맥 {number}에서는 InfiniGen이 유리하다(1).")
    result, _, _ = evaluate(state)
    assert result["items"]["neutrality"]["rule_score"] == 3 and not result["passed"]
    assert len([entry for entry in result["instructions"] if entry["item"] == "neutrality"]) == 3


# ── 범위 표기 (1)-(7) ──
def test_ranges_are_expanded_in_every_notation():
    evidence = {f"id{number}": {} for number in range(1, 11)}
    citation_map = {str(number): f"id{number}" for number in range(1, 11)}

    def numbers(text, **kwargs):
        ids, unknown = resolve_citations(text, citation_map, evidence, **kwargs)
        return [int(identifier[2:]) for identifier in ids], unknown

    assert numbers("보고됐다(1)-(7).", parens=True) == (list(range(1, 8)), [])
    assert numbers("보고됐다(1)-(3), (5)-(7), (9).", parens=True) == ([1, 2, 3, 5, 6, 7, 9], [])
    assert numbers("보고됐다(2-5).", parens=True) == ([2, 3, 4, 5], [])
    assert numbers("보고됐다 [1]-[7].") == (list(range(1, 8)), [])  # 대괄호 표기는 인용을 쓰는 모든 장에서 읽는다
    assert numbers("보고됐다 [2-5].") == ([2, 3, 4, 5], [])
    assert numbers("보고됐다(1)(2).", parens=True) == ([1, 2], [])
    assert numbers("(2) 둘째 항목이다(1)-(3).", parens=True) == ([1, 2, 3], [])  # 문단 맨 앞 (2)는 목록 번호
    assert numbers("보고됐다(1)-(7).") == ([], [])  # 인용을 쓰지 않는 장의 (n)은 읽지 않는다
    assert numbers("보고됐다(1)-(99).", parens=True) == ([], ["(1)-(99)"])  # 끝이 citation_map 밖
    assert numbers("보고됐다(7)-(1).", parens=True) == ([], ["(7)-(1)"])  # 거꾸로 된 범위
    assert numbers("보고됐다 [1]-[99].") == ([], ["[1]-[99]"])


def state_with_a_five_evidence_judgment() -> dict:
    state = make_state()
    for number in range(1, 6):
        state["evidence"][f"X-{number}"] = {**state["evidence"]["KIVI-w1"], "claim": f"추가 근거 {number}", "quote": f"extra quote {number}"}
    state["market_analysis"]["technologies"]["KIVI"]["market_size"]["evidence_ids"] = [f"X-{number}" for number in range(1, 6)]
    state["report"] = build_report(state)
    section(state, "6.")["paragraphs"] = [DISCLOSURE]
    return state


def test_every_number_in_a_run_of_citations_is_verified():
    # 보고서 데이터는 번호마다 대괄호 하나를 쓴다([1] [2] [3] [4] [5]). 범위로 묶는 것은 PDF·HTML을 그릴 때뿐이다.
    state = state_with_a_five_evidence_judgment()
    cell = next(row[-1] for row in section(state, "4.1")["table"]["rows"] if row[0] == "KIVI" and row[1] == "시장 규모와 성장")
    numbers = [int(number) for number in re.findall(r"\[(\d+)\]", cell)]
    assert len(numbers) == 5 and numbers == list(range(numbers[0], numbers[0] + 5)) and re.fullmatch(r"(?:\[\d+\] ?){5}", cell)
    result, _, evaluator = evaluate(state)
    assert evaluator.last_measurements["groundedness"]["footnote_problems"] == 0 and result["items"]["groundedness"]["score"] == 5
    middle = str(numbers[2])  # 가운데 번호의 근거 목록 행을 지우면 잡아야 한다
    footnote_rows(state)[:] = [row for row in footnote_rows(state) if row[0] != f"[{middle}]"]
    broken, _, evaluator = evaluate(state)
    assert broken["items"]["groundedness"]["score"] == 1
    assert any(f"({middle})" in item["problem"] and "각주가 없음" in item["problem"] for item in broken["instructions"])


def test_a_range_to_a_number_that_does_not_exist_is_an_unknown_citation():
    state = state_with_a_five_evidence_judgment()
    add_paragraph(state, "5.", "KIVI는 여러 조건에서 보고됐다(1)-(99).")
    result, _, _ = evaluate(state)
    assert result["items"]["groundedness"]["score"] == 1
    assert any("(1)-(99)" in item["problem"] for item in result["instructions"])


def test_judge_quotes_without_citation_numbers_are_still_found():
    state = state_with_a_five_evidence_judgment()
    parsed = parse_report(state["report"], list(TECHS), state["evidence"])
    sentence = next(text.text for text in parsed.texts if re.search(r"\[\d+\]", text.text) and text.where.startswith("문단"))
    quote = re.sub(r"\s*\[\d+\]", "", sentence)  # Judge가 인용 번호를 빼고 옮긴 문장
    assert "[" not in quote and QualityEvaluator()._locate(quote, parsed).text == sentence


def test_paper_notation_in_brackets_is_not_read_as_a_citation():
    evidence = {"KIVI-p3-12": {}, "e1": {}}
    citation_map = {"1": "KIVI-p3-12"}
    assert resolve_citations("슬라이스 X[l-r:]와 [i:j], [n], [k] 표기를 쓴다 [1].", citation_map, evidence) == (["KIVI-p3-12"], [])
    assert resolve_citations("근거 [e1]과 없는 근거 [ghost-evidence], [KIVI-p9-99].", citation_map, evidence) == (["e1"], ["[ghost-evidence]", "[KIVI-p9-99]"])
