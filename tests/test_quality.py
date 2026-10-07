from __future__ import annotations

import re
from copy import deepcopy

from conftest import FIELDS, LABELS, TECHS, FakeModel
from langchain_core.messages import AIMessage

from skala_rag.agents.quality import (
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
    return state


def section(state: dict, prefix: str) -> dict:
    return next(item for item in state["report"]["sections"] if item["heading"].startswith(prefix))


def add_paragraph(state: dict, prefix: str, text: str) -> None:
    section(state, prefix)["paragraphs"].append(text)


def numbered(state: dict) -> dict:
    """``[근거 ID]`` 인용을 ``[n]``으로 바꾸고 ``citation_map``을 붙인 State 사본."""
    copy = deepcopy(state)
    mapping: dict[str, str] = {}

    def convert(text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            token = match.group(1)
            if token in copy["evidence"]:
                return f"[{mapping.setdefault(token, str(len(mapping) + 1))}]"
            return match.group(0)

        return re.sub(r"\[([^\[\]]+)\]", replace, text)

    for item in copy["report"]["sections"]:
        if item["heading"].startswith(("REFERENCE", "부록")):
            continue
        item["paragraphs"] = [convert(text) for text in item["paragraphs"]]
        if item.get("table"):
            item["table"]["rows"] = [[convert(cell) for cell in row] for row in item["table"]["rows"]]
    copy["report"]["citation_map"] = {number: evidence_id for evidence_id, number in mapping.items()}
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
    assert {name: item["score"] for name, item in result["items"].items()} == {"groundedness": 5, "neutrality": 5, "bias": 5, "coverage": 5}
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
    by_id, _, _ = evaluate(state)
    by_number, _, _ = evaluate(numbered(state))
    assert by_id == by_number
    broken = deepcopy(state)
    add_paragraph(broken, "5.", "KIVI는 잘 동작한다 [ghost].")
    add_paragraph_numbered = numbered(broken)
    assert evaluate(broken)[0]["items"]["groundedness"]["score"] == 1
    assert evaluate(add_paragraph_numbered)[0]["items"]["groundedness"]["score"] == 1
    out_of_range = numbered(state)
    add_paragraph(out_of_range, "5.", "KIVI는 잘 동작한다 [99].")
    assert evaluate(out_of_range)[0]["items"]["groundedness"]["score"] == 1


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
def test_all_judgments_on_one_source_need_recollection():
    result, _, _ = evaluate(make_state(single_source=True))
    assert result["items"]["bias"]["score"] == 1 and result["action"] == "recollect"
    requests = result["rework_requests"]
    assert requests and all(item["reasons"] == ["missing_evidence"] for item in requests)
    assert all(item["review_reason"] == "단일 출처 의존: 다른 출처의 근거 필요" and item["attempt"] == 0 for item in requests)
    assert all(item["perspective"] != "domain" for item in requests)  # 도메인은 구조적으로 단일 출처
    assert result["instructions"]


def test_domain_single_source_must_be_disclosed_in_limitations():
    undisclosed, _, _ = evaluate(make_state(domain_disclosed=False))
    assert undisclosed["items"]["bias"]["score"] == 3 and undisclosed["action"] == "rewrite_report"
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
    assert result["items"]["bias"]["score"] <= 3


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
    without_citations = re.sub(r"\s*\[[^\[\]]+\]", "", sentence)  # 문장 중간 인용을 생략한 인용
    assert evaluator._locate(without_citations, parsed).text == sentence
    assert evaluator._locate("…" + sentence[:20] + "…", parsed) is not None
    assert evaluator._locate("보고서에 없는 문장이다", parsed) is None
    assert evaluator._locate("", parsed) is None
