"""2단 편집 학술 논문 PDF에서 읽기 순서를 보존해 텍스트를 추출한다.

`PyMuPDF`(pymupdf)를 사용한다. 애초에는 `pdfplumber`로 단어 좌표를 직접 클러스터링해 2단
컬럼을 재조립했으나, 이 논문들의 PDF는 공백 문자가 빠져 있고(단어 간 간격만으로 공백을
추정해야 함) arXiv 세로 워터마크 같은 회전된 텍스트가 섞여 있어 결과에 "nuJ"처럼 뒤집힌
문자열이 섞이는 문제가 있었다. PyMuPDF의 `page.get_text("dict")`는 같은 PDF에서 이 문제
없이 단어 간격과 2단 컬럼의 블록 순서(왼쪽 컬럼 전체 -> 오른쪽 컬럼 전체)를 올바르게 준다.

다만 `page.get_text("dict")`는 시각적으로 같은 줄(같은 y좌표)에 있어도 "1"과 "Introduction"
사이처럼 큰 x 간격이 있으면 이를 서로 다른 `line`으로 쪼갠다. 이 때문에 표제가
"1"/"Introduction" 두 줄로 분리되어 섹션 인식이 깨지므로, 같은 블록 안에서 y좌표가 사실상
같은 연속된 `line`들은 합쳐서 하나의 줄로 취급한다.

표 자동 인식은 쓰지 않는다. 표 내용은 컬럼 읽기 순서를 따르는 일반 텍스트 흐름으로 함께
추출된다(행/열 구조는 보존되지 않음 — 알려진 한계, docs/PAPER_RAG_HANDOFF.md 참고).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf

# 같은 블록 안에서 이 오차(포인트) 이내로 y좌표가 같으면 같은 시각적 줄로 간주해 합친다.
_SAME_ROW_TOLERANCE = 1.0
# PyMuPDF 텍스트 블록 type: 0 = 텍스트, 1 = 이미지.
_TEXT_BLOCK_TYPE = 0

_HEADING_FIRST_WORD = r"[A-Z][A-Za-z0-9(),:&-]*"
_HEADING_NEXT_WORD = r"[A-Za-z0-9(),:&-]+"
_SECTION_HEADING_RE = re.compile(
    rf"^(?:[0-9]{{1,2}}(?:\.[0-9]{{1,2}}){{0,3}}\.?\s+{_HEADING_FIRST_WORD}(?:\s+{_HEADING_NEXT_WORD}){{0,8}}"
    rf"|[A-Z]\.\s+{_HEADING_FIRST_WORD}(?:\s+{_HEADING_NEXT_WORD}){{0,8}}"  # 부록 등 "A. Title" 형태 표제
    r"|(?i:abstract|references|bibliography|acknowledg(?:e)?ments?|appendix[a-z. ]*))$"
)
_REFERENCES_RE = re.compile(r"^(?i:references|bibliography)\.?$")
# 페이지 번호 단독 줄, arXiv 자동 워터마크 줄은 본문이 아니므로 건너뛴다.
_NOISE_LINE_RE = re.compile(r"^([0-9]{1,4}|arXiv:\S+.*)$")


@dataclass
class PageBlock:
    """페이지에서 추출한, 섹션 하나에 속하는 텍스트 덩어리."""

    tech_name: str
    page: int
    section: str
    text: str


def _iter_page_lines(page: pymupdf.Page):
    """페이지를 시각적 줄 단위 텍스트로 순회한다(2단 컬럼 읽기 순서 유지)."""
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != _TEXT_BLOCK_TYPE:
            continue
        merged: list[list] = []  # [top, text]
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"])
            if not text.strip():
                continue
            top = line["bbox"][1]
            if merged and abs(merged[-1][0] - top) < _SAME_ROW_TOLERANCE:
                merged[-1][1] += " " + text
            else:
                merged.append([top, text])
        for _, text in merged:
            yield text


def extract_pdf_pages(pdf_path: str, tech_name: str) -> list[PageBlock]:
    """PDF를 컬럼 읽기 순서를 보존해 섹션별 텍스트 블록 리스트로 변환한다.

    References/Bibliography **절만** 색인 대상에서 제외하고, 그 뒤에 이어지는 부록(Appendix)
    등은 새 섹션 제목이 감지되는 순간부터 다시 포함한다(설계서 B.4: "본문, 실험, 부록만
    검색 대상으로 삼는다").
    """
    blocks: list[PageBlock] = []
    current_section = "Front Matter"
    in_references = False

    with pymupdf.open(pdf_path) as doc:
        for page_index, page in enumerate(doc):
            page_number = page_index + 1
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

            for raw_line in _iter_page_lines(page):
                stripped = raw_line.strip()
                if not stripped or _NOISE_LINE_RE.match(stripped):
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
