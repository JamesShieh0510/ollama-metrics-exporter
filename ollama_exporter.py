# ollama_exporter.py
import subprocess
from prometheus_client import start_http_server, Gauge
import time

connections = Gauge("ollama_tcp_connections", "TCP connections on 11434")

def count_conn():
    cmd = "lsof -nP -iTCP:11434 | grep ESTABLISHED | wc -l"
    return int(subprocess.check_output(cmd, shell=True).strip())

if __name__ == "__main__":
    start_http_server(9101)
    while True:
        connections.set(count_conn())
        time.sleep(2)

