import pytest
from allocator.engine.firewall import allocate
from allocator.ingestion.firewall import FirewallRecord

SUBNETS = {
    "10.100.1.0/24": "customer_a",
    "10.100.2.0/24": "customer_b",
    "10.100.3.0/24": "customer_c",
}
TENANTS = ["customer_a", "customer_b", "customer_c"]


def test_zero_leak_fully_attributed():
    records = [
        FirewallRecord("10.100.1.10", "8.8.8.8", 500_000_000),
        FirewallRecord("10.100.2.10", "8.8.8.8", 800_000_000),
        FirewallRecord("10.100.3.10", "8.8.8.8", 300_000_000),
    ]
    costs, _ = allocate(records, SUBNETS, cost_total=30.0, known_tenants=TENANTS)
    assert abs(sum(costs.values()) - 30.0) < 0.01


def test_zero_leak_with_unattributed(capsys):
    records = [
        FirewallRecord("10.100.1.10", "8.8.8.8", 500_000_000),
        FirewallRecord("10.200.99.1", "8.8.8.8", 100_000_000),
    ]
    costs, _ = allocate(records, SUBNETS, cost_total=30.0, known_tenants=TENANTS)
    assert abs(sum(costs.values()) - 30.0) < 0.01


def test_unattributed_ip_emits_warning(capsys):
    records = [
        FirewallRecord("10.100.1.10", "8.8.8.8", 500_000_000),
        FirewallRecord("10.200.99.1", "8.8.8.8", 100_000_000),
    ]
    _, warn_count = allocate(records, SUBNETS, cost_total=30.0, known_tenants=TENANTS)
    assert warn_count == 1
    captured = capsys.readouterr()
    assert "10.200.99.1" in captured.err


def test_destination_ip_fallback():
    """If source IP is unattributed, destination IP is tried (PDF §3.3 rule)."""
    records = [
        FirewallRecord("10.200.99.1", "10.100.2.10", 400_000_000),
    ]
    costs, warn_count = allocate(records, SUBNETS, cost_total=30.0, known_tenants=TENANTS)
    assert warn_count == 0
    assert costs["customer_b"] > 0


def test_proportional_allocation():
    records = [
        FirewallRecord("10.100.1.10", "8.8.8.8", 500),
        FirewallRecord("10.100.2.10", "8.8.8.8", 800),
        FirewallRecord("10.100.3.10", "8.8.8.8", 300),
    ]
    costs, _ = allocate(records, SUBNETS, cost_total=160.0, known_tenants=TENANTS)
    assert abs(costs["customer_a"] - 50.0) < 0.02
    assert abs(costs["customer_b"] - 80.0) < 0.02


def test_all_zero_equal_split():
    records = []
    costs, _ = allocate(records, SUBNETS, cost_total=30.0, known_tenants=TENANTS)
    assert abs(sum(costs.values()) - 30.0) < 0.01
    assert all(abs(v - 10.0) < 0.01 for v in costs.values())


def test_load_mock(mock_data_dir):
    from allocator.ingestion.firewall import load_mock
    records = load_mock(mock_data_dir)
    assert len(records) == 4
    assert any(r.source_ip == "10.200.99.1" for r in records)
