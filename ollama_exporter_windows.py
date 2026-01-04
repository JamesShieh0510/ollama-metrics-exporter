# ollama_exporter.py
import subprocess
from prometheus_client import start_http_server, Gauge
import time

connections = Gauge("ollama_tcp_connections", "TCP connections on 11434")

def count_conn():
    try:
        cmd = 'netstat -ano | findstr :11434 | findstr ESTABLISHED'
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).strip()
        if output:
            return len(output.decode().split('\n'))
        return 0
    except subprocess.CalledProcessError:
        return 0

if __name__ == "__main__":
    start_http_server(9101)
    while True:
        connections.set(count_conn())
        time.sleep(2)
