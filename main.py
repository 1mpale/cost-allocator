import argparse
from pathlib import Path

from allocator.config import load_billing_config, load_tenant_map
from allocator.ingestion.sql_mi import load_mock as load_sql_mi
from allocator.ingestion.agw import load_mock as load_agw
from allocator.ingestion.firewall import load_mock as load_firewall
from allocator.engine.sql_mi import allocate as allocate_sql_mi
from allocator.engine.agw import allocate as allocate_agw
from allocator.engine.firewall import allocate as allocate_firewall
from allocator.models import AllocationReport, TenantAllocation
from allocator.report import print_table, save_json

DATA_DIR = Path(__file__).parent / "mock_data"


def run(output_path: str) -> AllocationReport:
    config = load_billing_config(DATA_DIR)
    tenant_map = load_tenant_map(DATA_DIR)

    known_tenants = sorted(set(tenant_map.databases.values()))

    sql_records = load_sql_mi(DATA_DIR, tenant_map.databases)
    agw_records = load_agw(DATA_DIR, tenant_map.hostnames)
    fw_records = load_firewall(DATA_DIR)

    sql_costs = allocate_sql_mi(sql_records, config.sql_mi_daily_cost_eur)
    agw_costs = allocate_agw(agw_records, config.agw_daily_cost_eur)
    fw_costs, _ = allocate_firewall(fw_records, tenant_map.subnets, config.firewall_daily_cost_eur, known_tenants)

    allocations = [
        TenantAllocation(
            tenant_id=t,
            sql_mi_cost=sql_costs.get(t, 0.0),
            agw_cost=agw_costs.get(t, 0.0),
            firewall_cost=fw_costs.get(t, 0.0),
        )
        for t in known_tenants
    ]

    report = AllocationReport(date=config.date, allocations=allocations)
    print_table(report)
    save_json(report, output_path)
    return report


def main():
    parser = argparse.ArgumentParser(description="Azure Shared Resource Cost Allocator")
    parser.add_argument(
        "--output", default="daily_cost_report.json",
        help="Path to write JSON report (default: daily_cost_report.json)"
    )
    args = parser.parse_args()
    run(args.output)


if __name__ == "__main__":
    main()
