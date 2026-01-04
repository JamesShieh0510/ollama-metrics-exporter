# Dashboard 無數據排查指南

## 快速檢查清單

### 1. 檢查 Exporter 是否運行

```bash
# 檢查 exporter 是否在運行
curl http://localhost:9101/metrics

# 或者檢查其他節點
curl http://192.168.50.158:9101/metrics  # node1
curl http://192.168.50.31:9101/metrics   # node2
curl http://192.168.50.94:9101/metrics  # node3
curl http://192.168.50.155:9101/metrics # node4
```

**預期輸出**：應該看到類似以下的 metrics：
```
# HELP ollama_connections Current number of connections to Ollama port
# TYPE ollama_connections gauge
ollama_connections{node="node1",state="ESTABLISHED"} 0.0
ollama_connections{node="node1",state="LISTEN"} 1.0
# HELP ollama_bytes_sent_total Total bytes sent to Ollama port
# TYPE ollama_bytes_sent_total counter
ollama_bytes_sent_total{node="node1"} 0.0
# HELP ollama_bytes_recv_total Total bytes received from Ollama port
# TYPE ollama_bytes_recv_total counter
ollama_bytes_recv_total{node="node1"} 0.0
```

### 2. 檢查 Prometheus 配置

確認 `prometheus.yml` 中有正確的 scrape 配置：

```yaml
scrape_configs:
  - job_name: 'ollama-exporter'
    scrape_interval: 10s
    static_configs:
      - targets:
        - '192.168.50.158:9101'  # node1
        - '192.168.50.31:9101'   # node2
        - '192.168.50.94:9101'   # node3
        - '192.168.50.155:9101'  # node4
```

### 3. 檢查 Prometheus 是否抓取到數據

在 Prometheus UI 中（通常是 http://localhost:9090）：

1. 進入 **Status** → **Targets**
2. 確認所有 `ollama-exporter` targets 都是 **UP** 狀態
3. 如果有錯誤，檢查錯誤訊息

### 4. 在 Prometheus 中測試查詢

在 Prometheus 的查詢界面中測試：

```promql
# 測試連接數
ollama_connections

# 測試流量
ollama_bytes_sent_total
ollama_bytes_recv_total

# 測試特定節點
ollama_connections{node="node1"}
```

如果這些查詢在 Prometheus 中都沒有結果，問題在 Prometheus 配置或 exporter。

### 5. 檢查 Grafana 數據源配置

1. 進入 Grafana → **Configuration** → **Data Sources**
2. 選擇你的 Prometheus 數據源
3. 點擊 **Test** 按鈕，確認連接成功
4. 確認 **URL** 正確（例如：`http://localhost:9090`）

### 6. 檢查 Dashboard 查詢

在 Grafana Dashboard 中：

1. 點擊面板標題 → **Edit**
2. 檢查 **Query** 是否正確
3. 點擊 **Query inspector** 查看實際查詢結果
4. 檢查是否有錯誤訊息

### 7. 檢查時間範圍

確認 Dashboard 的時間範圍設置正確：
- 右上角時間選擇器
- 選擇 **Last 1 hour** 或 **Last 5 minutes**
- 確認時間範圍內有數據

### 8. 檢查節點標籤

確認每個節點的 `.env` 文件中的 `NODE_NAME` 設置正確：

```env
# node1 的 .env
NODE_NAME=node1

# node2 的 .env
NODE_NAME=node2

# node3 的 .env
NODE_NAME=node3

# node4 的 .env
NODE_NAME=node4
```

### 9. 檢查防火牆和網絡

確認：
- 9101 端口在所有節點上開放
- Prometheus 可以訪問所有 exporter 端口
- Grafana 可以訪問 Prometheus

### 10. 檢查 Exporter 日誌

查看 exporter 的輸出，確認：
- 沒有權限錯誤
- 監控任務正常運行
- 沒有異常訊息

## 常見問題

### 問題 1: Metrics 為 0

**原因**：可能是：
- Ollama 沒有運行
- 沒有活躍連接
- 監控邏輯有問題

**解決**：
- 確認 Ollama 在 11434 端口運行
- 發送一個測試請求到 Ollama
- 檢查連接數是否增加

### 問題 2: 只有部分節點有數據

**原因**：可能是：
- 某些節點的 exporter 未運行
- 網絡連接問題
- Prometheus 配置不完整

**解決**：
- 檢查所有節點的 exporter 狀態
- 檢查 Prometheus targets 狀態
- 確認所有節點的 `.env` 配置正確

### 問題 3: Dashboard 查詢返回 "No data"

**原因**：可能是：
- Prometheus 數據源配置錯誤
- 查詢語法錯誤
- 時間範圍內沒有數據

**解決**：
- 在 Prometheus UI 中測試相同查詢
- 檢查查詢語法
- 調整時間範圍

## 調試命令

```bash
# 1. 檢查 exporter metrics
curl http://localhost:9101/metrics | grep ollama

# 2. 檢查 Prometheus targets
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="ollama-exporter")'

# 3. 在 Prometheus 中查詢
curl 'http://localhost:9090/api/v1/query?query=ollama_connections'

# 4. 檢查網絡連接
netstat -an | grep 9101
netstat -an | grep 11434
```

## 驗證步驟

1. ✅ Exporter 運行並返回 metrics
2. ✅ Prometheus 可以抓取所有 targets
3. ✅ Prometheus 查詢返回數據
4. ✅ Grafana 數據源連接成功
5. ✅ Dashboard 查詢語法正確
6. ✅ 時間範圍內有數據

如果以上都確認無誤，但 Dashboard 仍然沒有數據，請檢查：
- Grafana 版本是否支持這些查詢
- Dashboard JSON 是否正確導入
- 是否有權限問題

