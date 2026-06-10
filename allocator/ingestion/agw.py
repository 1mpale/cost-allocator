import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass
class AgwRecord:
    tenant_id: str
    request_count: int
    total_bytes: int


def load_mock(data_dir: Path, hostname_to_tenant: Dict[str, str]) -> List[AgwRecord]:
    path = data_dir / "agw_logs.json"
    with open(path) as f:
        raw = json.load(f)
    records = []
    for row in raw:
        tenant_id = hostname_to_tenant.get(row["tenant_host"])
        if tenant_id:
            records.append(AgwRecord(
                tenant_id=tenant_id,
                request_count=int(row["request_count"]),
                total_bytes=int(row["total_bytes"]),
            ))
    return records


def load_live(workspace_id: str, credential, hostname_to_tenant: Dict[str, str]) -> List[AgwRecord]:
    """All live imports inside this function."""
    try:
        from azure.monitor.query import LogsQueryClient, LogsQueryStatus
        import datetime
    except ImportError:
        raise ImportError("Install live deps: pip install -r requirements-live.txt")

    KQL = """
AzureDiagnostics
| where ResourceProvider == "MICROSOFT.NETWORK" and Category == "ApplicationGatewayAccessLog"
| where TimeGenerated >= startofday(now()) and TimeGenerated < now()
| extend TenantHost = host_s
| extend BytesSent = toint(originalRequestBytes_d) + toint(responseBodyBytes_d)
| summarize RequestCount = count(), TotalBytes = sum(BytesSent) by TenantHost
"""
    client = LogsQueryClient(credential)
    response = client.query_workspace(
        workspace_id=workspace_id,
        query=KQL,
        timespan=datetime.timedelta(days=1),
    )
    records = []
    if response.status == LogsQueryStatus.SUCCESS:
        for row in response.tables[0].rows:
            tenant_host = str(row[0]) if row[0] else ""
            tenant_id = hostname_to_tenant.get(tenant_host)
            if tenant_id:
                records.append(AgwRecord(
                    tenant_id=tenant_id,
                    request_count=int(row[1] or 0),
                    total_bytes=int(row[2] or 0),
                ))
    return records
