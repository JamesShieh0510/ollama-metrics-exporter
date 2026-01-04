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

# 更穩的「活動連線數」：ESTABLISHED + SYN_*
ollama_tcp_active = Gauge("ollama_tcp_active", "ACTIVE TCP connections to port 11434 (ESTABLISHED + SYN_*)")

# 用 ACTIVE 的上升近似新連線
ollama_tcp_new_connections_total = Counter(
    "ollama_tcp_new_connections_total",
    "Approx new TCP connections to 11434 (increments when ACTIVE count increases)"
)

ACTIVE_STATES = {"ESTABLISHED", "SYN_SENT", "SYN_RECV"}

def count_tcp(port: int) -> Tuple[int, int, int]:
    est = 0
    listen = 0
    active = 0

    for c in psutil.net_connections(kind="inet"):
        if c.type != socket.SOCK_STREAM:
            continue
        if not c.laddr:
            continue
        if c.laddr.port != port:
            continue

        status = (c.status or "").upper()
        if status == "LISTEN":
            listen += 1
        if status == "ESTABLISHED":
            est += 1
        if status in ACTIVE_STATES:
            active += 1

    return est, listen, active

def main():
    start_http_server(EXPORTER_PORT)
    prev_active = 0

    while True:
        try:
            est, listen, active = count_tcp(PORT)
            ollama_tcp_established.set(est)
            ollama_tcp_listen_up.set(1 if listen > 0 else 0)
            ollama_tcp_active.set(active)

            if active > prev_active:
                ollama_tcp_new_connections_total.inc(active - prev_active)
            prev_active = active
        except Exception:
            pass

        time.sleep(INTERVAL_SEC)

if __name__ == "__main__":
    main()

