import time
import requests
from fastapi import FastAPI, Request
from prometheus_client import (
    Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
)
from fastapi.responses import Response
import uvicorn

OLLAMA_BASE = "http://127.0.0.1:11434"

app = FastAPI()

# ---- Prometheus metrics ----
ollama_requests_total = Counter(
    "ollama_requests_total",
    "Total Ollama generate requests",
    ["node"]
)

ollama_inflight_requests = Gauge(
    "ollama_inflight_requests",
    "Current inflight Ollama requests",
    ["node"]
)

ollama_request_latency = Histogram(
    "ollama_request_latency_seconds",
    "Ollama request latency",
    ["node"],
    buckets=(0.5, 1, 2, 5, 10, 30, 60)
)

NODE_NAME = "node1"  # 每台機器改這個（node1/node2/...）

# ---- Proxy endpoint ----
@app.post("/api/generate")
async def generate(req: Request):
    body = await req.body()
    headers = dict(req.headers)

    ollama_inflight_requests.labels(node=NODE_NAME).inc()
    start = time.time()

    try:
        resp = requests.post(
            f"{OLLAMA_BASE}/api/generate",
            data=body,
            headers=headers,
            stream=False,
            timeout=None,
        )
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type=resp.headers.get("content-type")
        )
    finally:
        duration = time.time() - start
        ollama_requests_total.labels(node=NODE_NAME).inc()
        ollama_request_latency.labels(node=NODE_NAME).observe(duration)
        ollama_inflight_requests.labels(node=NODE_NAME).dec()

# ---- Metrics endpoint ----
@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9101)

