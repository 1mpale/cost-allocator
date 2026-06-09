from pathlib import Path
from allocator.config import load_billing_config, load_tenant_map, BillingConfig, TenantMap

def test_load_billing_config(mock_data_dir):
    config = load_billing_config(mock_data_dir)
    assert isinstance(config, BillingConfig)
    assert config.date == "2026-06-09"
    assert config.sql_mi_daily_cost_eur == 50.0
    assert config.agw_daily_cost_eur == 15.0
    assert config.firewall_daily_cost_eur == 30.0

def test_load_tenant_map(mock_data_dir):
    tm = load_tenant_map(mock_data_dir)
    assert isinstance(tm, TenantMap)
    assert tm.databases["db_tenant_customer_a"] == "customer_a"
    assert tm.subnets["10.100.1.0/24"] == "customer_a"
    assert tm.hostnames["customer-a.oursharedapp.com"] == "customer_a"

def test_missing_billing_file_raises():
    import pytest
    with pytest.raises(FileNotFoundError):
        load_billing_config(Path("/nonexistent"))
