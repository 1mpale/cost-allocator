from typing import Dict, List

from allocator.ingestion.agw import AgwRecord

W_REQ = 0.3
W_DATA = 0.7


def allocate(records: List[AgwRecord], cost_total: float) -> Dict[str, float]:
    if not records:
        return {}

    tenants = sorted(r.tenant_id for r in records)
    n = len(tenants)
    by_tenant = {r.tenant_id: r for r in records}

    total_requests = sum(r.request_count for r in records)
    total_bytes = sum(r.total_bytes for r in records)

    weights: Dict[str, float] = {}
    for t in tenants:
        r = by_tenant.get(t)
        req = r.request_count if r else 0
        byt = r.total_bytes if r else 0

        if total_requests == 0 and total_bytes == 0:
            w = 1.0 / n
        elif total_requests == 0:
            w = byt / total_bytes
        elif total_bytes == 0:
            w = req / total_requests
        else:
            w = W_REQ * (req / total_requests) + W_DATA * (byt / total_bytes)
        weights[t] = w

    costs: Dict[str, float] = {}
    for t in tenants[:-1]:
        costs[t] = round(weights[t] * cost_total, 2)
    costs[tenants[-1]] = round(cost_total - sum(costs.values()), 2)
    return costs
