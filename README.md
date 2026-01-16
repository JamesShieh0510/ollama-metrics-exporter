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

### Platform-Specific Requirements

- **Windows**: PowerShell 5.1+ (Windows 10+ default) or netstat
- **macOS**: lsof (usually pre-installed) or netstat
- **Linux**: lsof, ss (iproute2), or netstat

**Note**: The exporter automatically uses system commands that don't require root/admin privileges.

## Project Structure

```
ollama-metrics-exporter/
├── src/                    # Python 源代码
│   ├── ollama_exporter.py  # Metrics exporter
│   ├── ollama_gateway.py   # Gateway 服务
│   └── ollama_humaneval_runner.py  # HumanEval 评估工具
├── config/                 # 配置文件
│   ├── node_config.json    # 节点配置
│   └── grafana-dashboard.json  # Grafana 仪表板配置
├── scripts/                # 启动和工具脚本
│   ├── start.sh            # 启动 exporter
│   ├── start_gateway.sh    # 启动 gateway
│   └── ...
├── static/                 # 静态文件
│   └── topology-3d.html    # 3D 拓扑可视化
├── data/                   # 数据文件
│   └── results.jsonl       # 评估结果
├── backups/                # 备份文件
├── docs/                   # 文档目录
├── requirements.txt        # Python 依赖
└── README.md              # 项目说明
```

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
   ./scripts/start.sh
   ```
   
   Or using PM2 (recommended for production):
   ```bash
   pm2 start ecosystem.config.js
   ```

### Running the Gateway

The gateway provides a unified entry point for multiple Ollama nodes. See [docs/GATEWAY_README.md](docs/GATEWAY_README.md) for detailed documentation.

Quick start:
```bash
./scripts/start_gateway.sh
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

See [docs/GATEWAY_README.md](docs/GATEWAY_README.md) for more details.

## Documentation

所有详细文档已统一管理在 [docs/](docs/) 目录下，包括：

- [Gateway 使用说明](docs/GATEWAY_README.md) - 完整的 Gateway 配置和使用文档
- [节点配置说明](docs/NODE_CONFIG_README.md) - 节点配置文件详细说明
- [Grafana 设置指南](docs/GRAFANA_SETUP.md) - Grafana 仪表板配置
- [3D 拓扑可视化](docs/TOPOLOGY_3D_README.md) - 网络拓扑可视化说明
- [故障排除指南](docs/TROUBLESHOOTING.md) - 常见问题解决方案
- [Whisper 实现计划](docs/WHISPER_IMPLEMENTATION_PLAN.md) - Whisper Large V3 集成计划

更多文档请查看 [docs/README.md](docs/README.md)

## License

MIT License
