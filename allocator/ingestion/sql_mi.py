import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass
class SqlMiRecord:
    tenant_id: str
    hour: int
    total_cpu_sec: float


def load_mock(data_dir: Path, db_to_tenant: Dict[str, str]) -> List[SqlMiRecord]:
    path = data_dir / "sql_mi_dmv.json"
    with open(path) as f:
        raw = json.load(f)
    records = []
    for row in raw:
        tenant_id = db_to_tenant.get(row["database_name"])
        if tenant_id:
            records.append(SqlMiRecord(
                tenant_id=tenant_id,
                hour=row["hour"],
                total_cpu_sec=float(row["total_cpu_sec"]),
            ))
    return records
