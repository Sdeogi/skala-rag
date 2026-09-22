import json

import pytest

from skala_rag.tools.retrieve.ingest import build_index


def _write_manifest(papers_dir, papers):
    (papers_dir / "manifest.json").write_text(json.dumps({"papers": papers}), encoding="utf-8")


def test_build_index_rejects_over_200_total_pages(tmp_path):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    _write_manifest(
        papers_dir,
        [
            {
                "source_id": "A",
                "tech_name": "A",
                "filename": "a.pdf",
                "page_count": 150,
            },
            {
                "source_id": "B",
                "tech_name": "B",
                "filename": "b.pdf",
                "page_count": 60,
            },
        ],
    )

    with pytest.raises(ValueError, match="200"):
        build_index(papers_dir=str(papers_dir), index_dir=str(tmp_path / "indexes"))


def test_build_index_reports_corrupt_pdf_clearly(tmp_path):
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    corrupt_pdf = papers_dir / "broken.pdf"
    corrupt_pdf.write_bytes(b"not a real pdf")
    _write_manifest(
        papers_dir,
        [
            {
                "source_id": "BROKEN",
                "tech_name": "BROKEN",
                "filename": "broken.pdf",
                "page_count": 1,
            }
        ],
    )

    with pytest.raises(RuntimeError, match="손상"):
        build_index(papers_dir=str(papers_dir), index_dir=str(tmp_path / "indexes"))
