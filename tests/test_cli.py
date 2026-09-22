import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args, env=None, cwd=ROOT):
    return subprocess.run([sys.executable, str(ROOT / "app.py"), *args], cwd=cwd, env=env, capture_output=True, text=True, check=False)


def test_documented_direct_cli_runs_without_pythonpath(tmp_path):
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    completed = run_cli("--mode", "replay", "--fixture", "--output-dir", str(tmp_path), env=environment)
    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "report.pdf").stat().st_size > 1000
    assert "합성 fixture" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_cli_defaults_to_integration_services_and_checks_llm_key(tmp_path):
    environment = {key: value for key, value in os.environ.items() if key not in ("OPENAI_API_KEY", "TAVILY_API_KEY")}
    environment["RAG_DISABLE_DOTENV"] = "1"
    completed = run_cli("--mode", "replay", "--output-dir", str(tmp_path / "out"), env=environment)
    assert completed.returncode != 0
    assert "--services is required" not in completed.stderr
    assert "OPENAI_API_KEY" in completed.stderr or "실행 실패" in completed.stderr


def test_cli_report_name_and_options(tmp_path):
    completed = run_cli("--mode", "replay", "--fixture", "--output-dir", str(tmp_path), "--report-name", "RAG-Output_판교_10반_test", "--as-of", "2026-09-22", "--web-search-max", "5")
    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "RAG-Output_판교_10반_test.md").exists()
    manifest = (tmp_path / "run_manifest.json").read_text(encoding="utf-8")
    assert '"as_of": "2026-09-22"' in manifest and '"web_search_max": 5' in manifest


def test_cli_draw_graph_writes_mermaid(tmp_path):
    target = tmp_path / "graph.mmd"
    completed = run_cli("--draw-graph", str(target))
    assert completed.returncode == 0, completed.stderr
    assert "repair --> evidence_check;" in target.read_text(encoding="utf-8")


def test_cli_failing_services_module_writes_failure_manifest(tmp_path):
    (tmp_path / "broken_services.py").write_text("def create_services():\n    raise ImportError('adapter missing')\n", encoding="utf-8")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(tmp_path)
    environment.setdefault("OPENAI_API_KEY", "test-key-never-used")  # the factory fails before any model call
    completed = run_cli("--mode", "replay", "--services", "broken_services:create_services", "--output-dir", str(tmp_path / "out"), env=environment)
    assert completed.returncode == 1 and "adapter missing" in completed.stderr
    manifest = (tmp_path / "out" / "run_manifest.json").read_text(encoding="utf-8")
    assert '"status": "failed"' in manifest and "pipeline-0" in manifest
