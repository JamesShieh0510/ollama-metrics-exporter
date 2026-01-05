# ollama-metrics-exporter

## Overview

This project is a Prometheus metrics exporter for Ollama, designed to monitor and expose network connection metrics for Ollama services. It provides real-time monitoring of connections to the Ollama port and estimates network traffic based on connection counts.

## Features

- Exposes Prometheus metrics for Ollama connections
- Estimates network traffic based on connection counts
- Supports multiple operating systems (Windows, macOS, Linux)
- Provides network topology visualization capabilities
- Includes CORS support for web-based dashboards

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

1. Configure the `.env` file (optional):
   ```
   NODE_NAME=node1
   OLLAMA_PORT=11434
   ```

2. Run the exporter:
   ```bash
   ./start.sh
   ```

## Metrics Exposed

- `ollama_connections`: Current number of connections to Ollama port
- `ollama_bytes_sent_total`: Total bytes sent to Ollama port
- `ollama_bytes_recv_total`: Total bytes received from Ollama port
- `ollama_node_to_router`: Connection from node to router (for NodeGraph edges)

## Configuration

The exporter can be configured using environment variables:
- `NODE_NAME`: Name of the node (default: "node1")
- `OLLAMA_PORT`: Port number of Ollama service (default: 11434)

## License

MIT License
