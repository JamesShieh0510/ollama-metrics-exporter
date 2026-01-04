# Dashboard 自動刷新問題解決指南

## 問題描述

Dashboard 需要手動點擊 "Edit > Run queries" 才能顯示數值，無法自動刷新。

## 解決方案

### 1. 檢查 Dashboard 刷新設置

在 Dashboard 右上角：

1. 點擊 **刷新按鈕**（圓形箭頭圖標）
2. 確認刷新間隔設置為 **"10s"** 或更短
3. 如果顯示 "Off"，點擊並選擇一個刷新間隔

### 2. 檢查瀏覽器設置

某些瀏覽器擴展或設置可能會阻止自動刷新：

1. 檢查瀏覽器控制台是否有錯誤
2. 嘗試禁用瀏覽器擴展
3. 確認瀏覽器允許頁面自動刷新

### 3. 檢查 Grafana 設置

在 Grafana 設置中：

1. 進入 **Configuration** → **Preferences**
2. 確認 **"Auto refresh"** 設置正確
3. 檢查是否有全局設置阻止自動刷新

### 4. 手動設置刷新間隔

如果自動刷新不工作，可以手動設置：

1. 在 Dashboard 右上角點擊時間選擇器旁邊的刷新按鈕
2. 選擇 **"10s"** 或 **"5s"**
3. 確認刷新按鈕顯示為活動狀態（不是灰色）

### 5. 檢查查詢配置

在面板編輯器中：

1. 點擊面板標題 → **Edit**
2. 在 **Query** 標籤中，檢查：
   - **Query options** → **Min interval** 設置為 `10s` 或更短
   - **Query options** → **Max data points** 設置合理（如 `1000`）
3. 確認查詢沒有錯誤

### 6. 檢查 Prometheus 數據源

確認 Prometheus 數據源配置：

1. **Configuration** → **Data Sources** → 選擇 Prometheus
2. 確認 **Scrape interval** 設置正確
3. 點擊 **Test** 確認連接正常

### 7. 強制刷新 Dashboard

如果以上都不行，嘗試：

1. 按 `Ctrl+Shift+R` (Windows/Linux) 或 `Cmd+Shift+R` (Mac) 強制刷新頁面
2. 清除瀏覽器緩存
3. 重新導入 Dashboard

### 8. 檢查網絡連接

確認：

1. Grafana 服務器可以訪問 Prometheus
2. Prometheus 可以訪問所有 exporter
3. 沒有防火牆阻止連接

## 已更新的配置

Dashboard JSON 已更新，包含：

1. **刷新間隔**：設置為 `10s`
2. **查詢間隔**：為所有查詢添加 `intervalMs: 10000`
3. **時間選擇器**：添加了刷新間隔選項

## 驗證步驟

1. ✅ Dashboard 右上角顯示刷新間隔（如 "10s"）
2. ✅ 刷新按鈕不是灰色（表示自動刷新已啟用）
3. ✅ 數據每 10 秒自動更新
4. ✅ 不需要手動點擊 "Run queries"

## 如果問題仍然存在

如果以上方法都無法解決問題，請檢查：

1. **Grafana 版本**：某些舊版本可能有自動刷新的 bug
2. **瀏覽器兼容性**：嘗試使用不同的瀏覽器
3. **Grafana 日誌**：檢查 Grafana 服務器日誌是否有錯誤

## 臨時解決方案

如果自動刷新無法修復，可以：

1. 使用瀏覽器擴展自動刷新頁面
2. 設置瀏覽器書籤工具自動刷新
3. 使用 Grafana API 定期查詢數據

