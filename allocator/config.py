import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

DATA_DIR = Path(__file__).parent.parent / "mock_data"


@dataclass
class BillingConfig:
    date: str
    sql_mi_daily_cost_eur: float
    agw_daily_cost_eur: float
    firewall_daily_cost_eur: float


@dataclass
class TenantMap:
    databases: Dict[str, str]
    subnets: Dict[str, str]
    hostnames: Dict[str, str]


def load_billing_config(data_dir: Path = DATA_DIR) -> BillingConfig:
    path = data_dir / "billing_config.json"
    with open(path) as f:
        data = json.load(f)
    return BillingConfig(**data)


def load_tenant_map(data_dir: Path = DATA_DIR) -> TenantMap:
    path = data_dir / "tenant_map.json"
    with open(path) as f:
        data = json.load(f)
    return TenantMap(**data)
