from dataclasses import dataclass
from typing import List


@dataclass
class TenantAllocation:
    tenant_id: str
    sql_mi_cost: float
    agw_cost: float
    firewall_cost: float

    @property
    def total_cost(self) -> float:
        return round(self.sql_mi_cost + self.agw_cost + self.firewall_cost, 2)


@dataclass
class AllocationReport:
    date: str
    allocations: List[TenantAllocation]

    @property
    def total_shared_cost_allocated(self) -> float:
        return round(sum(a.total_cost for a in self.allocations), 2)
