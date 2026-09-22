"""Command-line entry point for the graph/output branch (design E.2).

    python app.py --mode replay --fixture --output-dir outputs/demo   # 합성 자료로 흐름 검증
    python app.py --mode live --output-dir outputs/live                # A/B/C 통합 서비스(기본 factory)
    python app.py --mode replay --output-dir outputs/replay             # data/web 캐시 재생 (LLM 판정은 호출)
    python app.py --draw-graph docs/graph.mmd
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is declared; keep the CLI usable in minimal environments
    def load_dotenv(*args, **kwargs):
        return False

# The repository uses a src layout; make `python app.py` work before the package is installed.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
if os.environ.get("RAG_DISABLE_DOTENV") != "1":  # tests set this so a local .env cannot leak into them
    load_dotenv()

from skala_rag.agents.report import save_outputs  # noqa: E402
from skala_rag.config import load_settings, missing_settings  # noqa: E402
from skala_rag.graph.workflow import PipelineServices, build_graph, draw_mermaid, initial_state  # noqa: E402


DEFAULT_SERVICES = "skala_rag.integration.services:create_services"


def _load_services(spec: str) -> PipelineServices:
    module_name, separator, factory_name = spec.partition(":")
    if not separator or not module_name or not factory_name:
        raise ValueError("--services must be module.path:factory")
    factory = getattr(importlib.import_module(module_name), factory_name)
    services = factory()
    if not isinstance(services, PipelineServices):
        raise TypeError("service factory must return PipelineServices")
    return services


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="KV cache 다관점 RAG 그래프 실행")
    parser.add_argument("--mode", choices=("live", "replay"), help="live: 외부 검색과 LLM 사용, replay: 저장된 자료 재생")
    parser.add_argument("--services", default=None, help=f"서비스 factory module.path:factory (기본: {DEFAULT_SERVICES})")
    parser.add_argument("--fixture", action="store_true", help="합성 자료로 그래프만 검증; 실제 평가에 사용 금지")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--report-name", default="report", help="보고서 파일 이름(확장자 제외). 예: RAG-Output_판교_10반_이름")
    parser.add_argument("--paper-dir", type=Path, help="논문 PDF 폴더 (A 브랜치 prepare가 사용)")
    parser.add_argument("--model-id", default=None, help="기본값: RAG_MODEL_ID 또는 gpt-5.4-mini")
    parser.add_argument("--technologies", nargs=2, metavar=("SW_TECH", "HW_TECH"), default=("KIVI", "InfiniGen"))
    parser.add_argument("--domain", default="클라우드 LLM 서빙")
    parser.add_argument("--as-of", default=None, help="평가 기준일 YYYY-MM-DD (기본: 오늘)")
    parser.add_argument("--web-search-max", type=int, default=20, help="실행당 웹 검색 상한")
    parser.add_argument("--fetch-max", type=int, default=30, help="실행당 원문 조회 상한")
    parser.add_argument("--tool-timeout", type=int, default=20, help="도구별 시간 제한(초)")
    parser.add_argument("--tool-retries", type=int, default=2, help="도구 재시도 횟수")
    parser.add_argument("--max-paper-pages", type=int, default=200, help="RAG 문서 총 페이지 상한")
    parser.add_argument("--deterministic-output", action="store_true", help="live에서도 규칙 기반 종합과 SUMMARY 사용")
    parser.add_argument("--llm-output", choices=("auto", "on", "off"), default="auto", help="종합·SUMMARY LLM (auto: live에서만, on: replay에서도 캐시 재생 후 LLM 작성)")
    parser.add_argument("--semantic-review", choices=("auto", "on", "off"), default="auto", help="근거 의미 검토 LLM (auto: live에서만)")
    parser.add_argument("--max-review-calls", type=int, default=72, help="검토 LLM 호출 상한")
    parser.add_argument("--recursion-limit", type=int, default=50, help="그래프 최대 단계 수")
    parser.add_argument("--draw-graph", nargs="?", const="-", metavar="PATH", help="그래프 mermaid를 PATH('-'는 표준출력)에 쓰고 종료")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.draw_graph is not None:
        text = draw_mermaid()
        if args.draw_graph == "-":
            print(text)
        else:
            Path(args.draw_graph).write_text(text, encoding="utf-8")
            print(f"graph: {args.draw_graph}")
        return 0
    if not args.mode:
        parser.error("--mode is required")
    if args.fixture and args.services:
        parser.error("--fixture and --services cannot be combined")
    if args.fixture and args.mode != "replay":
        parser.error("--fixture is only available in replay mode")
    services_spec = args.services or DEFAULT_SERVICES
    if args.paper_dir and not args.paper_dir.is_dir():
        parser.error(f"paper directory does not exist: {args.paper_dir}")
    settings = load_settings()
    model_id = args.model_id or settings.model_id
    review_enabled = args.semantic_review == "on" or (args.semantic_review == "auto" and args.mode == "live")
    if args.deterministic_output or args.llm_output == "off":
        llm_output = False
    else:
        llm_output = args.llm_output == "on" or args.mode == "live"
    absent = missing_settings(settings, args.mode, semantic_review=review_enabled, llm_output=llm_output, services_need_llm=not args.fixture)
    if absent:
        parser.error("missing configuration: " + ", ".join(absent))

    last_state = None
    try:
        budget = {
            "web_search_max": args.web_search_max,
            "fetch_max": args.fetch_max,
            "tool_timeout_seconds": args.tool_timeout,
            "tool_retries": args.tool_retries,
        }
        last_state = initial_state(
            mode=args.mode,
            technologies=tuple(args.technologies),
            domain=args.domain,
            model_id=model_id,
            paper_dir=str(args.paper_dir) if args.paper_dir else None,
            as_of=args.as_of,
            budget=budget,
            max_paper_pages=args.max_paper_pages,
            fixture=args.fixture,
        )
        if args.fixture:
            from skala_rag.graph.demo import create_services

            services = create_services()
        else:
            services = _load_services(services_spec)
        if llm_output:
            from langchain_openai import ChatOpenAI

            from skala_rag.agents.llm_output import LLMReportAgent, LLMSynthesisAgent

            model = ChatOpenAI(model=model_id)
            services.synthesis_writer = services.synthesis_writer or LLMSynthesisAgent(model)
            services.report_writer = services.report_writer or LLMReportAgent(model)
        else:
            services.synthesis_writer = None
            services.report_writer = None
        if review_enabled:
            if services.semantic_review is None:
                from langchain_openai import ChatOpenAI

                from skala_rag.agents.review import LLMSemanticReviewer

                # Separate model instance and prompt: review is a distinct call from generation.
                services.semantic_review = LLMSemanticReviewer(ChatOpenAI(model=model_id), max_calls=args.max_review_calls)
        else:
            services.semantic_review = None
        graph = build_graph(services, output_dir=args.output_dir, report_name=args.report_name)
        for snapshot in graph.stream(last_state, config={"recursion_limit": args.recursion_limit}, stream_mode="values"):
            last_state = snapshot
        result = last_state
    except Exception as exc:
        if last_state is not None:
            failure = dict(last_state)
            errors = dict(failure.get("errors") or {})
            errors["pipeline-0"] = {"node": "pipeline", "reason": f"{type(exc).__name__}: {exc}", "fatal": True, "recovered": False, "kind": "pipeline"}
            failure["errors"] = errors
            try:
                save_outputs(failure, args.output_dir, report_name=args.report_name)
            except Exception as output_exc:
                print(f"실패 기록 저장 불가: {output_exc}", file=sys.stderr)
        print(f"실행 실패: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    for kind, path in result.get("artifacts", {}).items():
        print(f"{kind}: {path}")
    if any(item.get("fatal") for item in result.get("errors", {}).values()):
        print("필수 단계 실패; run_manifest.json 확인", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
