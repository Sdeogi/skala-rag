"""Grounded Korean report construction and artifact serialization.

Chapter order follows the assignment's reference outline: SUMMARY (<= half a
page), 1 분석 배경, 2 기술 선정, 3 기술 개요, 4 관점별 평가, 5 시사점, 6 한계점,
appendix of evidence, REFERENCE (only sources actually cited). Every sentence
about a judgment carries its evidence IDs. The same section model feeds the
Markdown, HTML and PDF renderers so the three outputs cannot diverge.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from skala_rag.graph.schemas import FIELD_TITLES, LABELS, PERSPECTIVE_TITLES, PERSPECTIVES, TRL_DISCLAIMER
from skala_rag.graph.state import GraphState, aggregate_metrics, collect_conflicts

from .korean import josa
from .report_static import background_paragraphs, selection_paragraphs
from .synthesis import limitation_lines

logger = logging.getLogger(__name__)

SUMMARY_LIMIT = 1200  # roughly half an A4 page of Korean text
QUOTE_LIMIT = 300
KEY_FIELDS = (("market", "adoption"), ("stakeholder", "adopter_view"), ("domain", "memory"), ("trl", "trl"))
JUDGMENT_COLUMNS = ["기술", "항목", "판정", "판정 이유", "성립 조건", "근거"]
MEASUREMENT_COLUMNS = ["기술", "지표", "값", "비교 기준", "측정 조건", "출처 위치"]
PERSPECTIVE_NOTES = {
    "market": "판정 라벨은 자료가 기술을 직접 다루는지(시장 규모와 성장), 실제 제품·서비스·프레임워크 적용 여부(상용화와 채택 현황), 후속 연구·파생 구현·표준화 움직임(생태계 지지)을 뜻한다. 같은 발표를 옮겨 쓴 기사 여러 건은 근거 하나로 센다.",
    "stakeholder": "이 관점은 실제 발언만 근거로 삼는다. 발언 주체와 시점은 부록 근거 목록에 기록하며, 에이전트가 추론한 예상 반응은 inference로 표시해 실제 발언과 분리한다.",
    "domain": "판정 라벨은 에이전트의 판단이 아니라 자료의 평가를 옮긴 것이다. 조건부 보고에는 자료가 밝힌 조건을 그대로 적고, 두 논문의 실험 조건이 다르면 각 조건을 나란히 제시한다. 비용은 자료가 직접 다룬 경우에만 기록한다.",
    "trl": "TRL은 NASA의 9단계 척도를 클라우드 서빙 소프트웨어 기술에 맞게 대응시켜 재현, 통합, 배포, 운영의 증거를 각 단계에 배정한 것이다. 증거가 두 단계에 걸치면 범위로 표시한다.",
}
BIAS_CONTROLS = (
    "본 시스템은 확증편향을 막기 위해 (1) 모든 질문을 두 기술에 같은 문장으로 던지고 기술별 필터로 따로 검색하는 대칭 조사, "
    "(2) 장점을 찾는 검색마다 limitation·issue 검색을 짝지어 실행하는 반례 질의, (3) 모든 근거에 reported_fact·inference·unverified "
    "주장 유형 표시, (4) 근거를 찾지 못한 항목을 지어내지 않고 미확인으로 남기는 미확인 라벨, (5) 총점이나 순위 대신 관점 간 "
    "상충 쌍과 성립 조건으로만 서술하는 종합 형식을 적용하도록 설계됐다. 문서와 웹 본문의 지시문은 데이터로만 취급했다."
)
PRIVATE_PATTERNS = (
    re.compile(r"\b(?:sk|tvly)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}\b", re.IGNORECASE),
    re.compile(r"(?i)(?:api[_-]?key|token)=([^\s&]+)"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b"),
)
FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/Library/Fonts/NanumGothic.ttf",
    "~/Library/Fonts/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
    "/usr/share/fonts/nanum/NanumGothic.ttf",
    "C:/Windows/Fonts/malgun.ttf",
)
FALLBACK_CID_FONT = "HYSMyeongJo-Medium"
_FONT_NAME: str | None = None


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        for pattern in PRIVATE_PATTERNS:
            value = pattern.sub("[REDACTED]", value)
        return value
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    return value


def _clip(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _citations(ids: list[str], evidence: dict[str, Any]) -> str:
    return " ".join(f"[{identifier}]" for identifier in dict.fromkeys(ids) if identifier in evidence)


def _section(heading: str, paragraphs: list[str], table: dict[str, Any] | None = None, level: int = 1) -> dict[str, Any]:
    return {"heading": heading, "paragraphs": [str(item) for item in paragraphs], "table": table, "level": level}


def _passed_items(state: GraphState) -> tuple[bool, set[tuple[str, str, str]]]:
    items = (state.get("evidence_check") or {}).get("items") or []
    return bool(items), {(item["perspective"], item["technology"], item["field"]) for item in items if item.get("passed")}


def _judgment(state: GraphState, perspective: str, technology: str, field: str) -> dict[str, Any] | None:
    result = state.get(f"{perspective}_analysis") or {}
    judgment = ((result.get("technologies") or {}).get(technology) or {}).get(field)
    return judgment if isinstance(judgment, dict) else None


def deterministic_summary(state: GraphState) -> list[str]:
    """Rule-based SUMMARY: key judgments per technology, pair counts, gaps, TRL notice."""
    config = state["run_config"]
    technologies = config["technologies"]
    evidence = state.get("evidence") or {}
    synthesis = state.get("synthesis") or {}
    has_checks, passed = _passed_items(state)
    named = " ".join(josa(name, "과", "와") for name in technologies[:-1]) + (" " if len(technologies) > 1 else "") + josa(technologies[-1], "을", "를")
    sentences: list[str] = []
    if config.get("fixture"):
        sentences.append("합성 fixture 실행: 이 보고서는 실제 논문·웹 조사 결과가 아니다.")
    sentences.append(
        f"{config.get('domain', '')}에서 KV cache 병목을 줄이는 {named} 시장성, 이해관계자, "
        "도메인 적용, 기술 성숙도의 네 관점으로 검토했다. 각 판정은 확인된 근거와 성립 조건을 함께 제시한다."
    )
    for technology in technologies:
        parts: list[str] = []
        ids: list[str] = []
        for perspective, field in KEY_FIELDS:
            judgment = _judgment(state, perspective, technology, field)
            if judgment is None or (has_checks and (perspective, technology, field) not in passed):
                continue
            parts.append(f"{PERSPECTIVE_TITLES[perspective]} 관점의 {FIELD_TITLES[field]} '{judgment.get('label') or '미확인'}'")
            ids.extend(judgment.get("evidence_ids") or [])
        if parts:
            cite = _citations(ids, evidence)
            sentences.append(f"{josa(technology, '은', '는')} " + ", ".join(parts) + f"로 판정됐다{(' ' + cite) if cite else ''}.")
        else:
            sentences.append(f"{josa(technology, '은', '는')} 근거가 확인된 핵심 판정이 없어 4장과 6장을 참고해야 한다.")
    conflicts = synthesis.get("conflicts") or []
    agreements = synthesis.get("agreements") or []
    if conflicts or agreements:
        text = f"관점 간 상충 쌍 {len(conflicts)}개와 일치 쌍 {len(agreements)}개를 확인했다."
        if conflicts:
            top = conflicts[0]
            left, right = top["first"], top["second"]
            cite = _citations(left["evidence_ids"] + right["evidence_ids"], evidence)
            text += (
                f" 대표 상충: {top['technology']}에 대해 {PERSPECTIVE_TITLES.get(left['perspective'], left['perspective'])} 관점은 "
                f"'{left['label']}', {PERSPECTIVE_TITLES.get(right['perspective'], right['perspective'])} 관점은 '{right['label']}'로 "
                f"판정했고 두 판정은 서로 다른 조건에서 성립한다{(' ' + cite) if cite else ''}."
            )
        sentences.append(text)
    missing = len(state.get("missing_questions") or [])
    if missing:
        sentences.append(f"근거를 확인하지 못한 항목 {missing}개는 6장 한계점에 정리했다.")
    sentences.append(TRL_DISCLAIMER + " 이 보고서는 두 기술의 우열이나 도입 추천을 제시하지 않는다.")
    text = " ".join(sentences)
    if len(text) > SUMMARY_LIMIT:
        cut = text.rfind(". ", 0, SUMMARY_LIMIT)
        text = text[: cut + 1] if cut > 0 else text[:SUMMARY_LIMIT]
    return [text]


def _technical_section(state: GraphState) -> tuple[list[str], dict[str, Any] | None]:
    evidence = state.get("evidence") or {}
    findings_all = state.get("technical_findings") or {}
    known = {"principle", "experiment_conditions", "measurements", "limitations", "evidence_ids"}
    paragraphs: list[str] = []
    rows: list[list[str]] = []
    for technology in state["run_config"]["technologies"]:
        findings = findings_all.get(technology) or {}
        if not findings:
            paragraphs.append(f"{technology}: 기술 조사 결과 미확인")
            continue
        cite = _citations(list(findings.get("evidence_ids") or []), evidence)
        written = False
        if findings.get("principle"):
            paragraphs.append(f"{technology}의 핵심 원리: {findings['principle']}" + (f" 근거: {cite}" if cite else ""))
            written = True
        if findings.get("experiment_conditions"):
            paragraphs.append(f"{technology}의 실험 조건: " + "; ".join(str(item) for item in findings["experiment_conditions"]))
            written = True
        if findings.get("limitations"):
            paragraphs.append(f"{technology}의 한계: " + "; ".join(str(item) for item in findings["limitations"]))
            written = True
        extras = []
        for key, value in findings.items():
            if key in known or value in (None, "", [], {}):
                continue
            rendered = value if isinstance(value, (str, int, float)) else json.dumps(value, ensure_ascii=False, default=str)
            extras.append(f"{key}: {_clip(rendered, 300)}")
        if extras:
            paragraphs.append(f"{technology}의 추가 조사 항목: " + "; ".join(extras))
            written = True
        if not written:
            paragraphs.append(f"{technology}: 구조화된 기술 조사 결과 있음(세부 항목 미기재)")
        for measurement in findings.get("measurements") or []:
            if not isinstance(measurement, dict):
                continue
            value = " ".join(str(item) for item in (measurement.get("value"), measurement.get("unit")) if item not in (None, ""))
            conditions = ", ".join(
                f"{label} {measurement[key]}"
                for key, label in (("model", "모델"), ("hardware", "하드웨어"), ("context_length", "문맥"), ("batch_size", "배치"), ("precision", "정밀도"))
                if measurement.get(key)
            )
            rows.append(
                [
                    technology,
                    str(measurement.get("metric") or "지표 미기재"),
                    value or "값 미기재",
                    str(measurement.get("baseline") or "미기재"),
                    conditions or "미기재",
                    str(measurement.get("location") or "미기재"),
                ]
            )
    table = {"columns": MEASUREMENT_COLUMNS, "rows": rows} if rows else None
    return paragraphs, table


def _judgment_rows(state: GraphState, perspective: str, passed: set[tuple[str, str, str]], has_checks: bool) -> list[list[str]]:
    evidence = state.get("evidence") or {}
    result = state.get(f"{perspective}_analysis") or {}
    rows: list[list[str]] = []
    for technology in state["run_config"]["technologies"]:
        judgments = (result.get("technologies") or {}).get(technology) or {}
        fields = list(LABELS[perspective]) + [field for field in judgments if field not in LABELS[perspective]]
        for field in fields:
            judgment = judgments.get(field)
            title = FIELD_TITLES.get(field, field)
            if not isinstance(judgment, dict):
                rows.append([technology, title, "미확인", "판정 없음", "", "미확인"])
                continue
            label = str(judgment.get("label") or "미확인")
            if has_checks and (perspective, technology, field) not in passed:
                label += " (근거 미확인)"
            cite = _citations(list(judgment.get("evidence_ids") or []), evidence)
            rows.append(
                [
                    technology,
                    title,
                    label,
                    str(judgment.get("reason") or "설명 미확인"),
                    str(judgment.get("conditions") or ""),
                    cite or "미확인",
                ]
            )
    return rows


def _trl_details(state: GraphState) -> list[str]:
    evidence = state.get("evidence") or {}
    lines: list[str] = []
    for technology in state["run_config"]["technologies"]:
        judgment = _judgment(state, "trl", technology, "trl")
        if judgment is None:
            continue
        parts: list[str] = []
        if judgment.get("highest_confirmed"):
            parts.append(f"확인된 최고 단계 {judgment['highest_confirmed']}")
        stages = judgment.get("stages") or {}
        if isinstance(stages, dict) and stages:
            described = []
            for stage, detail in stages.items():
                if not isinstance(detail, dict):
                    continue
                cite = _citations(list(detail.get("evidence_ids") or []), evidence)
                status = "충족" if detail.get("met") else "미충족"
                note = f", {detail['note']}" if detail.get("note") else ""
                described.append(f"{stage} {status}{(' ' + cite) if cite else ''}{note}")
            if described:
                parts.append("단계별 확인: " + "; ".join(described))
        if judgment.get("missing_evidence"):
            parts.append("다음 단계를 위해 확인하지 못한 증거: " + "; ".join(str(item) for item in judgment["missing_evidence"]))
        if judgment.get("estimation_note"):
            parts.append(f"추정 근거: {judgment['estimation_note']}")
        if parts:
            lines.append(f"{technology}: " + ". ".join(parts) + ".")
    return lines


def _synthesis_paragraphs(synthesis: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    conflicts = synthesis.get("conflicts") or []
    agreements = synthesis.get("agreements") or []
    lines = [
        f"관점 간 상충 쌍 {len(conflicts)}개, 일치 쌍 {len(agreements)}개를 확인했다. 총점이나 순위 대신 각 쌍이 성립하는 조건과 남은 불확실성을 나란히 제시한다."
    ]
    for pairs, title in ((conflicts, "상충"), (agreements, "일치")):
        for pair in pairs:
            first, second = pair["first"], pair["second"]
            cite = _citations(list(first["evidence_ids"]) + list(second["evidence_ids"]), evidence)
            left = f"{PERSPECTIVE_TITLES.get(first['perspective'], first['perspective'])}/{FIELD_TITLES.get(first['field'], first['field'])}"
            right = f"{PERSPECTIVE_TITLES.get(second['perspective'], second['perspective'])}/{FIELD_TITLES.get(second['field'], second['field'])}"
            lines.append(
                f"[{title}] {pair['technology']}: {left}({first['label']}) 및 {right}({second['label']}). {pair['reason']} "
                f"성립 조건: {left} '{first.get('conditions') or '조건 미기재'}' / {right} '{second.get('conditions') or '조건 미기재'}'. "
                f"남은 불확실성: {pair['uncertainty']}" + (f" 근거: {cite}" if cite else "")
            )
    if len(lines) == 1:
        lines.append("확인된 근거로 구성할 수 있는 관점 간 쌍이 없다.")
    return lines


def _limitations(state: GraphState, synthesis: dict[str, Any]) -> list[str]:
    limits = list(synthesis.get("limitations") or [])
    limits.extend(limitation_lines(state))
    for identifier, item in (state.get("errors") or {}).items():
        limits.append(f"실행 오류({item.get('kind', 'service')}) {item.get('node', identifier)}: {item.get('reason', '오류')}")
    conflicts = collect_conflicts(state)
    if conflicts:
        described = ", ".join(
            f"{item['collection']}/{item['id']}({item['variants']}건, {'/'.join(item['differing_fields']) or '필드 미상'})" for item in conflicts
        )
        limits.append(f"동일 ID 충돌 기록: {described}. 최초 수집 값을 사용했다.")
    check = state.get("evidence_check") or {}
    if check and not check.get("semantic_review_enabled"):
        limits.append("근거의 의미적 적합성은 규칙 검사만 수행했고 검토 LLM은 실행하지 않았다.")
    elif check.get("semantic_review_errors") or check.get("semantic_review_skipped"):
        limits.append(
            f"검토 LLM 오류 {check.get('semantic_review_errors', 0)}건, 호출 예산 초과로 생략 {check.get('semantic_review_skipped', 0)}건: 해당 항목은 규칙 검사만 통과했다."
        )
    paragraphs = [
        "공개 정보 기반 추정의 한계: " + TRL_DISCLAIMER + " 시장성과 이해관계자 판정도 공개된 발표와 발언에 근거하므로 비공개 채택 현황은 반영되지 않는다.",
        "확증편향 방지 조치: " + BIAS_CONTROLS,
    ]
    paragraphs.extend(dict.fromkeys(limits) or ["기계 검사에서 누락된 항목 없음."])
    return paragraphs


def _evidence_lines(evidence: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for evidence_id, item in sorted(evidence.items()):
        quote = _clip(item.get("quote") or item.get("claim") or "인용 구절 미기재", QUOTE_LIMIT)
        line = (
            f"[{evidence_id}] {item.get('technology', '기술 미상')} / 출처 [{item.get('source_id', '출처 미상')}] / "
            f"위치 {item.get('location') or '미기재'} / 유형 {item.get('claim_type', '미기재')}. {quote}"
        )
        if item.get("speaker"):
            line += f" 발언 주체: {item['speaker']}" + (f"({item['stated_at']})" if item.get("stated_at") else "")
        if item.get("conditions"):
            line += f" 조건: {_clip(item['conditions'], 200)}"
        measurement = item.get("measurement")
        if isinstance(measurement, dict):
            fields = ("metric", "value", "unit", "baseline", "model", "hardware", "context_length", "batch_size", "precision", "location")
            described = "; ".join(f"{field}={measurement[field]}" for field in fields if measurement.get(field) not in (None, ""))
            if described:
                line += f" 측정: {described}"
        lines.append(line)
    return lines


def format_reference(source_id: str, source: dict[str, Any]) -> str:
    """Assignment format. 논문: 저자(YYYY). 제목. 학회명, URL / 기타: 기관(YYYY-MM-DD). 제목. 사이트명, URL."""
    source_type = str(source.get("source_type") or "web").lower()
    author = source.get("author_or_org") or "저자 미상"
    title = source.get("title") or "제목 미상"
    published = str(source.get("published_at") or "").strip()
    if source_type == "paper":
        year = published[:4] if len(published) >= 4 else "연도 미상"
        text = f"{author}({year}). {title}."
    else:
        text = f"{author}({published or '발행일 미상'}). {title}."
    if source.get("venue"):
        text += f" {source['venue']},"
    text += f" {source['url']}" if source.get("url") else " (URL 미기재)"
    return f"[{source_id}] {text}"


def build_report(state: GraphState) -> dict[str, Any]:
    config = state["run_config"]
    technologies = config["technologies"]
    evidence = state.get("evidence") or {}
    sources = state.get("sources") or {}
    synthesis = state.get("synthesis") or {}
    has_checks, passed = _passed_items(state)
    title = config.get("report_title") or f"{' · '.join(technologies)} KV cache 최적화 기술 다관점 평가 보고서"

    sections = [_section("SUMMARY", deterministic_summary(state))]
    sections.append(_section("1. 분석 배경", background_paragraphs(config)))
    selection_text, selection_table = selection_paragraphs(config)
    sections.append(_section("2. 기술 선정", selection_text, selection_table))
    technical_text, technical_table = _technical_section(state)
    sections.append(_section("3. 기술 개요", technical_text, technical_table))
    sections.append(
        _section(
            "4. 관점별 평가",
            [
                "네 관점의 판정을 기술별·항목별로 정리했다. 판정 라벨은 Rubric에서 정의한 집합 안에서만 고르며, 근거를 찾지 못한 항목은 "
                "미확인으로 남긴다. 근거 ID는 부록의 근거 목록과 대응하고, 근거 검사를 통과하지 못한 판정에는 (근거 미확인)을 표시했다."
            ],
        )
    )
    for index, name in enumerate(PERSPECTIVES, start=1):
        paragraphs = [PERSPECTIVE_NOTES[name]]
        if name == "trl":
            paragraphs.append(TRL_DISCLAIMER)
            paragraphs.extend(_trl_details(state))
        if not state.get(f"{name}_analysis"):
            paragraphs.append("이 관점의 결과가 생성되지 않았다. 6장 한계점의 실행 오류를 참고한다.")
        rows = _judgment_rows(state, name, passed, has_checks)
        sections.append(_section(f"4.{index} {PERSPECTIVE_TITLES[name]}", paragraphs, {"columns": JUDGMENT_COLUMNS, "rows": rows}, level=2))
    sections.append(_section("5. 시사점", _synthesis_paragraphs(synthesis, evidence)))
    sections.append(_section("6. 한계점", _limitations(state, synthesis)))
    sections.append(_section("부록. 근거 목록", _evidence_lines(evidence) or ["등록된 근거 없음"]))
    used_source_ids = sorted({item.get("source_id") for item in evidence.values() if item.get("source_id") in sources})
    references = [format_reference(source_id, sources[source_id]) for source_id in used_source_ids]
    sections.append(_section("REFERENCE", references or ["검증된 출처 없음"]))

    sections = _redact(sections)
    return {
        "title": _redact(title),
        "sections": sections,
        "markdown": render_markdown(sections),
        "used_source_ids": used_source_ids,
        "generation_mode": "deterministic",
    }


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _markdown_table(table: dict[str, Any]) -> str:
    columns = table["columns"]
    lines = ["| " + " | ".join(_cell(column) for column in columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    lines.extend("| " + " | ".join(_cell(value) for value in row) + " |" for row in table["rows"])
    return "\n".join(lines)


def render_markdown(sections: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for section in sections:
        parts.append("#" * int(section.get("level", 1)) + " " + section["heading"])
        parts.extend(str(paragraph) for paragraph in section.get("paragraphs", []))
        table = section.get("table")
        if table and table.get("rows"):
            parts.append(_markdown_table(table))
    return "\n\n".join(parts) + "\n"


def _register_korean_font() -> str:
    """Embed a Korean TrueType font when one is available; fall back to the CID font."""
    global _FONT_NAME
    if _FONT_NAME:
        return _FONT_NAME
    candidates: list[str] = []
    if os.environ.get("RAG_PDF_FONT"):
        candidates.append(os.environ["RAG_PDF_FONT"])
    candidates.extend(FONT_CANDIDATES)
    candidates.extend(glob.glob("/System/Library/AssetsV2/com_apple_MobileAsset_Font*/*/AssetData/NanumGothic.ttc"))
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if not path.is_file():
            continue
        try:
            font = TTFont("KoreanBody", str(path), subfontIndex=0) if path.suffix.lower() == ".ttc" else TTFont("KoreanBody", str(path))
            pdfmetrics.registerFont(font)
        except Exception as exc:  # unusable outline format, corrupt file, ...
            logger.warning("PDF font %s unusable: %s", path, exc)
            continue
        _FONT_NAME = "KoreanBody"
        logger.info("PDF font embedded from %s", path)
        return _FONT_NAME
    pdfmetrics.registerFont(UnicodeCIDFont(FALLBACK_CID_FONT))
    _FONT_NAME = FALLBACK_CID_FONT
    logger.warning("No embeddable Korean TTF found; using non-embedded CID font %s", FALLBACK_CID_FONT)
    return _FONT_NAME


def _column_weights(columns: list[str]) -> list[float]:
    weights = {
        "기술": 1.0, "항목": 1.3, "판정": 1.3, "판정 이유": 2.6, "성립 조건": 2.0, "근거": 1.4,
        "비교 축": 1.0, "KIVI (SW)": 2.5, "InfiniGen (HW)": 2.5,
        "지표": 1.2, "값": 1.0, "비교 기준": 1.2, "측정 조건": 2.4, "출처 위치": 1.2,
    }
    return [weights.get(column, 1.5) for column in columns]


def _write_pdf(path: Path, report: dict[str, Any], meta: str) -> str:
    font = _register_korean_font()
    base = getSampleStyleSheet()["BodyText"]
    body = ParagraphStyle("KoreanBody", parent=base, fontName=font, fontSize=9.5, leading=15, wordWrap="CJK", spaceAfter=6)
    cell = ParagraphStyle("KoreanCell", parent=body, fontSize=7.5, leading=10, spaceAfter=0)
    heading1 = ParagraphStyle("KoreanH1", parent=body, fontSize=14, leading=20, spaceBefore=14, spaceAfter=8)
    heading2 = ParagraphStyle("KoreanH2", parent=body, fontSize=11.5, leading=16, spaceBefore=10, spaceAfter=6)
    title_style = ParagraphStyle("KoreanTitle", parent=heading1, fontSize=17, leading=24, alignment=TA_CENTER, spaceAfter=4)
    meta_style = ParagraphStyle("KoreanMeta", parent=body, fontSize=8, alignment=TA_CENTER, textColor=colors.HexColor("#555555"), spaceAfter=12)
    story: list[Any] = [Paragraph(escape(report["title"]), title_style), Paragraph(escape(meta), meta_style)]
    width = A4[0] - 90
    for section in report["sections"]:
        story.append(Paragraph(escape(section["heading"]), heading1 if section.get("level", 1) == 1 else heading2))
        for paragraph in section.get("paragraphs", []):
            story.append(Paragraph(escape(str(paragraph)).replace("\n", "<br/>"), body))
        table = section.get("table")
        if table and table.get("rows"):
            weights = _column_weights(table["columns"])
            widths = [width * weight / sum(weights) for weight in weights]
            data = [[Paragraph(escape(str(column)), cell) for column in table["columns"]]]
            data.extend([Paragraph(escape(str(value)), cell) for value in row] for row in table["rows"])
            grid = Table(data, colWidths=widths, repeatRows=1)
            grid.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa4b2")),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf3")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 3),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                        ("TOPPADDING", (0, 0), (-1, -1), 2),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ]
                )
            )
            story.append(grid)
            story.append(Spacer(1, 6))
        story.append(Spacer(1, 4))
    SimpleDocTemplate(str(path), pagesize=A4, rightMargin=45, leftMargin=45, topMargin=45, bottomMargin=45, title=report["title"]).build(story)
    return font


def save_outputs(state: GraphState, output_dir: Path | str, *, report_name: str = "report") -> dict[str, str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    config = state["run_config"]
    report = state.get("report")
    synthesis = state.get("synthesis") or {}
    check = state.get("evidence_check") or {}
    pdf_font: str | None = None
    meta = (
        f"모드 {config['mode']} · 생성 방식 {(report or {}).get('generation_mode', '-')} · 기준일 {config.get('as_of') or '미지정'} · "
        f"실행 시각 {str(state.get('started_at', ''))[:19]}"
    )
    if report:
        md_path = output_dir / f"{report_name}.md"
        md_path.write_text(report["markdown"], encoding="utf-8")
        artifacts["markdown"] = str(md_path)
        environment = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / "templates"), autoescape=select_autoescape(["html"]))
        html_path = output_dir / f"{report_name}.html"
        html_path.write_text(
            environment.get_template("report.html.j2").render(title=report.get("title", report_name), meta=meta, sections=report["sections"]),
            encoding="utf-8",
        )
        artifacts["html"] = str(html_path)
        pdf_path = output_dir / f"{report_name}.pdf"
        pdf_font = _write_pdf(pdf_path, report, meta)
        artifacts["pdf"] = str(pdf_path)
    source_path = output_dir / "sources.json"
    source_path.write_text(json.dumps(_redact(state.get("sources", {})), ensure_ascii=False, indent=2), encoding="utf-8")
    artifacts["sources"] = str(source_path)
    manifest_path = output_dir / "run_manifest.json"
    artifacts["manifest"] = str(manifest_path)
    finished_at = datetime.now(timezone.utc)
    started_at = datetime.fromisoformat(state["started_at"]) if state.get("started_at") else finished_at
    errors = state.get("errors", {}) or {}
    manifest = {
        "mode": config["mode"],
        "model_id": config.get("model_id"),
        "technologies": config["technologies"],
        "domain": config.get("domain"),
        "as_of": config.get("as_of"),
        "budget": config.get("budget"),
        "report_name": report_name,
        "started_at": state.get("started_at"),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "retry_count": state.get("retry_count", 0),
        "status": "failed" if any(item.get("fatal") for item in errors.values()) else ("complete" if check.get("passed") else "incomplete"),
        "evidence_check": check or None,
        "semantic_review": {
            "enabled": check.get("semantic_review_enabled"),
            "calls": check.get("semantic_review_calls"),
            "errors": check.get("semantic_review_errors"),
            "skipped": check.get("semantic_review_skipped"),
        },
        "generation": {
            "synthesis_mode": synthesis.get("generation_mode"),
            "synthesis_fallback_reason": synthesis.get("fallback_reason"),
            "synthesis_llm_review": synthesis.get("llm_review"),
            "report_mode": (report or {}).get("generation_mode"),
            "report_fallback_reason": (report or {}).get("fallback_reason"),
        },
        "errors": errors,
        "conflicts": collect_conflicts(state),
        "metrics": aggregate_metrics(state.get("metrics")),
        "pdf_font": pdf_font,
        "artifacts": dict(artifacts),
    }
    manifest_path.write_text(json.dumps(_redact(manifest), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return artifacts
