# Ollama Gateway - 調度器和反向代理

## 概述

Ollama Gateway 是一個統一的網關服務，負責將 LLM 請求轉發到多個 Ollama 節點。它提供了負載均衡、健康檢查、請求監控等功能。

## 功能特性

- ✅ **反向代理**: 將所有請求透明轉發到後端 Ollama 節點
- ✅ **多種調度策略**: 支持輪詢、最少連接數、加權輪詢
- ✅ **智能節點選擇**: 根據模型大小和節點硬件規格自動選擇最適合的節點
- ✅ **模型感知路由**: 自動檢測節點上已下載的模型，只路由到有該模型的節點
- ✅ **健康檢查**: 自動檢測節點健康狀態，自動剔除不健康節點
- ✅ **流式響應支持**: 完整支持 Ollama 的流式響應
- ✅ **Prometheus 監控**: 提供詳細的請求指標和節點狀態
- ✅ **高可用性**: 自動故障轉移，確保服務可用性

## 節點配置

當前配置的節點：

| 節點名 | IP地址 | 主機名 | 端口 | 權重 |
|--------|--------|--------|------|------|
| node1  | 192.168.50.158 | m3max, m3max.local, m3max-128gb.local | 11434 | 1.0 |
| node2  | 192.168.50.31  | m1max, m1max.local, m1max-64gb.local | 11434 | 1.0 |
| node3  | 192.168.50.94  | m1, m1.local, m1-16gb.local | 11434 | 1.0 |
| node4  | 192.168.50.155 | i7, i74080.local, i7g13-4080-32gb.local | 11434 | 1.0 |

## 安裝和啟動

### 1. 安裝依賴

```bash
pip install -r requirements.txt
```

### 2. 配置節點硬件規格（可選）

編輯 `node_config.json` 文件來配置節點的硬件規格和模型大小規則：

```json
{
  "nodes": [
    {
      "name": "node1",
      "memory_gb": 128,
      "description": "m3max-128gb",
      "supported_model_ranges": [
        {
          "min_params_b": 100,
          "max_params_b": null,
          "description": "120B+ 大模型"
        }
      ]
    }
  ],
  "model_name_patterns": {
    "120b": 120,
    "70b": 70,
    "8b": 8
  }
}
```

### 3. 配置環境變量（可選）

創建 `.env` 文件：

```env
# 網關端口（默認: 11435）
GATEWAY_PORT=11435

# 調度策略: round_robin, least_connections, weighted_round_robin
SCHEDULING_STRATEGY=round_robin

# 節點配置文件路徑（默認: node_config.json）
NODE_CONFIG_FILE=node_config.json
```

### 4. 啟動網關

```bash
# 使用啟動腳本
chmod +x start_gateway.sh
./start_gateway.sh

# 或直接運行
python ollama_gateway.py
```

網關將在 `http://0.0.0.0:11435` 啟動。

## 使用方法

### 基本使用

網關會代理所有請求到後端節點。只需將原來的 Ollama API 地址改為網關地址即可：

```bash
# 原來的請求
curl http://192.168.50.158:11434/api/tags

# 使用網關（自動轉發到某個節點）
curl http://localhost:11435/api/tags
```

### 示例：使用 Ollama Python 客戶端

```python
import ollama

# 配置客戶端使用網關
client = ollama.Client(host='http://localhost:11435')

# 正常使用，網關會自動轉發請求
response = client.generate(
    model='llama2',
    prompt='Why is the sky blue?'
)
```

### 示例：使用 curl

```bash
# 列出模型
curl http://localhost:11435/api/tags

# 生成文本
curl http://localhost:11435/api/generate -d '{
  "model": "llama2",
  "prompt": "Why is the sky blue?",
  "stream": false
}'

# 流式生成
curl http://localhost:11435/api/generate -d '{
  "model": "llama2",
  "prompt": "Why is the sky blue?",
  "stream": true
}'
```

## 智能節點選擇

網關會根據以下規則自動選擇最適合的節點：

1. **模型可用性檢查**: 只選擇已下載該模型的節點
2. **硬件規格匹配**: 根據模型大小匹配節點的硬件規格
3. **調度策略**: 在符合條件的節點中，根據調度策略選擇

### 模型大小識別

網關會從模型名稱中自動識別模型大小（參數數量），例如：
- `llama2-70b` → 70B
- `qwen2.5-120b` → 120B
- `llama2-7b` → 7B

### 硬件規格匹配規則

根據 `node_config.json` 配置：
- **120B+ 模型** → 自動路由到 128GB 的 node1 (m3max)
- **30B~70B 模型** → 自動路由到 32GB 的 node2 (m1max)
- **1B~8B 小模型** → 自動路由到 16GB 的 node3 (m1) 或 32GB 的 node4 (i7-4080)

如果沒有找到完全匹配的節點，網關會回退到所有健康節點。

## 調度策略

在通過模型和硬件篩選後，使用以下策略選擇節點：

### 1. Round Robin (輪詢) - 默認

請求按順序輪流分配到各個符合條件的節點。

```env
SCHEDULING_STRATEGY=round_robin
```

### 2. Least Connections (最少連接數)

將請求分配給當前連接數最少的節點。

```env
SCHEDULING_STRATEGY=least_connections
```

### 3. Weighted Round Robin (加權輪詢)

根據節點權重分配請求，權重高的節點會收到更多請求。

```env
SCHEDULING_STRATEGY=weighted_round_robin
```

## Web 界面

### 3D 網絡拓撲可視化

訪問 `http://localhost:11435/topology` 或 `http://localhost:11435/` 查看實時的 3D 網絡拓撲圖。

拓撲圖會顯示：
- 所有節點的實時狀態
- 節點之間的連接和流量
- 硬件規格和 IP 信息
- 連接數和流量統計

### 歡迎頁面

訪問 `http://localhost:11435/` 會顯示歡迎頁面，包含所有可用的端點鏈接。

## API 端點

### 健康檢查

```bash
curl http://localhost:11435/health
```

返回：
```json
{
  "status": "healthy",
  "healthy_nodes": 4,
  "total_nodes": 4,
  "nodes": {
    "node1": {
      "healthy": true,
      "active_connections": 2,
      "total_requests": 100,
      "failed_requests": 0
    },
    ...
  }
}
```

### 節點狀態

```bash
curl http://localhost:11435/nodes
```

返回所有節點的詳細狀態和配置，包括：
- 節點基本信息（主機名、端口、權重）
- 運行狀態（健康狀態、連接數、請求統計）
- 已下載的模型列表
- 硬件配置信息

### Prometheus Metrics

```bash
curl http://localhost:11435/metrics
```

提供的指標：
- `gateway_requests_total`: 總請求數（按方法、端點、節點、狀態）
- `gateway_request_duration_seconds`: 請求持續時間
- `gateway_active_connections`: 每個節點的活躍連接數
- `gateway_node_health`: 節點健康狀態（1=健康，0=不健康）

## 健康檢查和模型同步

網關會每 30 秒自動檢查所有節點的健康狀態，並同步每個節點上已下載的模型列表。健康檢查通過訪問 `/api/tags` 端點來判斷節點是否可用。

如果節點不健康：
- 該節點會被自動從調度池中移除
- 請求不會轉發到該節點
- 節點恢覆後會自動重新加入調度池

模型列表同步：
- 每次健康檢查時，網關會獲取每個節點上已下載的模型列表
- 只有包含請求模型的節點才會被考慮用於路由
- 這確保了請求只會轉發到實際擁有該模型的節點

## 監控和日志

### 查看節點狀態

```bash
# 查看所有節點狀態
curl http://localhost:11435/nodes | jq

# 查看健康狀態
curl http://localhost:11435/health | jq
```

### Prometheus 集成

將網關的 metrics 端點添加到 Prometheus 配置：

```yaml
scrape_configs:
  - job_name: 'ollama-gateway'
    static_configs:
      - targets: ['localhost:11435']
```

## 故障排除

### 1. 所有節點都不可用

如果所有節點都不可用，網關會返回 503 錯誤。檢查：
- 節點是否正常運行
- 網絡連接是否正常
- 防火墻設置

### 2. 請求超時

默認超時設置為 5 分鐘。如果請求超時，檢查：
- 節點性能是否正常
- 模型是否過大
- 網絡延遲

### 3. 節點健康檢查失敗

檢查：
- 節點上的 Ollama 服務是否正常運行
- 節點是否可以訪問 `/api/tags` 端點
- 網絡連接是否正常

## 配置自定義節點

編輯 `ollama_gateway.py` 中的 `NODES` 配置：

```python
NODES = [
    {
        "name": "node1",
        "hosts": ["192.168.50.158", "m3max.local"],
        "port": 11434,
        "weight": 1.0,
        "enabled": True,
    },
    # 添加更多節點...
]
```

## 性能優化建議

1. **使用最少連接數策略**: 如果節點性能差異較大，使用 `least_connections` 策略
2. **調整權重**: 根據節點性能調整權重，性能好的節點設置更高權重
3. **監控指標**: 定期查看 Prometheus metrics，了解各節點的負載情況
4. **健康檢查間隔**: 根據需求調整健康檢查間隔（默認30秒）

## 安全注意事項

1. **生產環境**: 建議限制 CORS 來源，不要使用 `allow_origins=["*"]`
2. **認證**: 考慮添加 API 密鑰或認證機制
3. **HTTPS**: 生產環境建議使用 HTTPS
4. **防火墻**: 確保只有必要的端口對外開放

## 許可證

MIT License

