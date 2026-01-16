# Dashboard 首次載入查詢不執行的問題解決方案

## 問題描述

Dashboard 首次載入時查詢不會自動執行，需要進入每個面板的編輯視圖手動按刷新，之後才能自動更新。

## 問題分析

這個問題通常是由於：
1. **Dashboard 首次載入時查詢沒有初始化**
2. **查詢配置缺少必要的選項**
3. **Grafana 的查詢執行機制需要明確的配置**

## 已完成的修復

1. **為所有面板添加 `maxDataPoints`**：
   - 設置為 `1000`，確保查詢有明確的數據點限制
   - 這有助於 Grafana 正確初始化查詢

2. **為所有查詢添加格式配置**：
   - `"format": "time_series"` - 明確查詢格式
   - `"instant": false` - 確保是範圍查詢

3. **調整刷新間隔**：
   - 設置為 `15s`，與 Prometheus scrape_interval 一致

## 解決方案

### 1. 重新導入 Dashboard（推薦）

1. 刪除現有的 Dashboard
2. 重新導入更新後的 `grafana-dashboard.json`
3. 確認所有配置正確

### 2. 檢查查詢選項

在面板編輯器中：
1. 點擊面板標題 → **Edit**
2. 點擊 **Query** 標籤
3. 找到 **Query options**（在查詢框下方）
4. 確認設置：
   - **Min interval**: `15s` 或更短
   - **Max data points**: `1000`
   - **Cache time**: `0` 或 `5s`

### 3. 強制初始化查詢

**方法 1：通過 URL 參數**
在 Dashboard URL 後添加 `?refresh=15s&from=now-15m&to=now`：
```
http://your-grafana:3000/d/ollama-metrics?refresh=15s&from=now-15m&to=now
```

**方法 2：手動觸發一次**
1. 進入任意面板的編輯視圖
2. 點擊 **Run queries**
3. 返回 Dashboard 視圖
4. 之後應該能自動更新

### 4. 檢查瀏覽器控制台

打開瀏覽器開發者工具（F12）：
1. 切換到 **Console** 標籤
2. 查看是否有錯誤訊息
3. 切換到 **Network** 標籤
4. 過濾 `prometheus` 或 `api/datasources/proxy`
5. 觀察 Dashboard 載入時是否有查詢請求

### 5. 檢查 Grafana 版本

某些 Grafana 版本可能有首次載入查詢不執行的 bug：

**檢查方法**：
1. 點擊用戶頭像 → **Help** → **About**
2. 查看 Grafana 版本
3. 如果是舊版本（< 8.0），考慮升級

## 驗證步驟

修復後應該：
1. ✅ Dashboard 首次載入時查詢自動執行
2. ✅ 不需要進入編輯視圖手動刷新
3. ✅ 數據自動顯示
4. ✅ 之後每 15 秒自動更新

## 如果問題仍然存在

### 臨時解決方案

如果首次載入仍然無法自動執行查詢，可以使用以下方法：

**方法 1：使用書籤**
創建一個帶有查詢參數的書籤：
```
http://your-grafana:3000/d/ollama-metrics?refresh=15s&from=now-15m&to=now&orgId=1
```

**方法 2：使用瀏覽器擴展**
安裝自動刷新擴展，設置頁面載入後自動刷新一次。

**方法 3：修改 Dashboard 設置**
1. 點擊 Dashboard 設置（齒輪圖標）
2. 在 **General** 標籤中
3. 找到 **Auto refresh** 設置
4. 確認設置正確

### 調試信息

如果問題仍然存在，請提供：
1. **Grafana 版本**
2. **瀏覽器類型和版本**
3. **瀏覽器控制台錯誤訊息**（F12 → Console）
4. **Network 標籤截圖**（顯示是否有查詢請求）

## 技術說明

`maxDataPoints` 設置告訴 Grafana：
- 查詢應該返回多少個數據點
- 這有助於 Grafana 正確初始化查詢
- 如果沒有設置，Grafana 可能不會在首次載入時執行查詢

這就是為什麼添加 `maxDataPoints` 可以解決首次載入查詢不執行的問題。

