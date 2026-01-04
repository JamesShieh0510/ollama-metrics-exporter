# Dashboard 數據顯示問題修復指南

## 問題分析

根據你提供的 Prometheus 查詢結果，數據確實存在：
```
ollama_connections{node="node4", state="ESTABLISHED"} 3
ollama_connections{node="node4", state="LISTEN"} 2
```

但 Dashboard 沒有顯示數據，可能的原因：

## 解決方案

### 1. 檢查時間範圍

**最重要**：確認 Dashboard 的時間範圍設置正確：

1. 點擊 Dashboard 右上角的時間選擇器
2. 選擇 **"Last 15 minutes"** 或 **"Last 5 minutes"**
3. 如果 exporter 剛啟動，選擇更短的時間範圍

**已更新**：Dashboard 預設時間範圍已改為 "Last 15 minutes"

### 2. 手動刷新 Dashboard

1. 點擊右上角的 **刷新按鈕**（圓形箭頭圖標）
2. 或按 `Ctrl+R` / `Cmd+R` 刷新頁面

### 3. 檢查查詢結果

在 Grafana 中：

1. 點擊任意面板的標題
2. 選擇 **"Edit"**
3. 點擊 **"Query inspector"** 按鈕（在查詢框下方）
4. 查看 **"Data"** 標籤，確認是否有數據返回

### 4. 測試簡單查詢

在 Grafana 中創建一個測試面板：

1. 點擊 **"Add"** → **"Visualization"**
2. 選擇 **"Time series"**
3. 在查詢框中輸入：
   ```promql
   ollama_connections{node="node4"}
   ```
4. 確認時間範圍為 **"Last 15 minutes"**
5. 點擊 **"Run query"**

如果這個簡單查詢有數據，說明問題在 Dashboard 配置。

### 5. 檢查 Legend Format

確認 Legend Format 正確：
- `{{node}} - Established` 應該顯示為 `node4 - Established`
- 如果顯示為空或錯誤，檢查 label 名稱

### 6. 重新導入 Dashboard

如果以上都不行，嘗試重新導入：

1. 刪除現有的 Dashboard
2. 重新導入 `grafana-dashboard.json`
3. 確認選擇正確的 Prometheus 數據源
4. 設置時間範圍為 **"Last 15 minutes"**

### 7. 檢查 Prometheus 數據源

確認 Prometheus 數據源配置：

1. **Configuration** → **Data Sources**
2. 選擇 Prometheus 數據源
3. 點擊 **"Test"** 確認連接成功
4. 確認 **URL** 正確（例如：`http://localhost:9090`）

### 8. 驗證查詢語法

在 Prometheus UI 中測試相同的查詢：

訪問 `http://localhost:9090`，在查詢框中輸入：

```promql
# 測試總連接數
ollama_connections{state="ESTABLISHED"}

# 測試特定節點
ollama_connections{node="node4", state="ESTABLISHED"}

# 測試流量
ollama_bytes_sent_total
ollama_bytes_recv_total
```

如果 Prometheus 中有數據但 Grafana 沒有，問題在 Grafana 配置。

## 快速檢查清單

- [ ] 時間範圍設置為 "Last 15 minutes" 或更短
- [ ] 點擊了刷新按鈕
- [ ] 在 Query Inspector 中確認有數據返回
- [ ] Prometheus 數據源連接正常
- [ ] 在 Prometheus UI 中查詢有結果
- [ ] Dashboard 已重新導入（如果需要）

## 常見問題

### Q: 為什麼 node2 和 node3 都是 0？

A: 這可能是正常的，如果這些節點：
- 沒有運行 Ollama
- 沒有活躍連接
- Exporter 剛啟動，還沒有監控到連接

### Q: 為什麼 node4 有 2 個 LISTEN？

A: 這可能表示：
- Ollama 進程監聽多個端口
- 或者有多個 Ollama 實例運行

### Q: 流量數據為什麼是 0？

A: 流量是基於連接數估算的，如果：
- 連接數為 0，流量也會是 0
- 或者估算邏輯還沒有觸發

## 調試步驟

1. **確認數據存在**：✅ 已完成（你提供的查詢結果顯示有數據）

2. **檢查時間範圍**：
   ```bash
   # 在 Grafana 中設置為 "Last 15 minutes"
   ```

3. **測試簡單查詢**：
   - 創建新面板
   - 查詢：`ollama_connections{node="node4"}`
   - 確認有數據

4. **檢查 Dashboard 查詢**：
   - 編輯面板
   - 查看 Query Inspector
   - 確認查詢返回數據

如果以上步驟都確認無誤，但 Dashboard 仍然沒有數據，請提供：
- Grafana 版本
- Query Inspector 的截圖
- 任何錯誤訊息

