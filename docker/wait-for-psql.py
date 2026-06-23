#!/usr/bin/env python3
"""
PostgreSQL availability check with configurable retry logic.
Used by Docker entrypoint to ensure DB is ready before Odoo starts.
"""
import os
import sys
import time
import socket


def wait_for_postgres(
    host: str = "db",
    port: int = 5432,
    timeout: int = 60,
    interval: float = 2.0,
) -> bool:
    """Block until PostgreSQL accepts connections or timeout expires."""
    start = time.monotonic()
    while (time.monotonic() - start) < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(interval)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                return True
        except OSError:
            pass
        time.sleep(interval)
    return False


def main():
    host = os.environ.get("DB_HOST", "db")
    port = int(os.environ.get("DB_PORT", "5432"))
    timeout = int(os.environ.get("DB_WAIT_TIMEOUT", "60"))

    print(f"Waiting for PostgreSQL at {host}:{port} (timeout={timeout}s)...")
    if wait_for_postgres(host, port, timeout):
        print("PostgreSQL is ready")
        sys.exit(0)
    else:
        print(f"ERROR: PostgreSQL not reachable after {timeout}s", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
