import subprocess
import sys
import json
from pathlib import Path


def test_cli_smoke(tmp_path):
    out = tmp_path / "report.json"
    result = subprocess.run(
        [sys.executable, "main.py", "--output", str(out)],
        capture_output=True, text=True,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0, f"CLI failed:\n{result.stderr}"
    assert out.exists(), "Output file not created"
    data = json.loads(out.read_text())
    assert "date" in data
    assert "allocations" in data
