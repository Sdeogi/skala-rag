"""Command-line entry point for the graph/output branch."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path

# The repository uses a src layout; make the documented `python app.py` work
# before the package has been installed in a newly created virtualenv.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from skala_rag.graph.workflow import PipelineServices, build_graph, initial_state
from skala_rag.agents.report import save_outputs


def _load_services(spec: str) -> PipelineServices:
    module_name, separator, factory_name = spec.partition(":")
    if not separator or not module_name or not factory_name:
        raise ValueError("--services must be module.path:factory")
    factory = getattr(importlib.import_module(module_name), factory_name)
    services = factory()
    if not isinstance(services, PipelineServices):
        raise TypeError("service factory must return PipelineServices")
    return services


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KV cache 다관점 RAG 그래프 실행")
    parser.add_argument("--mode", choices=("live", "replay"), required=True)
    parser.add_argument("--services", help="통합 서비스 factory: module.path:factory")
    parser.add_argument("--fixture", action="store_true", help="합성 자료로 그래프만 검증; 실제 평가에 사용 금지")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--paper-dir", type=Path)
    parser.add_argument("--model-id", default=os.environ.get("RAG_MODEL_ID", "gpt-5.4-mini"))
    parser.add_argument("--deterministic-output", action="store_true", help="live에서도 규칙 기반 종합과 보고서 사용")
    args = parser.parse_args(argv)
    if args.fixture and args.services:
        parser.error("--fixture and --services cannot be combined")
    if args.fixture and args.mode != "replay":
        parser.error("--fixture is only available in replay mode")
    if not args.fixture and not args.services:
        parser.error("--services is required until the A/B/C integration adapters are merged")
    if args.paper_dir and not args.paper_dir.is_dir():
        parser.error(f"paper directory does not exist: {args.paper_dir}")
    if args.mode == "live":
        absent = [name for name in ("OPENAI_API_KEY", "TAVILY_API_KEY") if not os.environ.get(name)]
        if absent:
            parser.error("missing configuration: " + ", ".join(absent))
    state = None
    try:
        if args.fixture:
            from skala_rag.graph.demo import create_services
            services = create_services()
        else:
            services = _load_services(args.services)
        if args.mode == "live" and not args.deterministic_output:
            from langchain_openai import ChatOpenAI
            from skala_rag.agents.llm_output import LLMSynthesisAgent, LLMReportAgent
            model = ChatOpenAI(model=args.model_id)
            services.synthesis_writer = services.synthesis_writer or LLMSynthesisAgent(model)
            services.report_writer = services.report_writer or LLMReportAgent(model)
        elif args.mode == "replay":
            services.synthesis_writer = None
            services.report_writer = None
        state = initial_state(mode=args.mode, model_id=args.model_id, paper_dir=str(args.paper_dir) if args.paper_dir else None)
        if args.fixture:
            state["run_config"]["fixture"] = True
        result = build_graph(services, output_dir=args.output_dir).invoke(state, config={"recursion_limit": 50})
    except Exception as exc:
        if state is not None:
            failure = dict(state)
            failure["errors"] = {"pipeline-0": {"node": "pipeline", "reason": f"{type(exc).__name__}: {exc}", "fatal": True, "recovered": False}}
            try:
                save_outputs(failure, args.output_dir)
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
