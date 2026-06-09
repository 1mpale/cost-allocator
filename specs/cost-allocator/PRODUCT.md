# Product Spec: Azure Shared Resource Cost Allocation Engine

## 1. Problem

In a multi-tenant Azure environment, each customer (tenant) has a dedicated Landing Zone
with private resources. To optimize infrastructure costs, three critical resources are shared
across all tenants:

- **Azure SQL Managed Instance (SQL MI)** — shared compute/storage
- **Azure Application Gateway (AGW) with WAF** — shared ingress controller
- **Azure Firewall (AzFW)** — shared egress, ingress, and inter-network traffic filtering

Because these resources are billed as a single Azure invoice line, there is no native
mechanism to determine how much each tenant owes per day. Without attribution:

- High-consuming tenants are subsidised by low-consuming tenants.
- FinOps reporting is blind to per-customer profitability.
- A single tenant with a temporary CPU spike can unfairly dominate SQL MI cost allocation.

## 2. Users

| User | Goal |
|---|---|
| FinOps / Finance team | Accurate per-customer daily cost breakdown to support billing/chargeback |
| Platform/Ops team | Validate that shared infra costs are fairly distributed; detect outlier tenants |
| Engineering lead | Audit the allocation logic and override daily cost inputs |

## 3. Desired Behavior

The Cost Allocation Engine runs once per day and produces a structured cost report showing
each tenant's share (in €) of each shared resource's daily cost.

### 3.1 SQL MI allocation (with Peak Shaving)

1. Ingest hourly CPU-seconds per tenant database (24 hourly data points per tenant).
2. Compute a global peak-shaving threshold `P_shave` over the flat list of all `CPU_i,h`
   values across all tenants `i` and all 24 hours `h` (zeros included). Formula: sort values
   ascending to array `v` of length `M`; compute virtual index `k = 0.9 × (M−1)`; then
   `P_shave = v[⌊k⌋] + (k − ⌊k⌋) × (v[⌊k⌋+1] − v[⌊k⌋])` (linear interpolation,
   equivalent to `numpy.percentile(arr, 90)` default).
3. Cap each tenant's per-hour CPU at `P_shave`: `CPU'_i,h = min(CPU_i,h, P_shave)`.
4. Compute each tenant's daily proportion: `Prop_SQL_i = Σ_h CPU'_i,h / Σ_j Σ_h CPU'_j,h`.
   If the denominator is zero (all CPU values are zero), split `Cost_SQL_Total` equally: each
   tenant receives `Cost_SQL_Total / N` (with residual cent to the alphabetically first tenant).
5. Allocate: `Cost_SQL_i = Prop_SQL_i × Cost_SQL_Total`.

### 3.2 Application Gateway allocation (weighted index)

1. Ingest per-tenant: request count `R_i` and total bytes transferred `D_i`.
2. Compute weighted allocation index: `W_i = (0.3 × R_i/ΣR_j) + (0.7 × D_i/ΣD_j)`.
   Zero-denominator rules (each term handled independently):
   - If `ΣR_j = 0`: `W_i = D_i/ΣD_j` (bytes-only).
   - If `ΣD_j = 0`: `W_i = R_i/ΣR_j` (requests-only).
   - If both `ΣR_j = 0` and `ΣD_j = 0`: `W_i = 1/N` (equal split).
3. Allocate: `Cost_AGW_i = W_i × Cost_AGW_Total`.

### 3.3 Azure Firewall allocation (direct proportional)

1. Ingest per-tenant network bytes (mapped from source/destination IP to tenant via subnet
   lookup table). Bytes whose source IP matches no subnet are accumulated under the special
   key `unattributed`; a warning is emitted to stderr.
2. Split total cost into attributed and unattributed portions:
   - `Σ_all = Σ_attributed + Bytes_unattributed`
   - `Attributed_Cost = Cost_FW_Total × (Σ_attributed / Σ_all)`
   - `Unattributed_Cost = Cost_FW_Total × (Bytes_unattributed / Σ_all)`
   - If `Σ_all == 0`: split `Cost_FW_Total` equally (`1/N` per tenant).
3. Compute tenant proportion against attributed bytes only:
   `Prop_FW_i = Bytes_i / Σ_attributed`
   If `Σ_attributed == 0` but `Σ_all > 0`: `Prop_FW_i = 0` for all (unattributed cost handles total).
4. Allocate: `Cost_FW_i = Prop_FW_i × Attributed_Cost + Unattributed_Cost / N`
   This preserves zero-leak: `Σ_i Cost_FW_i = Attributed_Cost × Σ Prop_FW_i + Unattributed_Cost = Attributed_Cost + Unattributed_Cost = Cost_FW_Total`.

### 3.4 Output

- Print a formatted table to stdout: tenant | SQL MI € | AGW € | Firewall € | Total €.
- Save `daily_cost_report.json` with the following schema:

```json
{
  "date": "YYYY-MM-DD",
  "total_shared_cost_allocated": 95.00,
  "allocations": [
    {
      "tenant_id": "customer_a",
      "sql_mi_cost": 22.40,
      "agw_cost": 5.10,
      "firewall_cost": 12.50,
      "total_cost": 40.00
    }
  ]
}
```

All monetary values are floats rounded to 2 decimal places. `date` is ISO-8601 (YYYY-MM-DD).
`total_shared_cost_allocated` is the sum of all tenant `total_cost` values.
Every tenant present in any input source appears in `allocations`, even if their costs are zero.

### 3.5 Azure connectivity

The engine supports two modes:

- **Mock mode** (default): reads from local JSON mock files simulating DMV results and KQL
  output. Fully offline, no Azure credentials required.
- **Live mode**: queries real Azure Log Analytics (KQL via `azure-monitor-query`) and SQL MI
  DMVs (via `pyodbc`). Activated by setting env vars `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`,
  `AZURE_CLIENT_SECRET`, `LOG_ANALYTICS_WORKSPACE_ID`, `SQL_MI_DSN`.

## 4. Invariants

1. **Zero-leak**: `Σ Cost_Tenant_i == Cost_Total` for every resource (float tolerance ≤ 0.01 €).
2. **Non-negative**: No tenant receives a negative cost allocation.
3. **Peak-shaving fairness**: Given two tenants with equal total daily CPU-seconds (e.g.,
   spike tenant: 1 hour at 2400s + 23 hours at 0s = 2400s total; steady tenant: 24 hours at
   100s = 2400s total), after peak-shaving the spike tenant's `Prop_SQL` must be less than
   the steady tenant's `Prop_SQL`.
4. **No missing tenants**: Every tenant present in any input source appears in the output
   report, even if their usage for a given resource is zero.
5. **Idempotency**: Running the engine twice on the same input files (mock mode) produces
   identical output. In live mode, output is deterministic for a given run but not guaranteed
   identical across runs if underlying Azure Log Analytics data changes (eventual consistency).

## 5. Edge Cases

| Scenario | Expected behavior |
|---|---|
| All tenants have zero usage for a resource | Costs split equally (1/N per tenant); residual cent allocated to alphabetically first tenant |
| Single tenant in the system | That tenant absorbs 100% of all resource costs |
| P_shave calculation with all identical CPU values | P90 = that value; no shaving occurs |
| Tenant present in SQL MI data but absent from AGW logs | AGW cost = €0 for that tenant |
| Tenant IP not found in subnet lookup table | Firewall bytes logged as `unattributed`, warning emitted, not lost from total |
| Daily cost config missing for a resource | Engine raises `ConfigurationError`, halts |

## 6. Success Criteria

| # | Criterion | Verification |
|---|---|---|
| SC-1 | Zero-leak: allocated sum == total cost for all 3 resources | `assert abs(sum(costs) - total) < 0.01` per resource |
| SC-2 | Peak-shaving fairness: spike tenant < steady tenant cost share for SQL MI | Dedicated test with spike vs steady mock data |
| SC-3 | Output JSON matches the required schema (date, total_shared_cost_allocated, allocations[]) | Schema validation against spec §3.4 |
| SC-4 | Stdout table renders all tenants with correct per-resource breakdown | Integration test captures stdout |
| SC-5 | Mock mode runs fully offline with no Azure SDK credentials configured | Run with no env vars set; no import errors or auth exceptions |
| SC-6 | Live mode wires up Log Analytics KQL and SQL MI DMV queries when credentials present | Smoke test with mocked Azure SDK responses |
| SC-7 | `unattributed` firewall bytes appear in report as a warning, not silently dropped | Test with an IP not in the subnet map |

## 7. Non-Goals

- Real-time or sub-daily cost reporting (daily batch only for prototype).
- Multi-currency support (EUR only).
- Billing system integration or invoice generation.
- Automated Azure cost ingestion from Cost Management API (costs are manually configured).
- Historical trend analysis or dashboards.
- Azure Functions / ADF deployment (the source spec §2 describes a production serverless
  architecture; this prototype uses a single-process Python CLI to maximise testability and
  eliminate infrastructure dependencies — functional behaviour is identical).
- Fixed hard-cap P_shave alternative (source spec §4.1 mentions a 3600s/hr/core cap option;
  this prototype implements global P90 only).
