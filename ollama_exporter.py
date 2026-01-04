
import time
import socket
from typing import Tuple

import psutil
from prometheus_client import start_http_server, Gauge, Counter

PORT = 11434
EXPORTER_PORT = 9101
INTERVAL_SEC = 2

ollama_tcp_established = Gauge("ollama_tcp_established", "ESTABLISHED TCP connections to port 11434")
ollama_tcp_listen_up = Gauge("ollama_tcp_listen_up", "Port 11434 is LISTENing (1/0)")
ollama_tcp_new_connections_total = Counter(
    "ollama_tcp_new_connections_total",
    "Approx new TCP connections to 11434 (increments when established count increases)"
)

def count_tcp(port: int) -> Tuple[int, int]:
    """
    Returns (established_count, listen_count) for a local TCP port.
    Uses psutil.net_connections which works on Windows/macOS/Linux.
    """
    est = 0
    listen = 0

    # inet = both IPv4/IPv6
    for c in psutil.net_connections(kind="inet"):
        if c.type != socket.SOCK_STREAM:
            continue
        laddr = c.laddr if c.laddr else None
        if not laddr:
            continue
        if laddr.port != port:
            continue

        status = (c.status or "").upper()
        if status == "LISTEN":
            listen += 1
        elif status == "ESTABLISHED":
            est += 1

    return est, listen

def main():
    start_http_server(EXPORTER_PORT)
    prev_est = 0

    while True:
        try:
            est, listen = count_tcp(PORT)
            ollama_tcp_established.set(est)
            ollama_tcp_listen_up.set(1 if listen > 0 else 0)

            if est > prev_est:
                ollama_tcp_new_connections_total.inc(est - prev_est)
            prev_est = est
        except Exception:
            # 如果遇到權限/系統限制，至少別讓 exporter 死掉
            pass

        time.sleep(INTERVAL_SEC)

if __name__ == "__main__":
    main()
