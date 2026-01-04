# Node2/Node3/Node4 顯示 "No data" 問題排查

## 問題描述

Dashboard 中 Node2、Node3、Node4 顯示 "No data"，而 Node1 正常顯示數據。

## 可能的原因

### 1. Prometheus 沒有抓取到這些節點的數據

**檢查方法**：
1. 訪問 Prometheus UI（通常是 `http://localhost:9090`）
2. 進入 **Status** → **Targets**
3. 檢查所有 `ollama-exporter` targets 的狀態
4. 確認 node2、node3、node4 的 targets 都是 **UP** 狀態

**解決方法**：
如果 targets 是 **DOWN** 狀態：
- 檢查這些節點的 exporter 是否運行
- 檢查網絡連接
- 檢查防火牆設置

### 2. Exporter 沒有運行

**檢查方法**：
```bash
# 檢查 node2
curl http://192.168.50.31:9101/metrics | grep ollama_connections

# 檢查 node3
curl http://192.168.50.94:9101/metrics | grep ollama_connections

# 檢查 node4
curl http://192.168.50.155:9101/metrics | grep ollama_connections
```

**解決方法**：
如果無法連接，需要在這些節點上啟動 exporter：
```bash
# 在每個節點上
cd /path/to/ollama-metrics-exporter
python3 ollama_exporter.py
```

### 3. NODE_NAME 配置不正確

**檢查方法**：
確認每個節點的 `.env` 文件中的 `NODE_NAME` 設置正確：

```env
# node2 的 .env
NODE_NAME=node2

# node3 的 .env
NODE_NAME=node3

# node4 的 .env
NODE_NAME=node4
```

**解決方法**：
如果配置不正確，修改 `.env` 文件並重啟 exporter。

### 4. Prometheus 配置問題

**檢查方法**：
確認 `prometheus.yml` 包含所有節點：

```yaml
scrape_configs:
  - job_name: 'ollama-exporter'
    static_configs:
      - targets:
        - '192.168.50.158:9101'  # node1
        - '192.168.50.31:9101'   # node2
        - '192.168.50.94:9101'   # node3
        - '192.168.50.155:9101'  # node4
```

**解決方法**：
如果配置不完整，添加缺失的節點並重啟 Prometheus。

### 5. 時間範圍問題

**檢查方法**：
在 Grafana Dashboard 中：
1. 檢查右上角的時間範圍
2. 如果選擇了 "Last 1 hour"，但 exporter 剛啟動，可能沒有歷史數據

**解決方法**：
1. 選擇更短的時間範圍（如 "Last 5 minutes"）
2. 或者等待一段時間讓數據累積

### 6. 查詢語法問題

**已修復**：Dashboard 查詢已更新，使用 `or vector(0)` 來處理沒有數據的情況，這樣會顯示 0 而不是 "No data"。

## 快速診斷步驟

1. **檢查 Prometheus Targets**：
   ```bash
   # 訪問 Prometheus UI
   http://localhost:9090/targets
   ```

2. **檢查 Exporter 是否運行**：
   ```bash
   # 測試每個節點
   curl http://192.168.50.31:9101/metrics  # node2
   curl http://192.168.50.94:9101/metrics  # node3
   curl http://192.168.50.155:9101/metrics # node4
   ```

3. **在 Prometheus 中測試查詢**：
   ```promql
   # 測試 node2
   ollama_connections{node="node2"}
   
   # 測試 node3
   ollama_connections{node="node3"}
   
   # 測試 node4
   ollama_connections{node="node4"}
   ```

4. **檢查時間範圍**：
   - 在 Grafana 中選擇 "Last 15 minutes" 或更短

## 已完成的修復

1. **更新查詢語法**：所有節點的查詢都添加了 `or vector(0)`，這樣即使沒有數據也會顯示 0 而不是 "No data"

## 驗證步驟

修復後，應該看到：
- ✅ Node1 顯示連接數（可能是 0）
- ✅ Node2 顯示連接數（可能是 0，而不是 "No data"）
- ✅ Node3 顯示連接數（可能是 0，而不是 "No data"）
- ✅ Node4 顯示連接數（可能是 0，而不是 "No data"）

如果仍然顯示 "No data"，問題在 Prometheus 配置或 exporter 運行狀態。

