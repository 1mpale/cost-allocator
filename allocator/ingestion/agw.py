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
