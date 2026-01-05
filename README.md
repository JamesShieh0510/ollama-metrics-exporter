# ollama-metrics-exporter

## Overview

This project includes:
1. **Ollama Metrics Exporter**: A Prometheus metrics exporter for Ollama, designed to monitor and expose network connection metrics for Ollama services.
2. **Ollama Gateway**: A unified gateway with load balancing and reverse proxy capabilities for distributing LLM requests across multiple Ollama nodes.

## Features

### Metrics Exporter
- Exposes Prometheus metrics for Ollama connections
- Estimates network traffic based on connection counts
- Supports multiple operating systems (Windows, macOS, Linux)
- Provides network topology visualization capabilities
- Includes CORS support for web-based dashboards

### Gateway
- Reverse proxy for distributing requests across multiple Ollama nodes
- Multiple load balancing strategies (round-robin, least-connections, weighted round-robin)
- Automatic health checking and failover
- Full support for streaming responses
- Prometheus metrics for monitoring

## Prerequisites

- Python 3.6+
- Ollama service running on the system
- Prometheus server for metrics collection

## Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Running the Metrics Exporter

1. Configure the `.env` file (optional):
   ```
   NODE_NAME=node1
   OLLAMA_PORT=11434
   ```

2. Run the exporter:
   ```bash
   ./start.sh
   ```

### Running the Gateway

The gateway provides a unified entry point for multiple Ollama nodes. See [GATEWAY_README.md](GATEWAY_README.md) for detailed documentation.

Quick start:
```bash
./start_gateway.sh
```

The gateway will start on port 11435 (configurable via `GATEWAY_PORT` environment variable).

## Metrics Exposed

- `ollama_connections`: Current number of connections to Ollama port
- `ollama_bytes_sent_total`: Total bytes sent to Ollama port
- `ollama_bytes_recv_total`: Total bytes received from Ollama port
- `ollama_node_to_router`: Connection from node to router (for NodeGraph edges)

## Configuration

### Metrics Exporter

The exporter can be configured using environment variables:
- `NODE_NAME`: Name of the node (default: "node1")
- `OLLAMA_PORT`: Port number of Ollama service (default: 11434)

### Gateway

The gateway can be configured using environment variables:
- `GATEWAY_PORT`: Port for the gateway service (default: 11435)
- `SCHEDULING_STRATEGY`: Load balancing strategy - `round_robin`, `least_connections`, or `weighted_round_robin` (default: "round_robin")

See [GATEWAY_README.md](GATEWAY_README.md) for more details.

## License

MIT License
