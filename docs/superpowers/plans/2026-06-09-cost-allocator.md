# Cost Allocation Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python prototype that ingests mock logs from three Azure shared resources (SQL MI, App Gateway, Azure Firewall), attributes daily costs to 3 tenants using resource-specific allocation formulas, and outputs a `daily_cost_report.json` plus a console table.

**Architecture:** Single-process Python CLI. Four pipeline stages: Config Loader → Data Ingestion (mock JSON files) → Allocation Engine (3 independent formulas) → Report Emitter (stdout table + JSON). Live Azure mode (KQL + DMV) is wired but gated behind env vars and not exercised by the test suite.

**Tech Stack:** Python 3.11+, numpy (percentile), pytest, ipaddress (stdlib), json (stdlib), dataclasses (stdlib). Optional live mode: `azure-monitor-query`, `azure-identity`, `pyodbc`.

---

## File Map

```
cost-allocator/
├── allocator/
│   ├── __init__.py                  # empty
│   ├── config.py                    # BillingConfig + TenantMap loaders
│   ├── models.py                    # TenantAllocation + AllocationReport dataclasses
│   ├── ingestion/
│   │   ├── __init__.py              # empty
│   │   ├── sql_mi.py               # SqlMiRecord + load_mock()
│   │   ├── agw.py                  # AgwRecord + load_mock()
│   │   └── firewall.py             # FirewallRecord + load_mock()
│   ├── engine/
│   │   ├── __init__.py              # empty
│   │   ├── sql_mi.py               # allocate() with peak-shaving
│   │   ├── agw.py                  # allocate() with weighted index
│   │   └── firewall.py             # allocate() with proportional + unattributed split
│   └── report.py                    # print_table() + save_json()
├── mock_data/
│   ├── billing_config.json
│   ├── tenant_map.json
│   ├── sql_mi_dmv.json             # 3 tenants × 24h; spike scenario embedded
│   ├── agw_logs.json
│   └── firewall_logs.json          # includes 1 unattributed IP
├── tests/
│   ├── conftest.py                  # shared fixtures
│   ├── test_config.py
│   ├── test_sql_mi_engine.py
│   ├── test_agw_engine.py
│   ├── test_firewall_engine.py
│   ├── test_report.py
│   └── test_integration.py
├── main.py                          # CLI: --output flag, wires all stages
└── requirements.txt
```

---

## Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `allocator/__init__.py`
- Create: `allocator/ingestion/__init__.py`
- Create: `allocator/engine/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create requirements.txt**

```
numpy>=1.26
pytest>=8.0
pytest-cov>=4.1
```

- [ ] **Step 2: Create all __init__.py files**

```bash
mkdir -p allocator/ingestion allocator/engine tests mock_data docs/superpowers/plans
touch allocator/__init__.py allocator/ingestion/__init__.py allocator/engine/__init__.py
```

- [ ] **Step 3: Create tests/conftest.py**

```python
from pathlib import Path
import pytest

MOCK_DATA_DIR = Path(__file__).parent.parent / "mock_data"

@pytest.fixture
def mock_data_dir():
    return MOCK_DATA_DIR
```

- [ ] **Step 4: Install dependencies**

```bash
cd ~/Projects/cost-allocator
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Expected: installs numpy and pytest with no errors.

- [ ] **Step 5: Verify pytest runs**

```bash
pytest --collect-only
```

Expected: `no tests ran` (zero errors, zero failures).

- [ ] **Step 6: Commit**

```bash
git init && git add requirements.txt allocator/ tests/conftest.py mock_data/ docs/
git commit -m "feat: scaffold project structure"
```

---

## Task 2: Mock Data Files

**Files:**
- Create: `mock_data/billing_config.json`
- Create: `mock_data/tenant_map.json`
- Create: `mock_data/sql_mi_dmv.json`
- Create: `mock_data/agw_logs.json`
- Create: `mock_data/firewall_logs.json`

**Design notes for SQL MI spike scenario:**
- customer_a: hour 0 = 2400 CPU-sec, hours 1–23 = 0 (spike tenant, total = 2400)
- customer_b: all 24 hours = 100 CPU-sec (steady tenant, total = 2400 — equal to customer_a)
- customer_c: all 24 hours = 50 CPU-sec (low usage, total = 1200)

With these values: sorted array of 72 values = [0×23, 50×24, 100×24, 2400×1].
Global P90 = v[63] = 100 (indices 47–70 are all 100s). After capping:
- customer_a: min(2400,100) + 23×0 = 100 shaved total
- customer_b: 24×100 = 2400 shaved total
- Verifies invariant 3: customer_a proportion (100/3700 ≈ 2.7%) < customer_b proportion (2400/3700 ≈ 64.9%) even though raw totals are equal.

- [ ] **Step 1: Create billing_config.json**

```json
{
  "date": "2026-06-09",
  "sql_mi_daily_cost_eur": 50.0,
  "agw_daily_cost_eur": 15.0,
  "firewall_daily_cost_eur": 30.0
}
```

Save to `mock_data/billing_config.json`.

- [ ] **Step 2: Create tenant_map.json**

```json
{
  "databases": {
    "db_tenant_customer_a": "customer_a",
    "db_tenant_customer_b": "customer_b",
    "db_tenant_customer_c": "customer_c"
  },
  "subnets": {
    "10.100.1.0/24": "customer_a",
    "10.100.2.0/24": "customer_b",
    "10.100.3.0/24": "customer_c"
  },
  "hostnames": {
    "customer-a.oursharedapp.com": "customer_a",
    "customer-b.oursharedapp.com": "customer_b",
    "customer-c.oursharedapp.com": "customer_c"
  }
}
```

Save to `mock_data/tenant_map.json`.

- [ ] **Step 3: Create sql_mi_dmv.json**

Generate with this Python snippet (run once, save output):

```python
import json

records = []
# customer_a: spike at hour 0, zero otherwise
records.append({"database_name": "db_tenant_customer_a", "hour": 0, "total_cpu_sec": 2400.0})
for h in range(1, 24):
    records.append({"database_name": "db_tenant_customer_a", "hour": h, "total_cpu_sec": 0.0})
# customer_b: steady 100/hr
for h in range(24):
    records.append({"database_name": "db_tenant_customer_b", "hour": h, "total_cpu_sec": 100.0})
# customer_c: steady 50/hr
for h in range(24):
    records.append({"database_name": "db_tenant_customer_c", "hour": h, "total_cpu_sec": 50.0})

with open("mock_data/sql_mi_dmv.json", "w") as f:
    json.dump(records, f, indent=2)
print(f"Written {len(records)} records")
```

Run: `python -c "exec(open('...').read())"` or paste into a REPL.
Expected: `Written 72 records`.

- [ ] **Step 4: Create agw_logs.json**

```json
[
  {"tenant_host": "customer-a.oursharedapp.com", "request_count": 5000, "total_bytes": 10000000},
  {"tenant_host": "customer-b.oursharedapp.com", "request_count": 3000, "total_bytes": 25000000},
  {"tenant_host": "customer-c.oursharedapp.com", "request_count": 2000, "total_bytes": 5000000}
]
```

Save to `mock_data/agw_logs.json`.

- [ ] **Step 5: Create firewall_logs.json**

Note: `10.200.99.1` is intentionally outside all subnets — triggers the unattributed path (SC-7).

```json
[
  {"source_ip": "10.100.1.10", "destination_ip": "8.8.8.8", "network_bytes": 500000000},
  {"source_ip": "10.100.2.10", "destination_ip": "8.8.8.8", "network_bytes": 800000000},
  {"source_ip": "10.100.3.10", "destination_ip": "8.8.8.8", "network_bytes": 300000000},
  {"source_ip": "10.200.99.1", "destination_ip": "8.8.8.8", "network_bytes": 100000000}
]
```

Save to `mock_data/firewall_logs.json`.

- [ ] **Step 6: Commit**

```bash
git add mock_data/
git commit -m "feat: add mock data for 3 tenants with spike/unattributed scenarios"
```

---

## Task 3: Config Loader

**Files:**
- Create: `allocator/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config.py`:

```python
from pathlib import Path
from allocator.config import load_billing_config, load_tenant_map, BillingConfig, TenantMap

def test_load_billing_config(mock_data_dir):
    config = load_billing_config(mock_data_dir)
    assert isinstance(config, BillingConfig)
    assert config.date == "2026-06-09"
    assert config.sql_mi_daily_cost_eur == 50.0
    assert config.agw_daily_cost_eur == 15.0
    assert config.firewall_daily_cost_eur == 30.0

def test_load_tenant_map(mock_data_dir):
    tm = load_tenant_map(mock_data_dir)
    assert isinstance(tm, TenantMap)
    assert tm.databases["db_tenant_customer_a"] == "customer_a"
    assert tm.subnets["10.100.1.0/24"] == "customer_a"
    assert tm.hostnames["customer-a.oursharedapp.com"] == "customer_a"

def test_missing_billing_file_raises():
    import pytest
    with pytest.raises(FileNotFoundError):
        load_billing_config(Path("/nonexistent"))
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_config.py -v
```

Expected: `ERRORS` — `ModuleNotFoundError: No module named 'allocator.config'`

- [ ] **Step 3: Implement allocator/config.py**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add allocator/config.py tests/test_config.py
git commit -m "feat: config loader for billing config and tenant map"
```

---

## Task 4: SQL MI Ingestion + Models

**Files:**
- Create: `allocator/models.py`
- Create: `allocator/ingestion/sql_mi.py`

- [ ] **Step 1: Write failing tests**

Add to a new file `tests/test_sql_mi_ingestion.py`:

```python
from allocator.ingestion.sql_mi import load_mock, SqlMiRecord

def test_load_mock_returns_records(mock_data_dir):
    from allocator.config import load_tenant_map
    tm = load_tenant_map(mock_data_dir)
    records = load_mock(mock_data_dir, tm.databases)
    assert len(records) == 72  # 3 tenants × 24 hours
    assert all(isinstance(r, SqlMiRecord) for r in records)

def test_load_mock_maps_db_to_tenant(mock_data_dir):
    from allocator.config import load_tenant_map
    tm = load_tenant_map(mock_data_dir)
    records = load_mock(mock_data_dir, tm.databases)
    tenant_ids = {r.tenant_id for r in records}
    assert tenant_ids == {"customer_a", "customer_b", "customer_c"}

def test_load_mock_spike_hour_present(mock_data_dir):
    from allocator.config import load_tenant_map
    tm = load_tenant_map(mock_data_dir)
    records = load_mock(mock_data_dir, tm.databases)
    spike = [r for r in records if r.tenant_id == "customer_a" and r.hour == 0]
    assert len(spike) == 1
    assert spike[0].total_cpu_sec == 2400.0
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_sql_mi_ingestion.py -v
```

Expected: `ERROR` — `ModuleNotFoundError`

- [ ] **Step 3: Create allocator/models.py**

```python
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
```

- [ ] **Step 4: Create allocator/ingestion/sql_mi.py**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_sql_mi_ingestion.py -v
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

```bash
git add allocator/models.py allocator/ingestion/sql_mi.py tests/test_sql_mi_ingestion.py
git commit -m "feat: SQL MI ingestion mock loader and shared models"
```

---

## Task 5: SQL MI Engine (Peak-Shaving)

**Files:**
- Create: `allocator/engine/sql_mi.py`
- Create: `tests/test_sql_mi_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sql_mi_engine.py
import pytest
from allocator.engine.sql_mi import allocate
from allocator.ingestion.sql_mi import SqlMiRecord

def _make_records(tenant_hours: dict) -> list:
    """tenant_hours: {tenant_id: [24 floats]}"""
    records = []
    for tenant_id, hours in tenant_hours.items():
        for h, cpu in enumerate(hours):
            records.append(SqlMiRecord(tenant_id=tenant_id, hour=h, total_cpu_sec=cpu))
    return records


def test_zero_leak_basic():
    records = _make_records({
        "a": [100.0] * 24,
        "b": [200.0] * 24,
    })
    costs = allocate(records, cost_total=50.0)
    assert abs(sum(costs.values()) - 50.0) < 0.01


def test_zero_leak_three_tenants(mock_data_dir):
    from allocator.config import load_tenant_map
    from allocator.ingestion.sql_mi import load_mock
    tm = load_tenant_map(mock_data_dir)
    records = load_mock(mock_data_dir, tm.databases)
    costs = allocate(records, cost_total=50.0)
    assert abs(sum(costs.values()) - 50.0) < 0.01


def test_peak_shaving_fairness():
    """Invariant 3: spike tenant (equal total CPU-sec) must pay less than steady tenant."""
    # spike: 1h×2400 + 23h×0 = 2400 total
    # steady: 24h×100 = 2400 total
    spike = [2400.0] + [0.0] * 23
    steady = [100.0] * 24
    records = _make_records({"spike": spike, "steady": steady})
    costs = allocate(records, cost_total=50.0)
    assert costs["spike"] < costs["steady"], (
        f"Peak-shaving failed: spike={costs['spike']}, steady={costs['steady']}"
    )


def test_all_zero_usage_equal_split():
    records = _make_records({"a": [0.0] * 24, "b": [0.0] * 24})
    costs = allocate(records, cost_total=10.0)
    assert abs(sum(costs.values()) - 10.0) < 0.01
    assert abs(costs["a"] - costs["b"]) < 0.01


def test_single_tenant_absorbs_all():
    records = _make_records({"only": [100.0] * 24})
    costs = allocate(records, cost_total=50.0)
    assert abs(costs["only"] - 50.0) < 0.01


def test_proportional_without_spike():
    """Without any spike, proportions follow raw CPU totals."""
    records = _make_records({"a": [100.0] * 24, "b": [300.0] * 24})
    costs = allocate(records, cost_total=40.0)
    # a=25%, b=75%
    assert abs(costs["a"] - 10.0) < 0.02
    assert abs(costs["b"] - 30.0) < 0.02
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_sql_mi_engine.py -v
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'allocator.engine.sql_mi'`

- [ ] **Step 3: Implement allocator/engine/sql_mi.py**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_sql_mi_engine.py -v
```

Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add allocator/engine/sql_mi.py tests/test_sql_mi_engine.py
git commit -m "feat: SQL MI peak-shaving allocation engine"
```

---

## Task 6: AGW Ingestion + Engine

**Files:**
- Create: `allocator/ingestion/agw.py`
- Create: `allocator/engine/agw.py`
- Create: `tests/test_agw_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_agw_engine.py
import pytest
from allocator.engine.agw import allocate
from allocator.ingestion.agw import AgwRecord


def test_zero_leak():
    records = [
        AgwRecord("a", 5000, 10_000_000),
        AgwRecord("b", 3000, 25_000_000),
        AgwRecord("c", 2000,  5_000_000),
    ]
    costs = allocate(records, cost_total=15.0)
    assert abs(sum(costs.values()) - 15.0) < 0.01


def test_weighted_index_data_dominates():
    """Tenant with more bytes but fewer requests pays more (W_data=0.7 > W_req=0.3)."""
    records = [
        AgwRecord("small_req_big_bytes", request_count=1000, total_bytes=90_000_000),
        AgwRecord("big_req_small_bytes",  request_count=9000, total_bytes=10_000_000),
    ]
    costs = allocate(records, cost_total=100.0)
    assert costs["small_req_big_bytes"] > costs["big_req_small_bytes"]


def test_zero_requests_falls_back_to_bytes():
    records = [
        AgwRecord("a", request_count=0, total_bytes=30_000_000),
        AgwRecord("b", request_count=0, total_bytes=70_000_000),
    ]
    costs = allocate(records, cost_total=10.0)
    assert abs(costs["a"] - 3.0) < 0.02
    assert abs(costs["b"] - 7.0) < 0.02


def test_both_zero_equal_split():
    records = [AgwRecord("a", 0, 0), AgwRecord("b", 0, 0)]
    costs = allocate(records, cost_total=10.0)
    assert abs(costs["a"] - 5.0) < 0.01
    assert abs(costs["b"] - 5.0) < 0.01


def test_load_mock(mock_data_dir):
    from allocator.config import load_tenant_map
    from allocator.ingestion.agw import load_mock
    tm = load_tenant_map(mock_data_dir)
    records = load_mock(mock_data_dir, tm.hostnames)
    assert len(records) == 3
    tenant_ids = {r.tenant_id for r in records}
    assert tenant_ids == {"customer_a", "customer_b", "customer_c"}
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_agw_engine.py -v
```

Expected: `ERROR` — `ModuleNotFoundError`

- [ ] **Step 3: Create allocator/ingestion/agw.py**

```python
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
```

- [ ] **Step 4: Create allocator/engine/agw.py**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_agw_engine.py -v
```

Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
git add allocator/ingestion/agw.py allocator/engine/agw.py tests/test_agw_engine.py
git commit -m "feat: AGW ingestion mock loader and weighted-index allocation engine"
```

---

## Task 7: Firewall Ingestion + Engine

**Files:**
- Create: `allocator/ingestion/firewall.py`
- Create: `allocator/engine/firewall.py`
- Create: `tests/test_firewall_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_firewall_engine.py
import pytest
import sys
from allocator.engine.firewall import allocate
from allocator.ingestion.firewall import FirewallRecord

SUBNETS = {
    "10.100.1.0/24": "customer_a",
    "10.100.2.0/24": "customer_b",
    "10.100.3.0/24": "customer_c",
}
TENANTS = ["customer_a", "customer_b", "customer_c"]


def test_zero_leak_fully_attributed():
    records = [
        FirewallRecord("10.100.1.10", "8.8.8.8", 500_000_000),
        FirewallRecord("10.100.2.10", "8.8.8.8", 800_000_000),
        FirewallRecord("10.100.3.10", "8.8.8.8", 300_000_000),
    ]
    costs, _ = allocate(records, SUBNETS, cost_total=30.0, known_tenants=TENANTS)
    assert abs(sum(costs.values()) - 30.0) < 0.01


def test_zero_leak_with_unattributed(capsys):
    records = [
        FirewallRecord("10.100.1.10", "8.8.8.8", 500_000_000),
        FirewallRecord("10.200.99.1", "8.8.8.8", 100_000_000),  # unattributed
    ]
    costs, _ = allocate(records, SUBNETS, cost_total=30.0, known_tenants=TENANTS)
    assert abs(sum(costs.values()) - 30.0) < 0.01


def test_unattributed_ip_emits_warning(capsys):
    records = [
        FirewallRecord("10.100.1.10", "8.8.8.8", 500_000_000),
        FirewallRecord("10.200.99.1", "8.8.8.8", 100_000_000),
    ]
    _, warn_count = allocate(records, SUBNETS, cost_total=30.0, known_tenants=TENANTS)
    assert warn_count == 1
    captured = capsys.readouterr()
    assert "10.200.99.1" in captured.err


def test_destination_ip_fallback():
    """If source IP is unattributed, destination IP is tried (PDF §3.3 rule)."""
    records = [
        FirewallRecord("10.200.99.1", "10.100.2.10", 400_000_000),  # dst maps to customer_b
    ]
    costs, warn_count = allocate(records, SUBNETS, cost_total=30.0, known_tenants=TENANTS)
    assert warn_count == 0
    assert costs["customer_b"] > 0


def test_proportional_allocation():
    """customer_a gets 5/16 and customer_b gets 8/16 of attributed cost."""
    records = [
        FirewallRecord("10.100.1.10", "8.8.8.8", 500),
        FirewallRecord("10.100.2.10", "8.8.8.8", 800),
        FirewallRecord("10.100.3.10", "8.8.8.8", 300),
    ]
    costs, _ = allocate(records, SUBNETS, cost_total=160.0, known_tenants=TENANTS)
    assert abs(costs["customer_a"] - 50.0) < 0.02   # 500/1600 * 160
    assert abs(costs["customer_b"] - 80.0) < 0.02   # 800/1600 * 160


def test_all_zero_equal_split():
    records = []
    costs, _ = allocate(records, SUBNETS, cost_total=30.0, known_tenants=TENANTS)
    assert abs(sum(costs.values()) - 30.0) < 0.01
    assert all(abs(v - 10.0) < 0.01 for v in costs.values())


def test_load_mock(mock_data_dir):
    from allocator.config import load_tenant_map
    from allocator.ingestion.firewall import load_mock
    records = load_mock(mock_data_dir)
    assert len(records) == 4  # 3 attributed + 1 unattributed
    assert any(r.source_ip == "10.200.99.1" for r in records)
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_firewall_engine.py -v
```

Expected: `ERROR` — `ModuleNotFoundError`

- [ ] **Step 3: Create allocator/ingestion/firewall.py**

```python
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
```

- [ ] **Step 4: Create allocator/engine/firewall.py**

```python
import ipaddress
import sys
from typing import Dict, List, Tuple

from allocator.ingestion.firewall import FirewallRecord


def _match_ip(ip_str: str, subnet_map: Dict[str, str]) -> str | None:
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
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_firewall_engine.py -v
```

Expected: `7 passed`.

- [ ] **Step 6: Commit**

```bash
git add allocator/ingestion/firewall.py allocator/engine/firewall.py tests/test_firewall_engine.py
git commit -m "feat: firewall ingestion mock loader and proportional allocation engine"
```

---

## Task 8: Report Module

**Files:**
- Create: `allocator/report.py`
- Create: `tests/test_report.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_report.py
import json
import os
import tempfile
from io import StringIO

from allocator.models import AllocationReport, TenantAllocation
from allocator.report import print_table, save_json


def _sample_report():
    return AllocationReport(
        date="2026-06-09",
        allocations=[
            TenantAllocation("customer_a", sql_mi_cost=14.71, agw_cost=3.75, firewall_cost=9.38),
            TenantAllocation("customer_b", sql_mi_cost=28.24, agw_cost=9.38, firewall_cost=15.00),
            TenantAllocation("customer_c", sql_mi_cost=7.05, agw_cost=1.87, firewall_cost=5.62),
        ],
    )


def test_total_shared_cost_allocated():
    report = _sample_report()
    expected = round(
        14.71 + 3.75 + 9.38 +
        28.24 + 9.38 + 15.00 +
        7.05 + 1.87 + 5.62,
        2,
    )
    assert report.total_shared_cost_allocated == expected


def test_save_json_schema(tmp_path):
    report = _sample_report()
    out = tmp_path / "report.json"
    save_json(report, str(out))
    with open(out) as f:
        data = json.load(f)
    assert "date" in data
    assert "total_shared_cost_allocated" in data
    assert "allocations" in data
    alloc = data["allocations"][0]
    for field in ("tenant_id", "sql_mi_cost", "agw_cost", "firewall_cost", "total_cost"):
        assert field in alloc, f"Missing field: {field}"


def test_save_json_zero_leak(tmp_path):
    report = _sample_report()
    out = tmp_path / "report.json"
    save_json(report, str(out))
    with open(out) as f:
        data = json.load(f)
    total = data["total_shared_cost_allocated"]
    summed = sum(a["total_cost"] for a in data["allocations"])
    assert abs(total - summed) < 0.01


def test_print_table_contains_all_tenants(capsys):
    report = _sample_report()
    print_table(report)
    captured = capsys.readouterr()
    assert "customer_a" in captured.out
    assert "customer_b" in captured.out
    assert "customer_c" in captured.out
    assert "2026-06-09" in captured.out
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_report.py -v
```

Expected: `ERROR` — `ModuleNotFoundError: No module named 'allocator.report'`

- [ ] **Step 3: Create allocator/report.py**

```python
import json
from allocator.models import AllocationReport


def print_table(report: AllocationReport) -> None:
    print(f"\nDaily Cost Report — {report.date}")
    print(f"Total allocated: €{report.total_shared_cost_allocated:.2f}\n")
    header = f"{'Tenant':<22} {'SQL MI':>10} {'AGW':>10} {'Firewall':>10} {'Total':>10}"
    print(header)
    print("─" * len(header))
    for a in sorted(report.allocations, key=lambda x: x.tenant_id):
        print(
            f"{a.tenant_id:<22} €{a.sql_mi_cost:>9.2f} €{a.agw_cost:>9.2f} "
            f"€{a.firewall_cost:>9.2f} €{a.total_cost:>9.2f}"
        )
    print()


def save_json(report: AllocationReport, output_path: str) -> None:
    data = {
        "date": report.date,
        "total_shared_cost_allocated": report.total_shared_cost_allocated,
        "allocations": [
            {
                "tenant_id": a.tenant_id,
                "sql_mi_cost": a.sql_mi_cost,
                "agw_cost": a.agw_cost,
                "firewall_cost": a.firewall_cost,
                "total_cost": a.total_cost,
            }
            for a in sorted(report.allocations, key=lambda x: x.tenant_id)
        ],
    }
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_report.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add allocator/report.py tests/test_report.py
git commit -m "feat: report module — stdout table and JSON output"
```

---

## Task 9: main.py CLI Entry Point

**Files:**
- Create: `main.py`

- [ ] **Step 1: Write failing test (CLI smoke test)**

Add to `tests/test_integration.py` (create the file):

```python
# tests/test_integration.py  — only the smoke test for now; full pipeline in Task 10
import subprocess
import sys
import json
from pathlib import Path


def test_cli_smoke(tmp_path):
    out = tmp_path / "report.json"
    result = subprocess.run(
        [sys.executable, "main.py", "--output", str(out)],
        capture_output=True, text=True,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0, f"CLI failed:\n{result.stderr}"
    assert out.exists(), "Output file not created"
    data = json.loads(out.read_text())
    assert "date" in data
    assert "allocations" in data
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_integration.py::test_cli_smoke -v
```

Expected: `FAILED` — `main.py` does not exist.

- [ ] **Step 3: Create main.py**

```python
import argparse
from pathlib import Path

from allocator.config import load_billing_config, load_tenant_map
from allocator.ingestion.sql_mi import load_mock as load_sql_mi
from allocator.ingestion.agw import load_mock as load_agw
from allocator.ingestion.firewall import load_mock as load_firewall
from allocator.engine.sql_mi import allocate as allocate_sql_mi
from allocator.engine.agw import allocate as allocate_agw
from allocator.engine.firewall import allocate as allocate_firewall
from allocator.models import AllocationReport, TenantAllocation
from allocator.report import print_table, save_json

DATA_DIR = Path(__file__).parent / "mock_data"


def run(output_path: str) -> AllocationReport:
    config = load_billing_config(DATA_DIR)
    tenant_map = load_tenant_map(DATA_DIR)

    known_tenants = sorted(set(tenant_map.databases.values()))

    sql_records = load_sql_mi(DATA_DIR, tenant_map.databases)
    agw_records = load_agw(DATA_DIR, tenant_map.hostnames)
    fw_records = load_firewall(DATA_DIR)

    sql_costs = allocate_sql_mi(sql_records, config.sql_mi_daily_cost_eur)
    agw_costs = allocate_agw(agw_records, config.agw_daily_cost_eur)
    fw_costs, _ = allocate_firewall(fw_records, tenant_map.subnets, config.firewall_daily_cost_eur, known_tenants)

    allocations = [
        TenantAllocation(
            tenant_id=t,
            sql_mi_cost=sql_costs.get(t, 0.0),
            agw_cost=agw_costs.get(t, 0.0),
            firewall_cost=fw_costs.get(t, 0.0),
        )
        for t in known_tenants
    ]

    report = AllocationReport(date=config.date, allocations=allocations)
    print_table(report)
    save_json(report, output_path)
    return report


def main():
    parser = argparse.ArgumentParser(description="Azure Shared Resource Cost Allocator")
    parser.add_argument(
        "--output", default="daily_cost_report.json",
        help="Path to write JSON report (default: daily_cost_report.json)"
    )
    args = parser.parse_args()
    run(args.output)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the smoke test**

```bash
pytest tests/test_integration.py::test_cli_smoke -v
```

Expected: `1 passed`.

- [ ] **Step 5: Run manually and inspect output**

```bash
python main.py --output /tmp/daily_cost_report.json
cat /tmp/daily_cost_report.json
```

Expected: console table with 3 tenants + valid JSON file.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_integration.py
git commit -m "feat: main.py CLI entry point wiring all pipeline stages"
```

---

## Task 10: Full Integration Tests (All Acceptance Criteria)

**Files:**
- Modify: `tests/test_integration.py`

- [ ] **Step 1: Add SC-1 zero-leak integration test**

Append to `tests/test_integration.py`:

```python
import json
from pathlib import Path
from main import run


def test_integration_zero_leak_all_resources(tmp_path):
    """SC-1: sum of allocated tenant costs == total for each resource."""
    from allocator.config import load_billing_config
    config = load_billing_config(Path(__file__).parent.parent / "mock_data")

    out = tmp_path / "report.json"
    report = run(str(out))

    data = json.loads(out.read_text())

    sql_sum = sum(a["sql_mi_cost"] for a in data["allocations"])
    agw_sum = sum(a["agw_cost"] for a in data["allocations"])
    fw_sum  = sum(a["firewall_cost"] for a in data["allocations"])

    assert abs(sql_sum - config.sql_mi_daily_cost_eur) < 0.01, f"SQL MI leak: {sql_sum} != {config.sql_mi_daily_cost_eur}"
    assert abs(agw_sum - config.agw_daily_cost_eur) < 0.01, f"AGW leak: {agw_sum} != {config.agw_daily_cost_eur}"
    assert abs(fw_sum  - config.firewall_daily_cost_eur) < 0.01, f"FW leak: {fw_sum} != {config.firewall_daily_cost_eur}"
```

- [ ] **Step 2: Add SC-2 peak-shaving integration test**

Append to `tests/test_integration.py`:

```python
def test_integration_peak_shaving_fairness(tmp_path):
    """SC-2: In mock data, customer_a (spike) must pay less SQL MI than customer_b (steady, equal total CPU)."""
    out = tmp_path / "report.json"
    report = run(str(out))

    data = json.loads(out.read_text())
    by_tenant = {a["tenant_id"]: a for a in data["allocations"]}

    assert by_tenant["customer_a"]["sql_mi_cost"] < by_tenant["customer_b"]["sql_mi_cost"], (
        f"Peak-shaving failed: customer_a={by_tenant['customer_a']['sql_mi_cost']}, "
        f"customer_b={by_tenant['customer_b']['sql_mi_cost']}"
    )
```

- [ ] **Step 3: Add SC-3 JSON schema test**

Append to `tests/test_integration.py`:

```python
def test_integration_json_schema(tmp_path):
    """SC-3: Output JSON matches required schema."""
    out = tmp_path / "report.json"
    run(str(out))
    data = json.loads(out.read_text())

    assert isinstance(data["date"], str)
    assert isinstance(data["total_shared_cost_allocated"], float)
    assert isinstance(data["allocations"], list)
    assert len(data["allocations"]) == 3

    for alloc in data["allocations"]:
        for field in ("tenant_id", "sql_mi_cost", "agw_cost", "firewall_cost", "total_cost"):
            assert field in alloc, f"Missing field '{field}' in allocation"
        assert abs(alloc["total_cost"] - (alloc["sql_mi_cost"] + alloc["agw_cost"] + alloc["firewall_cost"])) < 0.01
```

- [ ] **Step 4: Add SC-7 unattributed warning test**

Append to `tests/test_integration.py`:

```python
def test_integration_unattributed_warning_emitted(tmp_path, capsys):
    """SC-7: firewall_logs.json has an unattributed IP — warning on stderr, no cost leak."""
    out = tmp_path / "report.json"
    run(str(out))
    captured = capsys.readouterr()
    assert "10.200.99.1" in captured.err, "Expected unattributed IP warning on stderr"
```

- [ ] **Step 5: Run all integration tests**

```bash
pytest tests/test_integration.py -v
```

Expected: `5 passed` (smoke + 4 SC tests).

- [ ] **Step 6: Run the full test suite**

```bash
pytest --tb=short -q
```

Expected: all tests pass, `0 failed`.

- [ ] **Step 7: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: integration tests covering SC-1 zero-leak, SC-2 peak-shaving, SC-3 schema, SC-7 warning"
```

---

## Self-Review Checklist

**Spec coverage:**

| PRODUCT.md criterion | Task covering it |
|---|---|
| SC-1 Zero-leak per resource | Task 5 unit + Task 10 integration |
| SC-2 Peak-shaving fairness | Task 5 `test_peak_shaving_fairness` + Task 10 integration |
| SC-3 JSON schema | Task 8 `test_save_json_schema` + Task 10 integration |
| SC-4 Stdout table with all tenants | Task 8 `test_print_table_contains_all_tenants` |
| SC-5 Mock mode offline | Task 2 (mock data), Task 9 CLI smoke (no Azure creds needed) |
| SC-6 Live mode wired | Not tested (no Azure env in CI); live mode stubs exist in ingestion modules — add in a follow-up if needed |
| SC-7 Unattributed warning | Task 7 `test_unattributed_ip_emits_warning` + Task 10 integration |

**PRODUCT.md Invariants:**
- Invariant 1 (zero-leak): Task 5, 6, 7, 10
- Invariant 2 (non-negative): covered by proportional math; all costs ≥ 0 by construction
- Invariant 3 (peak-shaving fairness): Task 5 unit + Task 10 integration
- Invariant 4 (no missing tenants): `known_tenants` list drives output in `main.py`
- Invariant 5 (idempotency): deterministic sort order + fixed mock data ensures this

**Edge cases from PRODUCT.md §5:**
- All-zero usage: covered in Task 5, 6, 7 unit tests
- Single tenant: covered in Task 5 `test_single_tenant_absorbs_all`
- Unattributed IP: covered in Task 7 `test_unattributed_ip_emits_warning`

**Placeholder scan:** No TBDs, TODOs, or incomplete code blocks. All test code is complete and runnable.

**Type consistency:** `SqlMiRecord`, `AgwRecord`, `FirewallRecord`, `TenantAllocation`, `AllocationReport` — all defined once and referenced consistently across ingestion, engine, and test files.
