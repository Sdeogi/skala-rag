"""Grounded Korean report construction and artifact serialization."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from skala_rag.graph.state import GraphState


PERSPECTIVES = (("market", "시장성"), ("stakeholder", "이해관계자"), ("domain", "도메인 적용"), ("trl", "기술 성숙도"))
PRIVATE_PATTERNS = (
    re.compile(r"\b(?:sk|tvly)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}\b", re.IGNORECASE),
    re.compile(r"(?i)(?:api[_-]?key|token)=([^\s&]+)"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b"),
)


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


def _citations(judgment: dict[str, Any], evidence: dict[str, Any]) -> str:
    return " ".join(f"[{identifier}]" for identifier in judgment.get("evidence_ids", []) if identifier in evidence)


def build_report(state: GraphState) -> dict[str, Any]:
    config = state["run_config"]
    technologies = config["technologies"]
    evidence = state.get("evidence", {})
    sources = state.get("sources", {})
    synthesis = state.get("synthesis") or {}
    sections: list[dict[str, Any]] = []
    intro = f"{config['domain']}에서 {', '.join(technologies)}를 네 관점으로 검토했다. 각 판정은 확인된 근거와 성립 조건을 함께 제시한다."
    if config.get("fixture"):
        intro = "합성 fixture 실행: 이 보고서는 실제 논문·웹 조사 결과가 아니다. " + intro
    sections.append({"heading": "SUMMARY", "paragraphs": [intro]})

    technical = []
    for technology in technologies:
        findings = state.get("technical_findings", {}).get(technology, {})
        if findings:
            details = "; ".join(f"{key}: {value}" for key, value in findings.items() if isinstance(value, (str, int, float)))
            technical.append(f"{technology}: {details or '구조화된 기술 조사 결과 있음'}")
        else:
            technical.append(f"{technology}: 기술 조사 결과 미확인")
    sections.append({"heading": "기술 조사", "paragraphs": technical})

    for name, title in PERSPECTIVES:
        paragraphs = []
        result = state.get(f"{name}_analysis") or {}
        for technology in technologies:
            for field, judgment in result.get("technologies", {}).get(technology, {}).items():
                if not isinstance(judgment, dict):
                    continue
                citations = _citations(judgment, evidence)
                label = judgment.get("label", "미확인")
                reason = judgment.get("reason", "설명 미확인")
                conditions = judgment.get("conditions", "")
                line = f"{technology} / {field}: {label}. {reason}"
                if conditions:
                    line += f" 조건: {conditions}."
                if citations:
                    line += f" 근거: {citations}"
                else:
                    line += " 근거: 미확인"
                paragraphs.append(line)
        sections.append({"heading": title, "paragraphs": paragraphs or ["관점 결과 미확인"]})

    synthesis_lines = []
    for kind, title in (("agreements", "일치"), ("conflicts", "상충")):
        for pair in synthesis.get(kind, []):
            first, second = pair["first"], pair["second"]
            ids = list(dict.fromkeys(first["evidence_ids"] + second["evidence_ids"]))
            cite = " ".join(f"[{i}]" for i in ids if i in evidence)
            synthesis_lines.append(
                f"{pair['technology']} {title}: {first['perspective']}/{first['field']}({first['label']})와 "
                f"{second['perspective']}/{second['field']}({second['label']}). "
                f"{pair['reason']} 조건: {first['conditions']} / {second['conditions']}. "
                f"불확실성: {pair['uncertainty']}. {cite}"
            )
    sections.append({"heading": "관점 간 종합", "paragraphs": synthesis_lines or ["확인된 근거로 구성할 수 있는 관점 간 쌍이 없다."]})

    limits = list(synthesis.get("limitations", []))
    limits.extend(f"{q['technology']} {q['perspective']}/{q['field']}: 근거 미확인" for q in state.get("missing_questions", []))
    limits.extend(f"{item.get('node', identifier)}: {item.get('reason', '오류')}" for identifier, item in state.get("errors", {}).items())
    sections.append({"heading": "한계와 미확인 항목", "paragraphs": list(dict.fromkeys(limits)) or ["기계 검사에서 누락된 항목 없음. 근거의 의미적 적합성은 별도 검토가 필요하다."]})

    evidence_lines = []
    for evidence_id, item in sorted(evidence.items()):
        source_id = item.get("source_id", "출처 미상")
        line = f"[{evidence_id}] {item.get('technology', '기술 미상')} / 출처 [{source_id}] / 위치 {item.get('location', '미기재')}. {item.get('quote', item.get('claim', '인용 구절 미기재'))}"
        if item.get("conditions"):
            line += f" 조건: {item['conditions']}"
        if item.get("measurement") and isinstance(item["measurement"], dict):
            measurement = item["measurement"]
            fields = ("metric", "value", "unit", "baseline", "model", "hardware", "context_length", "batch_size", "precision", "location")
            line += " 측정: " + "; ".join(f"{field}={measurement.get(field, '미기재')}" for field in fields)
        evidence_lines.append(line)
    sections.append({"heading": "근거 목록", "paragraphs": evidence_lines or ["등록된 근거 없음"]})

    references = []
    used_source_ids = {item.get("source_id") for item in evidence.values() if item.get("source_id") in sources}
    for source_id in sorted(used_source_ids):
        source = sources[source_id]
        references.append(f"[{source_id}] {source.get('title', '제목 미상')} — {source.get('url', 'URL 없음')}")
    sections.append({"heading": "REFERENCE", "paragraphs": references or ["검증된 출처 없음"]})

    sections = _redact(sections)
    markdown = "\n\n".join("# " + section["heading"] + "\n\n" + "\n\n".join(section["paragraphs"]) for section in sections) + "\n"
    return {"sections": sections, "markdown": markdown, "used_source_ids": sorted(used_source_ids), "generation_mode": "deterministic"}


def _write_pdf(path: Path, sections: list[dict[str, Any]]) -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    body = ParagraphStyle("KoreanBody", parent=getSampleStyleSheet()["BodyText"], fontName="HYSMyeongJo-Medium", fontSize=9, leading=15, wordWrap="CJK", spaceAfter=7)
    heading = ParagraphStyle("KoreanHeading", parent=body, fontSize=15, leading=22, spaceBefore=14, spaceAfter=9)
    title = ParagraphStyle("KoreanTitle", parent=heading, fontSize=18, leading=26, alignment=TA_CENTER)
    story = []
    for index, section in enumerate(sections):
        story.append(Paragraph(escape(section["heading"]), title if index == 0 else heading))
        for paragraph in section["paragraphs"]:
            story.append(Paragraph(escape(paragraph).replace("\n", "<br/>"), body))
        story.append(Spacer(1, 8))
    SimpleDocTemplate(str(path), pagesize=A4, rightMargin=45, leftMargin=45, topMargin=45, bottomMargin=45).build(story)


def save_outputs(state: GraphState, output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, str] = {}
    report = state.get("report")
    if report:
        md_path = output_dir / "report.md"
        md_path.write_text(report["markdown"], encoding="utf-8")
        artifacts["markdown"] = str(md_path)
        environment = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / "templates"), autoescape=select_autoescape(["html"]))
        html_path = output_dir / "report.html"
        html_path.write_text(environment.get_template("report.html.j2").render(sections=report["sections"]), encoding="utf-8")
        artifacts["html"] = str(html_path)
        pdf_path = output_dir / "report.pdf"
        _write_pdf(pdf_path, report["sections"])
        artifacts["pdf"] = str(pdf_path)
    source_path = output_dir / "sources.json"
    source_path.write_text(json.dumps(_redact(state.get("sources", {})), ensure_ascii=False, indent=2), encoding="utf-8")
    artifacts["sources"] = str(source_path)
    manifest_path = output_dir / "run_manifest.json"
    artifacts["manifest"] = str(manifest_path)
    finished_at = datetime.now(timezone.utc)
    started_at = datetime.fromisoformat(state["started_at"]) if state.get("started_at") else finished_at
    manifest = {
        "mode": state["run_config"]["mode"],
        "model_id": state["run_config"].get("model_id"),
        "technologies": state["run_config"]["technologies"],
        "started_at": state.get("started_at"),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "retry_count": state.get("retry_count", 0),
        "evidence_check": state.get("evidence_check"),
        "errors": state.get("errors", {}),
        "metrics": state.get("metrics", {}),
        "synthesis_generation_mode": state.get("synthesis", {}).get("generation_mode"),
        "report_generation_mode": state.get("report", {}).get("generation_mode"),
        "status": "failed" if any(e.get("fatal") for e in state.get("errors", {}).values()) else ("complete" if state.get("evidence_check", {}).get("passed") else "incomplete"),
        "artifacts": dict(artifacts),
    }
    manifest_path.write_text(json.dumps(_redact(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    return artifacts
