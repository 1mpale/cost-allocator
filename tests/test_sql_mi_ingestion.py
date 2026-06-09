from allocator.ingestion.sql_mi import load_mock, SqlMiRecord

def test_load_mock_returns_records(mock_data_dir):
    from allocator.config import load_tenant_map
    tm = load_tenant_map(mock_data_dir)
    records = load_mock(mock_data_dir, tm.databases)
    assert len(records) == 72
    assert all(isinstance(r, SqlMiRecord) for r in records)

def test_load_mock_maps_db_to_tenant(mock_data_dir):
    from allocator.config import load_tenant_map
    tm = load_tenant_map(mock_data_dir)
    records = load_mock(mock_data_dir, tm.databases)
    tenant_ids = {r.tenant_id for r in records}
    assert tenant_ids == {"customer_a", "customer_b", "customer_c"}

def test_load_mock_spike_hour_present(mock_data_dir):
    from allocator.config import load_tenant_map
    tm = load_tenant_map(mock_data_dir)
    records = load_mock(mock_data_dir, tm.databases)
    spike = [r for r in records if r.tenant_id == "customer_a" and r.hour == 0]
    assert len(spike) == 1
    assert spike[0].total_cpu_sec == 2400.0
