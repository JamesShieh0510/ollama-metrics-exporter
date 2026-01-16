# Node Graph 無數據問題排查指南

## 問題描述
Node Graph 查詢返回空的 frames，所有三個查詢（A, B, C）都返回 `"fields": []` 和 `"values": []`。

## 可能原因

### 1. Prometheus 沒有收集到指標數據

**檢查方法：**

```bash
# 檢查 Prometheus 是否能夠查詢到指標
curl 'http://localhost:9090/api/v1/query?query=ollama_connections'

# 檢查特定節點的指標
curl 'http://localhost:9090/api/v1/query?query=ollama_connections{node="node1"}'

# 檢查所有節點的指標
curl 'http://localhost:9090/api/v1/query?query=ollama_connections'

# 檢查流量指標
curl 'http://localhost:9090/api/v1/query?query=ollama_bytes_sent_total'
curl 'http://localhost:9090/api/v1/query?query=ollama_bytes_recv_total'
```

**預期輸出應該包含：**
```
{
  "status": "success",
  "data": {
    "resultType": "vector",
    "result": [
      {
        "metric": {
          "node": "node1",
          "state": "ESTABLISHED"
        },
        "value": [1767534531.560, "2"]
      },
      ...
    ]
  }
}
```

### 2. Prometheus 配置問題

**檢查 Prometheus 配置 (`prometheus.yml`)：**

```yaml
scrape_configs:
  - job_name: 'ollama-exporter'
    scrape_interval: 15s
    static_configs:
      - targets:
        - '192.168.50.158:9101'  # node1
        - '192.168.50.31:9101'   # node2
        - '192.168.50.94:9101'   # node3
        - '192.168.50.155:9101'  # node4
```

**驗證 Prometheus 是否成功抓取：**
1. 打開 Prometheus UI: `http://localhost:9090`
2. 進入 **Status > Targets**
3. 確認所有 exporter 的狀態都是 **UP**

### 3. Exporter 沒有運行或沒有數據

**檢查每個節點的 exporter：**

```bash
# 檢查 node1
curl http://192.168.50.158:9101/metrics | grep ollama_connections

# 檢查 node2
curl http://192.168.50.31:9101/metrics | grep ollama_connections

# 檢查 node3
curl http://192.168.50.94:9101/metrics | grep ollama_connections

# 檢查 node4
curl http://192.168.50.155:9101/metrics | grep ollama_connections
```

**預期輸出應該包含：**
```
# HELP ollama_connections Current number of connections to Ollama port
# TYPE ollama_connections gauge
ollama_connections{node="node1",state="ESTABLISHED"} 2.0
ollama_connections{node="node1",state="LISTEN"} 1.0
```

### 4. 時間範圍問題

**檢查 Grafana 的時間範圍：**
- 打開 Dashboard
- 檢查右上角的時間選擇器
- 確保時間範圍包含當前時間（例如：`Last 15 minutes`）

**檢查 Prometheus 查詢時間：**
從你提供的查詢響應中，時間範圍是：
- `from`: `1767532731560` (2026-01-04 12:38:51)
- `to`: `1767534531560` (2026-01-04 13:08:51)

確保這個時間範圍內 Prometheus 有數據。

### 5. 指標標籤不匹配

**檢查指標的實際標籤：**

```bash
# 在 Prometheus UI 中執行
ollama_connections

# 查看返回的所有標籤組合
```

確保查詢中的標籤（如 `state="ESTABLISHED"`）與實際指標的標籤匹配。

## 解決方案

### 方案 1: 確保 Exporter 正在運行

```bash
# 在每個節點上檢查 exporter 是否運行
ps aux | grep ollama_exporter

# 如果沒有運行，啟動它
cd /path/to/ollama-metrics-exporter
python3 ollama_exporter.py
```

### 方案 2: 檢查 Prometheus 配置

1. 確認 `prometheus.yml` 中的 targets 正確
2. 重啟 Prometheus
3. 等待至少一個 scrape interval（15秒）後再檢查

### 方案 3: 驗證指標是否存在

在 Prometheus UI (`http://localhost:9090`) 中執行以下查詢：

```promql
# 檢查所有指標
{__name__=~"ollama_.*"}

# 檢查連接數指標
ollama_connections

# 檢查流量指標
ollama_bytes_sent_total
ollama_bytes_recv_total
```

如果這些查詢都返回空，說明 Prometheus 沒有收集到數據。

### 方案 4: 檢查網絡連接

```bash
# 從 Prometheus 服務器測試連接到各個 exporter
curl http://192.168.50.158:9101/metrics
curl http://192.168.50.31:9101/metrics
curl http://192.168.50.94:9101/metrics
curl http://192.168.50.155:9101/metrics
```

### 方案 5: 使用 Grafana Explore 測試查詢

1. 打開 Grafana
2. 進入 **Explore**
3. 選擇 Prometheus 數據源
4. 執行查詢：
   - `ollama_connections{state="ESTABLISHED"}`
   - `rate(ollama_bytes_sent_total[5m])`
   - `rate(ollama_bytes_recv_total[5m])`

如果 Explore 中也沒有數據，問題在 Prometheus 或 Exporter，而不是 Dashboard 配置。

## 快速診斷腳本

創建一個診斷腳本來檢查所有節點：

```bash
#!/bin/bash

NODES=(
  "192.168.50.158:9101:node1"
  "192.168.50.31:9101:node2"
  "192.168.50.94:9101:node3"
  "192.168.50.155:9101:node4"
)

echo "=== 檢查 Exporter 狀態 ==="
for node_info in "${NODES[@]}"; do
  IFS=':' read -r ip port name <<< "$node_info"
  echo "檢查 $name ($ip:$port)..."
  
  if curl -s "http://$ip:$port/metrics" | grep -q "ollama_connections"; then
    echo "✅ $name: Exporter 正常運行"
    curl -s "http://$ip:$port/metrics" | grep "ollama_connections" | head -2
  else
    echo "❌ $name: Exporter 無響應或無數據"
  fi
  echo ""
done

echo "=== 檢查 Prometheus 查詢 ==="
if command -v curl &> /dev/null; then
  echo "查詢 ollama_connections:"
  curl -s 'http://localhost:9090/api/v1/query?query=ollama_connections' | jq '.data.result | length'
  echo "結果數量（應該 > 0）"
fi
```

## 常見問題

### Q: 為什麼查詢返回空的 frames？
A: 最可能的原因是 Prometheus 沒有收集到數據。檢查：
1. Exporter 是否運行
2. Prometheus 配置是否正確
3. 網絡連接是否正常

### Q: 為什麼 `rate()` 函數返回空？
A: `rate()` 需要至少兩個數據點才能計算速率。如果指標剛開始收集，可能需要等待幾分鐘。

### Q: 如何確認 Prometheus 正在抓取數據？
A: 在 Prometheus UI 中：
1. 進入 **Status > Targets**
2. 確認所有 targets 狀態為 **UP**
3. 進入 **Status > Configuration** 確認配置已加載

## 下一步

如果以上步驟都無法解決問題，請提供：
1. Prometheus 的 targets 狀態截圖
2. 從 exporter 直接查詢 metrics 的輸出
3. Prometheus 查詢 API 的響應
4. Grafana Explore 中執行相同查詢的結果

