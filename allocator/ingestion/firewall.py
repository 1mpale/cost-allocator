import json
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class FirewallRecord:
    source_ip: str
    destination_ip: str
    network_bytes: int


def load_mock(data_dir: Path) -> List[FirewallRecord]:
    path = data_dir / "firewall_logs.json"
    with open(path) as f:
        raw = json.load(f)
    return [
        FirewallRecord(
            source_ip=row["source_ip"],
            destination_ip=row["destination_ip"],
            network_bytes=int(row["network_bytes"]),
        )
        for row in raw
    ]


def load_live(workspace_id: str, credential) -> List[FirewallRecord]:
    """All live imports inside this function."""
    try:
        from azure.monitor.query import LogsQueryClient, LogsQueryStatus
        import datetime
    except ImportError:
        raise ImportError("Install live deps: pip install -r requirements-live.txt")

    KQL_MODERN = """
AZFWNetworkRule
| where TimeGenerated >= startofday(now()) and TimeGenerated < now()
| extend NetworkBytes = toint(coalesce(OutboundBytes, 0)) + toint(coalesce(InboundBytes, 0))
| summarize NetworkBytes = sum(NetworkBytes) by SourceIP = SrcIP, DestinationIP = DstIP
"""
    KQL_LEGACY = """
AzureDiagnostics
| where Category == "AzureFirewallNetworkRule"
| where TimeGenerated >= startofday(now()) and TimeGenerated < now()
| parse msg_s with * "from " SourceIP ":" * " to " DestinationIP ":" * "." *
| extend NetworkBytes = toint(coalesce(sent_bytes_d, 0)) + toint(coalesce(received_bytes_d, 0))
| where isnotempty(SourceIP) and isnotempty(DestinationIP)
| summarize NetworkBytes = sum(NetworkBytes) by SourceIP, DestinationIP
"""
    client = LogsQueryClient(credential)

    def _query(kql):
        resp = client.query_workspace(workspace_id=workspace_id, query=kql, timespan=datetime.timedelta(days=1))
        if resp.status == LogsQueryStatus.SUCCESS and resp.tables and resp.tables[0].rows:
            return resp.tables[0].rows
        return []

    rows = _query(KQL_MODERN) or _query(KQL_LEGACY)
    records = []
    for row in rows:
        src, dst, nbytes = str(row[0] or ""), str(row[1] or ""), int(row[2] or 0)
        if src and dst:
            records.append(FirewallRecord(source_ip=src, destination_ip=dst, network_bytes=nbytes))
    return records
