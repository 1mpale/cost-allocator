import argparse
import os
from pathlib import Path

from allocator.config import load_billing_config, load_tenant_map
from allocator.ingestion.sql_mi import load_mock as load_sql_mi_mock, load_live as load_sql_mi_live
from allocator.ingestion.agw import load_mock as load_agw_mock, load_live as load_agw_live
from allocator.ingestion.firewall import load_mock as load_firewall_mock, load_live as load_firewall_live
from allocator.engine.sql_mi import allocate as allocate_sql_mi
from allocator.engine.agw import allocate as allocate_agw
from allocator.engine.firewall import allocate as allocate_firewall
from allocator.models import AllocationReport, TenantAllocation
from allocator.report import print_table, save_json

DATA_DIR = Path(__file__).parent / "mock_data"


def run(output_path: str) -> AllocationReport:
    import os
    mode = os.environ.get("ALLOCATION_MODE", "mock").lower()

    config = load_billing_config(DATA_DIR)
    tenant_map = load_tenant_map(DATA_DIR)

    known_tenants = sorted(set(tenant_map.databases.values()))

    if mode == "live":
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
        workspace_id = os.environ["LOG_ANALYTICS_WORKSPACE_ID"]

        sql_fqdn = os.environ["SQL_SERVER_FQDN"]
        sql_password = os.environ["SQL_ADMIN_PASSWORD"]
        connection_strings = {
            db_name: (
                f"Driver={{ODBC Driver 18 for SQL Server}};"
                f"Server=tcp:{sql_fqdn},1433;Database={db_name};"
                f"Uid=sqladmin;Pwd={sql_password};"
                f"Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
            )
            for db_name in tenant_map.databases.keys()
        }

        sql_records = load_sql_mi_live(tenant_map.databases, connection_strings)
        agw_records = load_agw_live(workspace_id, credential, tenant_map.hostnames)
        fw_records = load_firewall_live(workspace_id, credential)
    else:
        sql_records = load_sql_mi_mock(DATA_DIR, tenant_map.databases)
        agw_records = load_agw_mock(DATA_DIR, tenant_map.hostnames)
        fw_records = load_firewall_mock(DATA_DIR)

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
