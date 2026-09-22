import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_documented_direct_cli_runs_without_pythonpath(tmp_path):
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "app.py", "--mode", "replay", "--fixture", "--output-dir", str(tmp_path)],
        cwd=ROOT, env=environment, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "report.pdf").stat().st_size > 1000
    assert "합성 fixture" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_cli_explains_missing_integration_services():
    completed = subprocess.run([sys.executable, "app.py", "--mode", "replay"], cwd=ROOT, capture_output=True, text=True, check=False)
    assert completed.returncode != 0
    assert "--services is required" in completed.stderr
