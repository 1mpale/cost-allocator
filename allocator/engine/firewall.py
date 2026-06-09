import ipaddress
import sys
from typing import Dict, List, Optional, Tuple

from allocator.ingestion.firewall import FirewallRecord


def _match_ip(ip_str: str, subnet_map: Dict[str, str]) -> Optional[str]:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return None
    best, best_prefix = None, -1
    for cidr, tenant_id in subnet_map.items():
        net = ipaddress.ip_network(cidr, strict=False)
        if ip in net and net.prefixlen > best_prefix:
            best, best_prefix = tenant_id, net.prefixlen
    return best


def allocate(
    records: List[FirewallRecord],
    subnet_map: Dict[str, str],
    cost_total: float,
    known_tenants: List[str],
) -> Tuple[Dict[str, float], int]:
    tenants = sorted(known_tenants)
    n = len(tenants)

    if not records:
        return _equal_split(tenants, cost_total), 0

    tenant_bytes: Dict[str, int] = {}
    unattributed_bytes = 0
    warn_count = 0

    for r in records:
        tenant = _match_ip(r.source_ip, subnet_map) or _match_ip(r.destination_ip, subnet_map)
        if tenant:
            tenant_bytes[tenant] = tenant_bytes.get(tenant, 0) + r.network_bytes
        else:
            unattributed_bytes += r.network_bytes
            warn_count += 1
            print(
                f"WARNING: unattributed firewall traffic src={r.source_ip} "
                f"dst={r.destination_ip} bytes={r.network_bytes}",
                file=sys.stderr,
            )

    sum_attributed = sum(tenant_bytes.values())
    sum_all = sum_attributed + unattributed_bytes

    if sum_all == 0:
        return _equal_split(tenants, cost_total), warn_count

    attributed_cost = cost_total * (sum_attributed / sum_all)
    unattributed_cost = cost_total * (unattributed_bytes / sum_all)
    unattr_share_per_tenant = unattributed_cost / n

    costs: Dict[str, float] = {}
    for t in tenants[:-1]:
        prop = tenant_bytes.get(t, 0) / sum_attributed if sum_attributed > 0 else 0.0
        costs[t] = round(prop * attributed_cost + unattr_share_per_tenant, 2)
    costs[tenants[-1]] = round(cost_total - sum(costs.values()), 2)

    return costs, warn_count


def _equal_split(tenants: List[str], cost_total: float) -> Dict[str, float]:
    n = len(tenants)
    costs: Dict[str, float] = {}
    for t in tenants[:-1]:
        costs[t] = round(cost_total / n, 2)
    costs[tenants[-1]] = round(cost_total - sum(costs.values()), 2)
    return costs
