import json

from allocator.models import AllocationReport, TenantAllocation
from allocator.report import print_table, save_json


def _sample_report():
    return AllocationReport(
        date="2026-06-09",
        allocations=[
            TenantAllocation("customer_a", sql_mi_cost=14.71, agw_cost=3.75, firewall_cost=9.38),
            TenantAllocation("customer_b", sql_mi_cost=28.24, agw_cost=9.38, firewall_cost=15.00),
            TenantAllocation("customer_c", sql_mi_cost=7.05, agw_cost=1.87, firewall_cost=5.62),
        ],
    )


def test_total_shared_cost_allocated():
    report = _sample_report()
    expected = round(
        14.71 + 3.75 + 9.38 +
        28.24 + 9.38 + 15.00 +
        7.05 + 1.87 + 5.62,
        2,
    )
    assert report.total_shared_cost_allocated == expected


def test_save_json_schema(tmp_path):
    report = _sample_report()
    out = tmp_path / "report.json"
    save_json(report, str(out))
    with open(out) as f:
        data = json.load(f)
    assert "date" in data
    assert "total_shared_cost_allocated" in data
    assert "allocations" in data
    alloc = data["allocations"][0]
    for field in ("tenant_id", "sql_mi_cost", "agw_cost", "firewall_cost", "total_cost"):
        assert field in alloc, f"Missing field: {field}"


def test_save_json_zero_leak(tmp_path):
    report = _sample_report()
    out = tmp_path / "report.json"
    save_json(report, str(out))
    with open(out) as f:
        data = json.load(f)
    total = data["total_shared_cost_allocated"]
    summed = sum(a["total_cost"] for a in data["allocations"])
    assert abs(total - summed) < 0.01


def test_print_table_contains_all_tenants(capsys):
    report = _sample_report()
    print_table(report)
    captured = capsys.readouterr()
    assert "customer_a" in captured.out
    assert "customer_b" in captured.out
    assert "customer_c" in captured.out
    assert "2026-06-09" in captured.out
