import pytest
from allocator.engine.sql_mi import allocate
from allocator.ingestion.sql_mi import SqlMiRecord

def _make_records(tenant_hours: dict) -> list:
    records = []
    for tenant_id, hours in tenant_hours.items():
        for h, cpu in enumerate(hours):
            records.append(SqlMiRecord(tenant_id=tenant_id, hour=h, total_cpu_sec=cpu))
    return records


def test_zero_leak_basic():
    records = _make_records({"a": [100.0] * 24, "b": [200.0] * 24})
    costs = allocate(records, cost_total=50.0)
    assert abs(sum(costs.values()) - 50.0) < 0.01


def test_zero_leak_three_tenants(mock_data_dir):
    from allocator.config import load_tenant_map
    from allocator.ingestion.sql_mi import load_mock
    tm = load_tenant_map(mock_data_dir)
    records = load_mock(mock_data_dir, tm.databases)
    costs = allocate(records, cost_total=50.0)
    assert abs(sum(costs.values()) - 50.0) < 0.01


def test_peak_shaving_fairness():
    """Invariant 3: spike tenant (equal total CPU-sec) must pay less than steady tenant."""
    spike = [2400.0] + [0.0] * 23
    steady = [100.0] * 24
    records = _make_records({"spike": spike, "steady": steady})
    costs = allocate(records, cost_total=50.0)
    assert costs["spike"] < costs["steady"], (
        f"Peak-shaving failed: spike={costs['spike']}, steady={costs['steady']}"
    )


def test_all_zero_usage_equal_split():
    records = _make_records({"a": [0.0] * 24, "b": [0.0] * 24})
    costs = allocate(records, cost_total=10.0)
    assert abs(sum(costs.values()) - 10.0) < 0.01
    assert abs(costs["a"] - costs["b"]) < 0.01


def test_single_tenant_absorbs_all():
    records = _make_records({"only": [100.0] * 24})
    costs = allocate(records, cost_total=50.0)
    assert abs(costs["only"] - 50.0) < 0.01


def test_proportional_without_spike():
    records = _make_records({"a": [100.0] * 24, "b": [300.0] * 24})
    costs = allocate(records, cost_total=40.0)
    assert abs(costs["a"] - 10.0) < 0.02
    assert abs(costs["b"] - 30.0) < 0.02
