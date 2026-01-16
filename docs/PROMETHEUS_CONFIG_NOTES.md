# Prometheus 配置說明

## 配置分析

你的 Prometheus 配置看起來正確，所有節點都已配置。配置要點：

### 1. 標籤設置

你在 `static_configs` 中為每個 target 添加了 `node` 標籤：

```yaml
static_configs:
  - targets:
    - 192.168.50.158:9101
    labels:
      node: node1
```

**注意**：
- Exporter 本身也會設置 `node` 標籤（通過 `NODE_NAME` 環境變數）
- Prometheus 的 `labels` 會添加到所有 metrics 上
- 如果兩個地方都設置了 `node` 標籤，**metrics 中的標籤優先級更高**
- 這意味著 Prometheus 的 `labels` 中的 `node` 標籤會被忽略

**建議**：
- 保持現有配置即可（兩個地方都設置 `node` 標籤不會有問題）
- 或者移除 Prometheus 配置中的 `labels`，只依賴 exporter 設置的標籤

### 2. 抓取間隔

```yaml
scrape_interval: 15s
scrape_timeout: 10s
```

這意味著 Prometheus 每 15 秒抓取一次數據。如果 Grafana Dashboard 刷新間隔設置為 10s，可能會在 Prometheus 還沒抓取新數據時就查詢，導致顯示舊數據或 "No data"。

**建議**：
- 將 Dashboard 刷新間隔設置為 `15s` 或更長（與 Prometheus scrape_interval 一致）
- 或者將 Prometheus scrape_interval 改為 `10s` 或更短

### 3. 查詢無法自動執行的可能原因

如果查詢無法自動執行，可能的原因：

#### A. 查詢緩存問題

**解決方法**：
1. 在 Grafana 面板編輯器中
2. 點擊 **Query** 標籤
3. 找到 **Query options**
4. 設置 **Cache time** 為 `0` 或 `5s`

#### B. Prometheus 數據源設置

**檢查**：
1. **Configuration** → **Data Sources** → Prometheus
2. 確認 **Query timeout** 設置為 `60s` 或更長
3. 確認 **HTTP Method** 設置為 `POST`（推薦）

#### C. 時間範圍問題

如果時間範圍選擇了 "Last 1 hour"，但 Prometheus 剛啟動或數據只有最近幾分鐘，可能顯示為 "No data"。

**解決方法**：
- 選擇更短的時間範圍（如 "Last 15 minutes"）

#### D. Grafana 版本問題

某些 Grafana 版本可能有自動查詢執行的 bug。

**檢查方法**：
- 點擊用戶頭像 → **Help** → **About**
- 查看 Grafana 版本
- 如果是舊版本（< 8.0），考慮升級

## 驗證配置

### 1. 檢查 Prometheus Targets

訪問 `http://localhost:9090/targets`，確認所有 targets 都是 **UP** 狀態。

### 2. 在 Prometheus 中測試查詢

訪問 `http://localhost:9090`，在查詢框中輸入：

```promql
# 測試所有節點
ollama_connections

# 測試特定節點
ollama_connections{node="node1"}
ollama_connections{node="node2"}
ollama_connections{node="node3"}
ollama_connections{node="node4"}
```

如果 Prometheus 中有數據但 Grafana 沒有，問題在 Grafana 配置。

### 3. 檢查標籤

在 Prometheus 中查詢：

```promql
# 查看所有標籤
{__name__="ollama_connections"}

# 查看 node 標籤的值
{__name__="ollama_connections", node="node1"}
```

確認 `node` 標籤的值正確。

## 建議的配置調整

### 選項 1：移除 Prometheus labels（推薦）

如果 exporter 已經正確設置了 `node` 標籤，可以移除 Prometheus 配置中的 `labels`：

```yaml
static_configs:
  - targets:
    - 192.168.50.158:9101
    - 192.168.50.31:9101
    - 192.168.50.94:9101
    - 192.168.50.155:9101
```

這樣可以避免標籤衝突，只使用 exporter 設置的標籤。

### 選項 2：保持現有配置

如果兩個地方都設置了 `node` 標籤，也沒問題，因為 metrics 中的標籤優先級更高。

### 選項 3：調整刷新間隔

將 Dashboard 刷新間隔改為 `15s`，與 Prometheus scrape_interval 一致：

```json
"refresh": "15s"
```

## 關於查詢無法自動執行的問題

如果刷新間隔已設置，但查詢仍然無法自動執行，請檢查：

1. **瀏覽器開發者工具**：
   - 打開 Network 標籤
   - 過濾 `prometheus` 或 `api/datasources/proxy`
   - 觀察是否有查詢請求發送

2. **查詢選項**：
   - 在面板編輯器中設置 **Min interval** 為 `10s` 或更短
   - 設置 **Cache time** 為 `0`

3. **Grafana 日誌**：
   - 檢查 Grafana 服務器日誌
   - 查看是否有錯誤訊息

