import pytest

from skala_rag.tools.retrieve.ingest import build_index


@pytest.fixture(scope="session")
def built_index_dir(tmp_path_factory) -> str:
    """실제 두 논문으로 임시 디렉터리에 FAISS 인덱스를 한 번만 빌드해서 재사용한다."""
    index_dir = tmp_path_factory.mktemp("faiss_index")
    build_index(papers_dir="data/papers", index_dir=str(index_dir))
    return str(index_dir)
