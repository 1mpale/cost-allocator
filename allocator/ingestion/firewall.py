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
