#!/usr/bin/env python
"""기술조사 Agent를 직접 실행해 결과를 눈으로 확인하는 CLI.

예: python scripts/run_technical_agent.py --tech KIVI --tech InfiniGen

OPENAI_API_KEY가 없으면 명확한 에러 메시지로 종료한다.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from skala_rag.agents.technical import run_technical_research  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="기술조사 Agent 실행")
    parser.add_argument(
        "--tech", action="append", dest="tech_names", help="기술명 (여러 번 지정 가능)"
    )
    args = parser.parse_args()
    tech_names = args.tech_names or ["KIVI", "InfiniGen"]

    if not os.getenv("OPENAI_API_KEY"):
        print(
            "OPENAI_API_KEY가 설정되어 있지 않습니다. .env에 키를 채운 뒤 다시 실행하세요.",
            file=sys.stderr,
        )
        sys.exit(1)

    result = run_technical_research(tech_names)
    print(json.dumps(result.model_dump(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
