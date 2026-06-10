import json
from allocator.models import AllocationReport


def print_table(report: AllocationReport) -> None:
    print(f"\nDaily Cost Report — {report.date}")
    print(f"Total allocated: €{report.total_shared_cost_allocated:.2f}\n")
    header = f"{'Tenant':<22} {'SQL MI':>10} {'AGW':>10} {'Firewall':>10} {'Total':>10}"
    print(header)
    print("─" * len(header))
    for a in sorted(report.allocations, key=lambda x: x.tenant_id):
        print(
            f"{a.tenant_id:<22} €{a.sql_mi_cost:>9.2f} €{a.agw_cost:>9.2f} "
            f"€{a.firewall_cost:>9.2f} €{a.total_cost:>9.2f}"
        )
    print()


def save_json(report: AllocationReport, output_path: str) -> None:
    data = {
        "date": report.date,
        "total_shared_cost_allocated": report.total_shared_cost_allocated,
        "allocations": [
            {
                "tenant_id": a.tenant_id,
                "sql_mi_cost": a.sql_mi_cost,
                "agw_cost": a.agw_cost,
                "firewall_cost": a.firewall_cost,
                "total_cost": a.total_cost,
            }
            for a in sorted(report.allocations, key=lambda x: x.tenant_id)
        ],
    }
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
