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


def load_live(db_to_tenant: Dict[str, str], connection_strings: Dict[str, str]) -> List[SqlMiRecord]:
    """
    connection_strings: {db_name: odbc_connection_string}
    Queries sys.dm_exec_query_stats grouped by hour for today (UTC).
    All live imports are inside this function.
    """
    try:
        import pyodbc
    except ImportError:
        raise ImportError("Install live deps: pip install -r requirements-live.txt")

    QUERY = """
        SELECT
            DATEPART(HOUR, qs.last_execution_time) AS hour,
            SUM(qs.total_worker_time) / 1000000.0 AS TotalCPUSec
        FROM sys.dm_exec_query_stats qs
        WHERE CAST(qs.last_execution_time AS DATE) = CAST(GETDATE() AS DATE)
        GROUP BY DATEPART(HOUR, qs.last_execution_time)
    """
    records = []
    for db_name, tenant_id in db_to_tenant.items():
        conn_str = connection_strings.get(db_name)
        if not conn_str:
            continue
        import time as _time
        for attempt in range(3):
            try:
                with pyodbc.connect(conn_str, timeout=30) as conn:
                    cursor = conn.cursor()
                    cursor.execute(QUERY)
                    for row in cursor.fetchall():
                        records.append(SqlMiRecord(
                            tenant_id=tenant_id,
                            hour=int(row.hour),
                            total_cpu_sec=float(row.TotalCPUSec or 0.0),
                        ))
                break
            except Exception as e:
                if attempt < 2:
                    print(f"WARNING: SQL query attempt {attempt+1} failed for {db_name}, retrying in 20s: {e}", file=__import__('sys').stderr)
                    _time.sleep(20)
                else:
                    print(f"WARNING: SQL query failed for {db_name} after 3 attempts: {e}", file=__import__('sys').stderr)
    return records
