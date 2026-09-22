from skala_rag.tools.retrieve.parsing import extract_pdf_pages

KIVI_PDF = "data/papers/kivi.pdf"
INFINIGEN_PDF = "data/papers/infinigen.pdf"


def test_extract_returns_nonempty_blocks_for_both_papers():
    kivi_blocks = extract_pdf_pages(KIVI_PDF, "KIVI")
    infinigen_blocks = extract_pdf_pages(INFINIGEN_PDF, "InfiniGen")

    assert len(kivi_blocks) > 5
    assert len(infinigen_blocks) > 5
    assert all(b.tech_name == "KIVI" for b in kivi_blocks)
    assert all(b.text.strip() for b in kivi_blocks)


def test_references_section_is_excluded():
    for pdf_path, tech_name in [(KIVI_PDF, "KIVI"), (INFINIGEN_PDF, "InfiniGen")]:
        blocks = extract_pdf_pages(pdf_path, tech_name)
        assert not any(b.section.strip().lower() in {"references", "bibliography"} for b in blocks)
        # References 절 본문(저자/연도 인용 목록)이 다른 섹션으로 잘못 라벨링되어 남지 않았는지 확인
        assert not any("et al" in b.text and "arxiv" in b.text.lower() for b in blocks)


def test_appendix_after_references_is_kept_for_kivi():
    # KIVI 논문은 References(10p) 뒤에 부록 A~D가 이어진다(설계서 B.4: 부록은 색인 대상).
    blocks = extract_pdf_pages(KIVI_PDF, "KIVI")
    assert any(b.page > 10 for b in blocks), "References 이후 부록 페이지가 제외되면 안 된다"


def test_pages_are_recorded_and_monotonic_source():
    blocks = extract_pdf_pages(KIVI_PDF, "KIVI")
    pages = [b.page for b in blocks]
    assert pages == sorted(pages), "블록은 페이지 순서대로 나와야 한다"
