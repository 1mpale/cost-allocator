"""
Traffic generator for cost-allocator live testing.

Env vars required:
  AGW_PUBLIC_IP       - Public IP of the Application Gateway
  SQL_SERVER_FQDN     - FQDN of the Azure SQL Server
  SQL_ADMIN_PASSWORD  - SQL admin password

Usage:
  python scripts/generate_traffic.py
"""

import os
import sys
import time
import concurrent.futures


def _http_request(agw_ip: str, host: str) -> None:
    """Send a single HTTP request to the AGW, ignoring errors."""
    try:
        import requests
        requests.get(f"http://{agw_ip}/", headers={"Host": host}, timeout=5)
    except Exception:
        pass


def _sql_cpu_query(conn_str: str) -> None:
    """Run a CPU-intensive SQL query, ignoring errors."""
    try:
        import pyodbc
        CPU_QUERY = """
SELECT COUNT(*) FROM (
  SELECT a.object_id * b.object_id AS val
  FROM sys.objects a CROSS JOIN sys.objects b
) t
"""
        with pyodbc.connect(conn_str, timeout=15) as conn:
            conn.cursor().execute(CPU_QUERY)
    except Exception:
        pass


def _build_conn_str(fqdn: str, db_name: str, password: str) -> str:
    return (
        f"Driver={{ODBC Driver 18 for SQL Server}};"
        f"Server=tcp:{fqdn},1433;Database={db_name};"
        f"Uid=sqladmin;Pwd={password};"
        f"Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )


def http_burst(agw_ip: str, host: str, count: int, workers: int = 50) -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_http_request, agw_ip, host) for _ in range(count)]
        concurrent.futures.wait(futures)


def sql_burst(conn_str: str, count: int, workers: int = 20) -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_sql_cpu_query, conn_str) for _ in range(count)]
        concurrent.futures.wait(futures)


def customer_a_spike(agw_ip: str, sql_fqdn: str, sql_password: str) -> None:
    """500 HTTP requests as fast as possible, then 500 SQL queries in a burst."""
    host = "customer-a.oursharedapp.com"
    db = "db-tenant-customer-a"
    conn_str = _build_conn_str(sql_fqdn, db, sql_password)

    print(f"[customer_a] Starting HTTP spike: 500 requests to {host}")
    http_burst(agw_ip, host, 500, workers=100)
    print("[customer_a] HTTP spike done. Starting SQL burst: 500 queries")
    sql_burst(conn_str, 500, workers=50)
    print("[customer_a] SQL burst done.")


def customer_b_steady(agw_ip: str, sql_fqdn: str, sql_password: str) -> None:
    """150 HTTP requests spread over 90s; 30 SQL queries per 30s interval x 3."""
    host = "customer-b.oursharedapp.com"
    db = "db-tenant-customer-b"
    conn_str = _build_conn_str(sql_fqdn, db, sql_password)

    # 150 HTTP requests over 90s: 50 per 30s interval x 3
    for interval in range(3):
        print(f"[customer_b] HTTP interval {interval + 1}/3: 50 requests")
        http_burst(agw_ip, host, 50, workers=25)
        print(f"[customer_b] SQL interval {interval + 1}/3: 30 queries")
        sql_burst(conn_str, 30, workers=10)
        if interval < 2:
            time.sleep(30)
    print("[customer_b] Steady traffic done.")


def customer_c_low(agw_ip: str, sql_fqdn: str, sql_password: str) -> None:
    """40 HTTP requests, 10 SQL queries."""
    host = "customer-c.oursharedapp.com"
    db = "db-tenant-customer-c"
    conn_str = _build_conn_str(sql_fqdn, db, sql_password)

    print(f"[customer_c] Sending 40 HTTP requests to {host}")
    http_burst(agw_ip, host, 40, workers=10)
    print("[customer_c] Sending 10 SQL queries")
    sql_burst(conn_str, 10, workers=5)
    print("[customer_c] Low traffic done.")


def main() -> None:
    agw_ip = os.environ.get("AGW_PUBLIC_IP")
    sql_fqdn = os.environ.get("SQL_SERVER_FQDN")
    sql_password = os.environ.get("SQL_ADMIN_PASSWORD")

    missing = [k for k, v in {"AGW_PUBLIC_IP": agw_ip, "SQL_SERVER_FQDN": sql_fqdn, "SQL_ADMIN_PASSWORD": sql_password}.items() if v is None]
    if missing:
        print(f"ERROR: Missing env vars: {missing}", file=sys.stderr)
        sys.exit(1)

    # Narrow types after validation
    assert agw_ip is not None
    assert sql_fqdn is not None
    assert sql_password is not None

    print("=== Traffic Generator ===")
    print(f"AGW: {agw_ip}  SQL: {sql_fqdn}")
    print()

    # Run all three tenants concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        fa = pool.submit(customer_a_spike, agw_ip, sql_fqdn, sql_password)
        fb = pool.submit(customer_b_steady, agw_ip, sql_fqdn, sql_password)
        fc = pool.submit(customer_c_low, agw_ip, sql_fqdn, sql_password)

        for f in concurrent.futures.as_completed([fa, fb, fc]):
            try:
                f.result()
            except Exception as e:
                print(f"WARNING: tenant task failed: {e}", file=sys.stderr)

    print("\n=== Traffic generation complete ===")


if __name__ == "__main__":
    main()
