# Tech Spec: Azure Shared Resource Cost Allocation Engine

References: PRODUCT.md §3 (Desired Behavior), §4 (Invariants), §6 (Success Criteria)

## 1. Architecture

### 1.1 Overview

Single-process Python CLI. Runs once per day (or on-demand). No persistent server, no
message queue. Structured as a pipeline of three independent stages:

```
[Config Loader] → [Data Ingestion] → [Allocation Engine] → [Report Emitter]
```

### 1.2 Module structure

```
cost-allocator/
├── allocator/
│   ├── __init__.py
│   ├── config.py          # loads billing config + tenant map from JSON/env
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── sql_mi.py      # SQL MI DMV extractor (mock + live)
│   │   ├── agw.py         # AGW KQL extractor (mock + live)
│   │   └── firewall.py    # AzFW KQL extractor (mock + live)
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── sql_mi.py      # Peak-shaving allocation formula
│   │   ├── agw.py         # Weighted index allocation formula
│   │   └── firewall.py    # Proportional allocation formula
│   └── report.py          # stdout table + JSON output
├── mock_data/
│   ├── tenant_map.json    # db/subnet/hostname → tenant_id mapping
│   ├── billing_config.json
│   ├── sql_mi_dmv.json    # 3 tenants × 24 hours CPU data
│   ├── agw_logs.json      # request + byte counts per tenant
│   └── firewall_logs.json # bytes per src/dst IP
├── tests/
│   ├── test_sql_mi.py
│   ├── test_agw.py
│   ├── test_firewall.py
│   ├── test_report.py
│   └── test_integration.py
├── main.py                # CLI entry point
└── requirements.txt
```

### 1.3 Mode switching

`config.py` reads `ALLOCATION_MODE` env var (`mock` | `live`, default `mock`).  
In `mock` mode: ingestion modules read from `mock_data/*.json`.  
In `live` mode: ingestion modules use `azure-monitor-query` (KQL) and `pyodbc` (SQL MI DMV).

## 2. Data Model

### 2.1 Tenant map (`mock_data/tenant_map.json`)

```json
{
  "databases": { "db_tenant_customer_a": "customer_a", "db_tenant_customer_b": "customer_b", "db_tenant_customer_c": "customer_c" },
  "subnets":   { "10.100.1.0/24": "customer_a", "10.100.2.0/24": "customer_b", "10.100.3.0/24": "customer_c" },
  "hostnames": { "customer-a.oursharedapp.com": "customer_a", "customer-b.oursharedapp.com": "customer_b", "customer-c.oursharedapp.com": "customer_c" }
}
```

### 2.2 Billing config (`mock_data/billing_config.json`)

```json
{
  "date": "2026-06-09",
  "sql_mi_daily_cost_eur": 50.0,
  "agw_daily_cost_eur": 15.0,
  "firewall_daily_cost_eur": 30.0
}
```

### 2.3 SQL MI DMV mock (`mock_data/sql_mi_dmv.json`)

List of `{ database_name, hour (0-23), total_cpu_sec }` records.  
3 tenants × 24 hours = 72 records minimum.  
Includes a deliberate spike scenario: customer_a has 1 hour at 5× normal, customer_b has
steady medium-high usage, validating SC-2.

### 2.4 AGW logs mock (`mock_data/agw_logs.json`)

List of `{ tenant_host, request_count, total_bytes }` records (one row per tenant).

### 2.5 Firewall logs mock (`mock_data/firewall_logs.json`)

List of `{ source_ip, destination_ip, network_bytes }` records.  
Includes one entry with an IP outside the subnet map to test the `unattributed` path (SC-7).

### 2.6 Internal allocation result (Python dataclasses)

```python
@dataclass
class TenantAllocation:
    tenant_id: str
    sql_mi_cost: float
    agw_cost: float
    firewall_cost: float

    @property
    def total_cost(self) -> float:
        return self.sql_mi_cost + self.agw_cost + self.firewall_cost

@dataclass
class AllocationReport:
    date: str                          # ISO-8601 from billing_config["date"]
    allocations: List[TenantAllocation]

    @property
    def total_shared_cost_allocated(self) -> float:
        return sum(a.total_cost for a in self.allocations)
```
`report.py` serialises `AllocationReport` directly to the §2.7 JSON schema.

### 2.7 Output JSON schema

```json
{
  "date": "YYYY-MM-DD",
  "total_shared_cost_allocated": 95.00,
  "allocations": [
    { "tenant_id": "customer_a", "sql_mi_cost": 22.40, "agw_cost": 5.10, "firewall_cost": 12.50, "total_cost": 40.00 }
  ]
}
```

## 3. Algorithm Specifications

### 3.1 SQL MI — Peak-shaving allocation

Implements PRODUCT.md §3.1.

```
Input:  List[(tenant_id, hour, cpu_sec)]  # 24 hours × N tenants
        cost_total: float
        p_shave_percentile: float = 90.0  # configurable, default 90th

Step 1: Compute p_shave = numpy.percentile([r.cpu_sec for r in input_records], p_shave_percentile)
        — a single scalar over the entire input dataset, all tenants all hours combined (zeros included)
Step 2: For each (tenant, hour): cpu_shaved = min(cpu_sec, p_shave)
Step 3: tenant_sum_i = Σ_h cpu_shaved_i,h
Step 4: total_sum = Σ_i tenant_sum_i
        If total_sum == 0: allocate cost_total / N equally (edge case from PRODUCT.md §5)
Step 5: proportion_i = tenant_sum_i / total_sum
Step 6: cost_i = proportion_i × cost_total
Step 7: Adjust last tenant to absorb floating-point residual → guarantees zero-leak (Invariant 1)
Output: Dict[tenant_id → cost_float]
```

### 3.2 AGW — Weighted index allocation

Implements PRODUCT.md §3.2. Weights: W_req=0.3, W_data=0.7 (hardcoded per spec).

```
Input:  List[(tenant_id, request_count, total_bytes)]
        cost_total: float

Step 1: total_requests = Σ request_count_i
        total_bytes = Σ total_bytes_i
        If either sum == 0: use 1.0 to avoid division by zero (uniform split)
Step 2: w_i = 0.3 × (request_count_i / total_requests) + 0.7 × (total_bytes_i / total_bytes)
Step 3: cost_i = w_i × cost_total
Step 4: Residual adjustment on last tenant (zero-leak)
Output: Dict[tenant_id → cost_float]
```

### 3.3 Firewall — Proportional allocation

Implements PRODUCT.md §3.3.

```
Input:  List[(source_ip, destination_ip, network_bytes)]
        tenant_subnet_map: Dict[cidr → tenant_id]
        cost_total: float
        known_tenants: List[str]  # used for uniform-split fallback and unattributed distribution

Step 1: For each row: attempt longest-prefix match on source_ip first, then destination_ip
        (per PDF §3.3 parsing rule: "allocate bytes to the tenant matching source or destination IP").
        Use the first match found. If neither IP matches any subnet: accumulate under
        "unattributed"; emit warning to stderr.
Step 2: sum_attributed = Σ tenant_bytes_i (excludes unattributed)
        sum_all = sum_attributed + bytes_unattributed
        If sum_all == 0: allocate cost_total / N equally across known_tenants; done.
Step 3: attributed_cost = cost_total × (sum_attributed / sum_all)
        unattributed_cost = cost_total × (bytes_unattributed / sum_all)
        — invariant: attributed_cost + unattributed_cost == cost_total exactly
Step 4: If sum_attributed == 0: proportion_i = 0 for all; full cost handled by unattributed path.
        Else: proportion_i = tenant_bytes_i / sum_attributed
Step 5: cost_i = proportion_i × attributed_cost + unattributed_cost / N
        — zero-leak holds: Σ cost_i = attributed_cost × Σ proportion_i + unattributed_cost
          = attributed_cost + unattributed_cost = cost_total
Step 6: Residual adjustment on last tenant (alphabetical) for floating-point gap
Output: Dict[tenant_id → cost_float], warns on unattributed bytes
```

### 3.4 Floating-point residual adjustment

To satisfy Invariant 1 exactly, after computing all proportional costs:
```python
residual = cost_total - sum(costs.values())
last_tenant = sorted(costs.keys())[-1]  # deterministic: alphabetically last
costs[last_tenant] += residual
```
Residual is expected to be < 0.001 €. If `abs(residual) > 0.01`, raise `AllocationError`.

## 4. Integration Points

### 4.1 Mock mode (offline)

No external dependencies. All ingestion modules accept an optional `data_path` parameter
pointing to `mock_data/`. Default: relative path from project root.

### 4.2 Live mode — Log Analytics (AGW + Firewall)

- SDK: `azure-monitor-query` (`LogsQueryClient`)
- Auth: `azure-identity` `DefaultAzureCredential` (reads `AZURE_TENANT_ID`,
  `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`)
- Workspace: `LOG_ANALYTICS_WORKSPACE_ID` env var
- Time range: previous calendar day (UTC)

**AGW KQL query** (target table: `AzureDiagnostics`, category: `ApplicationGatewayAccessLog`):
```kql
AzureDiagnostics
| where ResourceProvider == "MICROSOFT.NETWORK" and Category == "ApplicationGatewayAccessLog"
| extend TenantHost = host_s
| extend BytesSent = originalRequestBytes_d + responseBodyBytes_d
| summarize
    RequestCount = count(),
    TotalBytes = sum(BytesSent),
    FailedRequests = countif(httpStatus_d >= 400)
  by TenantHost, bin(TimeGenerated, 1d)
```
Parse `TenantHost` (e.g., `customer-a.oursharedapp.com`) against `tenant_map.hostnames` to resolve `tenant_id`.

**Firewall KQL query** (target table: `AZFWNetworkRule`; legacy fallback: `AzureDiagnostics` where `Category == "AzureFirewallNetworkRule"` for environments using older diagnostic settings):
```kql
AZFWNetworkRule
| extend SourceIP = SrcIP, DestinationIP = DstIP, BytesTransferred = OutboundBytes + InboundBytes
| summarize
    NetworkBytes = sum(BytesTransferred)
  by SourceIP, DestinationIP, Protocol, bin(TimeGenerated, 1d)
```
Resolve `SourceIP` → `tenant_id` via longest-prefix match against `tenant_map.subnets`.

### 4.3 Live mode — SQL MI DMVs

- Driver: `pyodbc` with ODBC Driver 18 for SQL Server
- Connection string from env var `SQL_MI_DSN`
- Executed once against the `master` database; all tenant databases returned in single result set

**DMV query**:
```sql
SELECT
    d.name AS DatabaseName,
    SUM(qs.total_worker_time) / 1000000.0 AS TotalCPUSec,
    SUM(qs.execution_count) AS ExecutionCount,
    SUM(qs.total_logical_reads) AS LogicalReads,
    SUM(qs.total_elapsed_time) / 1000000.0 AS TotalDurationSec
FROM sys.dm_exec_query_stats qs
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) qt
JOIN sys.databases d ON qt.dbid = d.database_id
WHERE d.name NOT IN ('master', 'model', 'msdb', 'tempdb')
GROUP BY d.name;
```
Map `DatabaseName` → `tenant_id` via `tenant_map.databases`. The mock data simulates this result set split into 24 hourly buckets using the `hour` field.

## 5. Tradeoffs

| Decision | Chosen | Alternative | Reason |
|---|---|---|---|
| Peak-shaving threshold | Global P90 | Per-tenant P90 or fixed cap (PDF §4.1 option b) | Global prevents gaming; no core-count dependency; fixed cap omitted as not needed for prototype |
| Residual adjustment | Last alphabetical tenant | Distribute evenly | Simplest deterministic approach; residual < 0.001 € |
| Float precision | Python `float` (64-bit) | `decimal.Decimal` | Sufficient at € scale; residual guard catches divergence |
| Subnet IP matching | Longest-prefix match | Exact match | Handles overlapping ranges; industry standard |
| Mode switching | Env var | CLI flag | Consistent with 12-factor; easier to test |
| Ingestion architecture | Single-process Python CLI (`main.py`) | Azure Functions + ADF (PDF §2) | PDF §2 describes production serverless architecture; prototype uses a CLI to maximise testability and eliminate infra dependencies. Functional behaviour is identical. |
| Firewall unattributed bytes | Split cost proportionally then add unattributed share equally | PDF §4.3 simple proportion (assumes 100% attribution) | PDF formula has no concept of unattributed bytes; it implicitly assumes perfect IP mapping. This extension preserves zero-leak when any IP cannot be resolved, which is realistic for any real environment. |
| CLI entry point | `main.py` (calls `allocator/` package) | Single `allocator.py` file (PDF §5.2 naming) | Package structure is more maintainable and testable; `main.py` fulfils the same runnable-script requirement from PDF §5.2. |

## 6. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| SQL MI DMV data spans midnight (stale stats) | Medium | Wrong daily attribution | Document: run engine at 01:00 UTC after daily stats reset |
| Tenant with zero usage in all resources | Low | ZeroDivision | Tested edge case in §5; uniform split |
| IP in multiple subnets (misconfigured map) | Low | Double-counted bytes | Longest-prefix match picks the most specific; log if ambiguous |
| Live KQL query timeout | Medium | Partial data | Raise `IngestionError`, do not emit partial report |

## 7. Validation Plan

| Step | Command | Pass Condition |
|---|---|---|
| Unit: SQL MI zero-leak | `pytest tests/test_sql_mi_engine.py::test_zero_leak_basic -v` | assert passes |
| Unit: peak-shaving fairness (SC-2) | `pytest tests/test_sql_mi_engine.py::test_peak_shaving_fairness -v` | spike tenant cost < steady tenant cost |
| Unit: AGW zero-leak | `pytest tests/test_agw_engine.py::test_zero_leak -v` | assert passes |
| Unit: FW unattributed warning | `pytest tests/test_firewall_engine.py::test_unattributed_ip_emits_warning -v` | warning on stderr, bytes not lost |
| Unit: FW zero-leak | `pytest tests/test_firewall_engine.py::test_zero_leak_fully_attributed -v` | assert passes |
| Integration: full pipeline mock | `pytest tests/test_integration.py -v` | JSON output matches schema, all SC- criteria green |
| Integration: stdout table | `pytest tests/test_report.py::test_print_table_contains_all_tenants -v` | output contains all 3 tenant IDs |
| CLI smoke test | `python main.py --output /tmp/daily_cost_report.json && python -c "import json; json.load(open('/tmp/daily_cost_report.json'))"` | exits 0, file exists, valid JSON |
