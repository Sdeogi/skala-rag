"""2단 편집 학술 논문 PDF에서 읽기 순서를 보존해 텍스트를 추출한다.

`pdfplumber`의 기본 `extract_text()`/`extract_words()`는 이 두 논문(ICML/OSDI 카메라레디
템플릿)에서 두 가지 문제를 일으킨다.

1. 기본 ``x_tolerance``가 단어 사이 간격(~2.3pt)보다 커서 한 줄 전체가 공백 없이 한
   단어로 뭉친다 -> ``x_tolerance``를 좁혀서 해결한다.
2. 같은 높이(top)에 있는 좌/우 컬럼의 텍스트가 한 줄로 합쳐진다 -> 같은 top 그룹 안에서도
   컬럼 사이 여백(gutter)만큼 큰 x 간격이 있으면 별도 줄로 쪼갠다.

표 자동 인식(``page.find_tables()``)은 이 PDF의 그림(matplotlib 차트)을 표로 오검출해
축 레이블이 뒤섞인 텍스트("eulaV" 등)를 만들어내므로 사용하지 않는다. 표 내용은 컬럼
읽기 순서를 따르는 일반 텍스트 흐름으로 함께 추출된다(행/열 구조는 보존되지 않음 — 알려진
한계, docs/PAPER_RAG_HANDOFF.md 참고).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pdfplumber

# 단어 사이 실제 간격(~2.3pt)보다는 좁고, 글자 내부 커닝(대개 0 이하)보다는 넓은 값.
_WORD_X_TOLERANCE = 1.5
# 같은 줄로 묶을 top 좌표 오차 허용치.
_LINE_TOP_TOLERANCE = 2.5
# 컬럼 사이 여백(gutter, 대개 30pt 이상)과 일반 단어 간격을 구분하는 임계값.
_COLUMN_GAP_SPLIT = 18.0
# 페이지 폭 대비 이 비율 이상을 가로지르면 "전체 폭(full-width)" 줄로 본다.
_FULL_WIDTH_MARGIN_RATIO = 0.2

_HEADING_FIRST_WORD = r"[A-Z][A-Za-z0-9(),:&-]*"
_HEADING_NEXT_WORD = r"[A-Za-z0-9(),:&-]+"
_SECTION_HEADING_RE = re.compile(
    rf"^(?:[0-9]{{1,2}}(?:\.[0-9]{{1,2}}){{0,3}}\.?\s+{_HEADING_FIRST_WORD}(?:\s+{_HEADING_NEXT_WORD}){{0,8}}"
    rf"|[A-Z]\.\s+{_HEADING_FIRST_WORD}(?:\s+{_HEADING_NEXT_WORD}){{0,8}}"  # 부록 등 "A. Title" 형태 표제
    r"|(?i:abstract|references|bibliography|acknowledg(?:e)?ments?|appendix[a-z. ]*))$"
)
_REFERENCES_RE = re.compile(r"^(?i:references|bibliography)\.?$")


@dataclass
class TextLine:
    page: int
    top: float
    x0: float
    x1: float
    text: str


@dataclass
class PageBlock:
    """페이지에서 추출한, 섹션 하나에 속하는 텍스트 덩어리."""

    tech_name: str
    page: int
    section: str
    text: str


def _group_words_into_lines(words: list[dict]) -> list[list[dict]]:
    """단어를 top 좌표로 줄 단위로 묶고, 컬럼 여백만큼 큰 x 간격이 있으면 다시 쪼갠다."""
    rows: list[list[dict]] = []
    current: list[dict] = []
    current_top: float | None = None
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if current_top is None or abs(word["top"] - current_top) <= _LINE_TOP_TOLERANCE:
            current.append(word)
            current_top = word["top"] if current_top is None else current_top
        else:
            rows.append(current)
            current = [word]
            current_top = word["top"]
    if current:
        rows.append(current)

    lines: list[list[dict]] = []
    for row in rows:
        row = sorted(row, key=lambda w: w["x0"])
        sub: list[dict] = [row[0]]
        for word in row[1:]:
            if word["x0"] - sub[-1]["x1"] > _COLUMN_GAP_SPLIT:
                lines.append(sub)
                sub = [word]
            else:
                sub.append(word)
        lines.append(sub)
    return lines


def _line_from_words(page_number: int, words: list[dict]) -> TextLine:
    x0 = min(w["x0"] for w in words)
    x1 = max(w["x1"] for w in words)
    top = min(w["top"] for w in words)
    text = " ".join(w["text"] for w in sorted(words, key=lambda w: w["x0"]))
    return TextLine(page=page_number, top=top, x0=x0, x1=x1, text=text)


def _classify(line: TextLine, page_width: float) -> str:
    margin = page_width * _FULL_WIDTH_MARGIN_RATIO
    if line.x0 < margin and line.x1 > page_width - margin:
        return "full"
    return "left" if (line.x0 + line.x1) / 2 < page_width / 2 else "right"


def _reorder_two_column(lines: list[TextLine], page_width: float) -> list[TextLine]:
    """전체 폭 줄로 구분된 구간마다 좌 컬럼 전체 -> 우 컬럼 전체 순으로 재배열한다."""
    ordered: list[TextLine] = []
    left_buf: list[TextLine] = []
    right_buf: list[TextLine] = []
    for line in lines:
        cls = _classify(line, page_width)
        if cls == "full":
            ordered.extend(left_buf)
            ordered.extend(right_buf)
            left_buf, right_buf = [], []
            ordered.append(line)
        elif cls == "left":
            left_buf.append(line)
        else:
            right_buf.append(line)
    ordered.extend(left_buf)
    ordered.extend(right_buf)
    return ordered


def extract_pdf_pages(pdf_path: str, tech_name: str) -> list[PageBlock]:
    """PDF를 컬럼 읽기 순서를 보존해 섹션별 텍스트 블록 리스트로 변환한다.

    References/Bibliography **절만** 색인 대상에서 제외하고, 그 뒤에 이어지는 부록(Appendix)
    등은 새 섹션 제목이 감지되는 순간부터 다시 포함한다(설계서 B.4: "본문, 실험, 부록만
    검색 대상으로 삼는다").
    """
    blocks: list[PageBlock] = []
    current_section = "Front Matter"
    in_references = False

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages):
            page_number = page_index + 1
            words = page.extract_words(x_tolerance=_WORD_X_TOLERANCE)
            if not words:
                continue
            raw_lines = [_line_from_words(page_number, w) for w in _group_words_into_lines(words)]
            ordered_lines = _reorder_two_column(raw_lines, page.width)

            page_lines: list[str] = []

            def _flush() -> None:
                nonlocal page_lines
                if page_lines and not in_references:
                    blocks.append(
                        PageBlock(
                            tech_name=tech_name,
                            page=page_number,
                            section=current_section,
                            text="\n".join(page_lines),
                        )
                    )
                page_lines = []

            for line in ordered_lines:
                stripped = line.text.strip()
                if not stripped:
                    continue
                if _SECTION_HEADING_RE.match(stripped) and len(stripped) < 80:
                    _flush()
                    current_section = stripped
                    in_references = bool(_REFERENCES_RE.match(stripped))
                    continue
                if not in_references:
                    page_lines.append(stripped)

            _flush()

    return blocks
