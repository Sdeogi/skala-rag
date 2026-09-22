#!/usr/bin/env python
"""FAISS 인덱스를 새로 빌드하는 CLI. `python scripts/build_index.py`로 실행.

`skala_rag`가 editable 설치되어 있지 않아도 실행할 수 있도록 `src/`를 sys.path에 추가한다.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from skala_rag.tools.retrieve.ingest import build_index  # noqa: E402


def main() -> None:
    start = time.time()
    build_index()
    elapsed = time.time() - start
    print(f"FAISS 인덱스를 indexes/ 에 생성했습니다. ({elapsed:.1f}초)")


if __name__ == "__main__":
    main()
