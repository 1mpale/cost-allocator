import subprocess
import sys
import json
from pathlib import Path
from main import run


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


def test_integration_zero_leak_all_resources(tmp_path):
    """SC-1: sum of allocated tenant costs == total for each resource."""
    from allocator.config import load_billing_config
    config = load_billing_config(Path(__file__).parent.parent / "mock_data")

    out = tmp_path / "report.json"
    report = run(str(out))

    data = json.loads(out.read_text())

    sql_sum = sum(a["sql_mi_cost"] for a in data["allocations"])
    agw_sum = sum(a["agw_cost"] for a in data["allocations"])
    fw_sum  = sum(a["firewall_cost"] for a in data["allocations"])

    assert abs(sql_sum - config.sql_mi_daily_cost_eur) < 0.01, f"SQL MI leak: {sql_sum} != {config.sql_mi_daily_cost_eur}"
    assert abs(agw_sum - config.agw_daily_cost_eur) < 0.01, f"AGW leak: {agw_sum} != {config.agw_daily_cost_eur}"
    assert abs(fw_sum  - config.firewall_daily_cost_eur) < 0.01, f"FW leak: {fw_sum} != {config.firewall_daily_cost_eur}"


def test_integration_peak_shaving_fairness(tmp_path):
    """SC-2: In mock data, customer_a (spike) must pay less SQL MI than customer_b (steady, equal total CPU)."""
    out = tmp_path / "report.json"
    run(str(out))

    data = json.loads(out.read_text())
    by_tenant = {a["tenant_id"]: a for a in data["allocations"]}

    assert by_tenant["customer_a"]["sql_mi_cost"] < by_tenant["customer_b"]["sql_mi_cost"], (
        f"Peak-shaving failed: customer_a={by_tenant['customer_a']['sql_mi_cost']}, "
        f"customer_b={by_tenant['customer_b']['sql_mi_cost']}"
    )


def test_integration_json_schema(tmp_path):
    """SC-3: Output JSON matches required schema."""
    out = tmp_path / "report.json"
    run(str(out))
    data = json.loads(out.read_text())

    assert isinstance(data["date"], str)
    assert isinstance(data["total_shared_cost_allocated"], float)
    assert isinstance(data["allocations"], list)
    assert len(data["allocations"]) == 3

    for alloc in data["allocations"]:
        for field in ("tenant_id", "sql_mi_cost", "agw_cost", "firewall_cost", "total_cost"):
            assert field in alloc, f"Missing field '{field}' in allocation"
        assert abs(alloc["total_cost"] - (alloc["sql_mi_cost"] + alloc["agw_cost"] + alloc["firewall_cost"])) < 0.01


def test_integration_unattributed_warning_emitted(tmp_path, capsys):
    """SC-7: firewall_logs.json has an unattributed IP — warning on stderr, no cost leak."""
    out = tmp_path / "report.json"
    run(str(out))
    captured = capsys.readouterr()
    assert "10.200.99.1" in captured.err, "Expected unattributed IP warning on stderr"
