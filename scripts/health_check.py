#!/usr/bin/env python3
"""
NN Fund Management — Production Health Check
Verifies: PostgreSQL connectivity, Odoo process, cron jobs, disk space

Usage:
    python scripts/health_check.py          # Full health check
    python scripts/health_check.py --quick   # Basic connectivity only

Exit code: 0 = healthy, 1 = warning, 2 = critical
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def check_postgresql(
    host: str = None,
    port: int = None,
    db: str = None,
    user: str = None,
    password: str = None,
) -> dict:
    """Verify PostgreSQL is accepting connections and responding."""
    result = {"status": "unknown", "message": "", "latency_ms": 0}
    host = host or os.environ.get("DB_HOST", "db")
    port = port or int(os.environ.get("DB_PORT", "5432"))
    db = db or os.environ.get("DB_NAME", "nn_fund_management")
    user = user or os.environ.get("DB_USER", "odoo")

    try:
        start = time.monotonic()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((host, port))
        sock.close()
        latency = (time.monotonic() - start) * 1000
        result["status"] = "healthy"
        result["message"] = f"PostgreSQL accepting connections at {host}:{port}"
        result["latency_ms"] = round(latency, 2)
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        result["status"] = "critical"
        result["message"] = f"PostgreSQL unreachable: {e}"
    return result


def check_disk_usage(paths: list[str] = None) -> list[dict]:
    """Verify disk usage is below threshold."""
    thresholds = {"warning": 80, "critical": 90}
    results = []
    for p in paths or ["/", "/opt/odoo", "/var/log", "/backup"]:
        try:
            usage = shutil.disk_usage(p)
            percent = usage.used / usage.total * 100
            status = "healthy"
            if percent >= thresholds["critical"]:
                status = "critical"
            elif percent >= thresholds["warning"]:
                status = "warning"
            results.append({
                "path": p,
                "status": status,
                "used_gb": round(usage.used / (1024**3), 2),
                "total_gb": round(usage.total / (1024**3), 2),
                "percent": round(percent, 1),
            })
        except FileNotFoundError:
            results.append({"path": p, "status": "warning", "message": "Path not found"})
    return results


def check_odoo_process() -> dict:
    """Verify Odoo process is running."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect(("localhost", 8069))
        sock.close()
        return {"status": "healthy", "message": "Odoo HTTP listener responding on port 8069"}
    except (socket.timeout, ConnectionRefusedError) as e:
        return {"status": "critical", "message": f"Odoo not responding: {e}"}


def check_cron_processes() -> dict:
    """Verify cron workers are running."""
    try:
        # Check for Odoo cron workers
        result = subprocess.run(
            ["pgrep", "-f", "odoo.*cron"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        pid_count = len(result.stdout.strip().split("\n")) if result.stdout.strip() else 0
        if pid_count > 0:
            return {"status": "healthy", "message": f"{pid_count} cron worker(s) running"}
        return {"status": "warning", "message": "No dedicated cron workers found"}
    except (subprocess.SubprocessError, FileNotFoundError):
        return {"status": "warning", "message": "Cannot check cron processes"}


def check_recent_backup(backup_dir: str = None) -> dict:
    """Verify recent backup exists (within 24 hours)."""
    backup_dir = backup_dir or os.environ.get("BACKUP_DIR", "/backup")
    try:
        bd = Path(backup_dir)
        if not bd.exists():
            return {"status": "warning", "message": f"Backup directory not found: {backup_dir}"}
        recent = [d for d in bd.iterdir() if d.is_dir() and d.name.isdigit()]
        if not recent:
            return {"status": "warning", "message": "No backups found"}
        latest = max(recent, key=lambda d: d.name)
        age_hours = (datetime.now() - datetime.fromtimestamp(latest.stat().st_mtime)).total_seconds() / 3600
        if age_hours < 24:
            return {"status": "healthy", "message": f"Latest backup: {latest.name} ({age_hours:.1f}h ago)"}
        return {"status": "warning", "message": f"Latest backup is {age_hours:.1f}h old: {latest.name}"}
    except Exception as e:
        return {"status": "warning", "message": f"Cannot check backups: {e}"}


def run_health_check(quick: bool = False) -> dict:
    """Execute all health checks and return aggregated result."""
    checks = {
        "timestamp": datetime.utcnow().isoformat(),
        "hostname": socket.gethostname(),
        "version": "18.0.4.0.0",
    }

    checks["postgresql"] = check_postgresql()
    checks["odoo"] = check_odoo_process()

    if not quick:
        checks["disk_usage"] = check_disk_usage()
        checks["cron"] = check_cron_processes()
        checks["backup"] = check_recent_backup()

    # Overall status
    statuses = []
    for key, check in checks.items():
        if isinstance(check, dict) and "status" in check:
            statuses.append(check["status"])
    if "critical" in statuses:
        checks["overall_status"] = "critical"
    elif "warning" in statuses:
        checks["overall_status"] = "warning"
    else:
        checks["overall_status"] = "healthy"

    return checks


def main():
    quick = "--quick" in sys.argv
    output_format = "json" if "--json" in sys.argv else "text"

    result = run_health_check(quick)
    status_map = {"healthy": 0, "warning": 1, "critical": 2}
    exit_code = status_map.get(result.get("overall_status", "critical"), 2)

    if output_format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"\nNN Fund Management — Health Check ({result['timestamp']})")
        print(f"Host: {result['hostname']}  |  Overall: {result['overall_status'].upper()}")
        print("=" * 60)
        for key, check in result.items():
            if key in ("timestamp", "hostname", "version", "overall_status"):
                continue
            if isinstance(check, dict) and "status" in check:
                icon = {"healthy": "OK", "warning": "!!", "critical": "!!"}.get(check["status"], "??")
                print(f"  [{icon}] {key}: {check.get('message', check['status'])}")
            elif isinstance(check, list):
                for item in check:
                    icon = {"healthy": "OK", "warning": "!!", "critical": "!!"}.get(item.get("status", ""), "??")
                    print(f"  [{icon}] disk/{item.get('path')}: {item.get('percent', '?')}% used")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
