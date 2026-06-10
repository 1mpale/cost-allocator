import pytest
from allocator.engine.agw import allocate
from allocator.ingestion.agw import AgwRecord


def test_zero_leak():
    records = [
        AgwRecord("a", 5000, 10_000_000),
        AgwRecord("b", 3000, 25_000_000),
        AgwRecord("c", 2000,  5_000_000),
    ]
    costs = allocate(records, cost_total=15.0)
    assert abs(sum(costs.values()) - 15.0) < 0.01


def test_weighted_index_data_dominates():
    """Tenant with more bytes but fewer requests pays more (W_data=0.7 > W_req=0.3)."""
    records = [
        AgwRecord("small_req_big_bytes", request_count=1000, total_bytes=90_000_000),
        AgwRecord("big_req_small_bytes",  request_count=9000, total_bytes=10_000_000),
    ]
    costs = allocate(records, cost_total=100.0)
    assert costs["small_req_big_bytes"] > costs["big_req_small_bytes"]


def test_zero_requests_falls_back_to_bytes():
    records = [
        AgwRecord("a", request_count=0, total_bytes=30_000_000),
        AgwRecord("b", request_count=0, total_bytes=70_000_000),
    ]
    costs = allocate(records, cost_total=10.0)
    assert abs(costs["a"] - 3.0) < 0.02
    assert abs(costs["b"] - 7.0) < 0.02


def test_both_zero_equal_split():
    records = [AgwRecord("a", 0, 0), AgwRecord("b", 0, 0)]
    costs = allocate(records, cost_total=10.0)
    assert abs(costs["a"] - 5.0) < 0.01
    assert abs(costs["b"] - 5.0) < 0.01


def test_load_mock(mock_data_dir):
    from allocator.config import load_tenant_map
    from allocator.ingestion.agw import load_mock
    tm = load_tenant_map(mock_data_dir)
    records = load_mock(mock_data_dir, tm.hostnames)
    assert len(records) == 3
    tenant_ids = {r.tenant_id for r in records}
    assert tenant_ids == {"customer_a", "customer_b", "customer_c"}
