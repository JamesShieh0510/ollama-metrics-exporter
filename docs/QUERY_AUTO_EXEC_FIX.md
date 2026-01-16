# 查詢無法自動執行的問題解決方案

## 問題描述

即使 Dashboard 刷新設置為 10s，URL 中也有 `refresh=10s`，但查詢不會自動執行，必須手動點擊 "Run queries" 才能顯示數據。

## 已完成的修復

1. **為所有查詢添加格式配置**：
   - `"format": "time_series"` - 確保查詢返回時間序列格式
   - `"instant": false` - 確保查詢是範圍查詢而不是即時查詢

2. **查詢間隔設置**：
   - 已為部分查詢添加 `"intervalMs": 10000`

## 可能的原因和解決方案

### 1. Grafana 查詢緩存問題

**解決方法**：
1. 在面板編輯器中，點擊 **Query** 標籤
2. 找到 **Query options**
3. 設置 **Cache time** 為 `0` 或較短的時間（如 `5s`）
4. 設置 **Min interval** 為 `10s` 或更短

### 2. Prometheus 數據源設置

**檢查步驟**：
1. **Configuration** → **Data Sources** → 選擇 Prometheus
2. 檢查以下設置：
   - **Query timeout**: 設置為 `60s` 或更長
   - **HTTP Method**: 建議使用 `POST`
   - **Scrape interval**: 確認設置正確
3. 點擊 **Save & Test**

### 3. 瀏覽器開發者工具檢查

**診斷步驟**：
1. 打開瀏覽器開發者工具（F12）
2. 切換到 **Network** 標籤
3. 過濾 `prometheus` 或 `api/datasources/proxy`
4. 觀察是否有查詢請求發送
5. 如果沒有請求，說明查詢沒有自動執行
6. 如果有請求但返回錯誤，檢查錯誤訊息

### 4. 檢查查詢執行狀態

**在 Grafana 中**：
1. 點擊面板標題 → **Edit**
2. 點擊 **Query inspector**（查詢框下方的按鈕）
3. 查看 **Request** 和 **Response** 標籤
4. 確認查詢是否正確執行
5. 檢查是否有錯誤訊息

### 5. 檢查時間範圍

**可能問題**：
- 如果時間範圍選擇了 "Last 1 hour"，但數據只有最近幾分鐘，可能顯示為 "No data"

**解決方法**：
1. 選擇更短的時間範圍（如 "Last 15 minutes"）
2. 或選擇 "Last 5 minutes"

### 6. 強制重新加載 Dashboard

**方法 1**：
1. 按 `Ctrl+Shift+R` (Windows/Linux) 或 `Cmd+Shift+R` (Mac) 強制刷新
2. 清除瀏覽器緩存

**方法 2**：
1. 刪除現有的 Dashboard
2. 重新導入更新後的 `grafana-dashboard.json`
3. 確認所有查詢配置正確

### 7. 檢查 Grafana 版本

某些 Grafana 版本可能有自動查詢執行的 bug：

**檢查方法**：
1. 點擊用戶頭像 → **Help** → **About**
2. 查看 Grafana 版本
3. 如果是舊版本（< 8.0），考慮升級

### 8. 檢查面板級別的設置

**在面板編輯器中**：
1. 點擊 **Panel options**（齒輪圖標）
2. 檢查是否有設置阻止自動刷新
3. 確認 **Data links** 或其他設置沒有問題

## 驗證步驟

修復後應該：
1. ✅ 打開瀏覽器開發者工具 → **Network** 標籤
2. ✅ 每 10 秒看到查詢請求發送到 Prometheus
3. ✅ 查詢請求返回 200 狀態碼
4. ✅ 數據自動更新，不需要手動點擊 "Run queries"

## 調試命令

在瀏覽器控制台中運行以下命令來檢查 Dashboard 狀態：

```javascript
// 檢查 Dashboard 刷新設置
console.log(window.grafanaBootData.settings);

// 檢查當前 Dashboard 配置
// 需要在 Dashboard 頁面中運行
```

## 如果問題仍然存在

請提供以下信息：
1. **瀏覽器開發者工具截圖**：
   - Network 標籤（顯示是否有查詢請求）
   - Console 標籤（顯示是否有錯誤）

2. **Grafana 版本**：
   - 點擊用戶頭像 → **Help** → **About**

3. **查詢 Inspector 截圖**：
   - 點擊面板 → **Edit** → **Query inspector**
   - 截圖 Request 和 Response 標籤

4. **Prometheus 數據源配置**：
   - 截圖 Prometheus 數據源設置頁面

## 臨時解決方案

如果自動查詢執行無法修復：

1. **使用瀏覽器擴展**：
   - 安裝自動刷新擴展
   - 設置每 10 秒刷新頁面

2. **使用 Grafana API**：
   - 通過 API 定期查詢數據
   - 或使用外部工具監控

3. **手動刷新**：
   - 雖然不方便，但可以暫時使用
   - 或設置更長的刷新間隔（如 30s）

