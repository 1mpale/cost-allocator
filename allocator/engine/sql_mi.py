import numpy as np
from typing import Dict, List

from allocator.ingestion.sql_mi import SqlMiRecord


def allocate(
    records: List[SqlMiRecord],
    cost_total: float,
    p_shave_percentile: float = 90.0,
) -> Dict[str, float]:
    if not records:
        return {}

    all_cpu = [r.total_cpu_sec for r in records]
    p_shave = float(np.percentile(all_cpu, p_shave_percentile))

    tenant_sums: Dict[str, float] = {}
    for r in records:
        shaved = min(r.total_cpu_sec, p_shave)
        tenant_sums[r.tenant_id] = tenant_sums.get(r.tenant_id, 0.0) + shaved

    tenants = sorted(tenant_sums.keys())
    total_sum = sum(tenant_sums.values())

    if total_sum == 0.0:
        return _equal_split(tenants, cost_total)

    costs: Dict[str, float] = {}
    for t in tenants[:-1]:
        costs[t] = round(tenant_sums[t] / total_sum * cost_total, 2)
    costs[tenants[-1]] = round(cost_total - sum(costs.values()), 2)

    _assert_zero_leak(costs, cost_total)
    return costs


def _equal_split(tenants: List[str], cost_total: float) -> Dict[str, float]:
    n = len(tenants)
    costs: Dict[str, float] = {}
    for t in tenants[:-1]:
        costs[t] = round(cost_total / n, 2)
    costs[tenants[-1]] = round(cost_total - sum(costs.values()), 2)
    return costs


def _assert_zero_leak(costs: Dict[str, float], cost_total: float) -> None:
    residual = abs(cost_total - sum(costs.values()))
    if residual > 0.01:
        raise ValueError(f"Zero-leak violation: residual={residual:.4f}")
