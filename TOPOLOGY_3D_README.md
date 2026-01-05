# 3D 拓撲圖使用說明

## 🎨 功能特點

- **3D 可視化**：使用 Three.js 創建的炫酷 3D 網絡拓撲圖
- **實時更新**：每 2 秒自動從 exporter 獲取最新數據
- **交互式控制**：支持鼠標拖拽、縮放、旋轉視角
- **動態效果**：節點大小和顏色根據連接數和流量動態變化
- **連接線動畫**：連接線根據流量強度顯示不同的顏色和透明度

## 🚀 快速開始

### 方法 1：直接打開 HTML 文件

1. 確保至少有一個 exporter 正在運行（`python ollama_exporter.py`）
2. 直接用瀏覽器打開 `topology-3d.html` 文件

**注意**：由於瀏覽器的 CORS（跨域資源共享）安全策略，如果 exporter 運行在不同的端口或域名，可能會遇到跨域問題。

### 方法 2：使用本地服務器（推薦）

為了避免 CORS 問題，建議使用本地服務器：

#### Python 3
```bash
# 在項目目錄下運行
python3 -m http.server 8000
# 然後在瀏覽器打開 http://localhost:8000/topology-3d.html
```

#### Node.js
```bash
# 安裝 http-server（如果還沒有）
npm install -g http-server

# 在項目目錄下運行
http-server -p 8000
# 然後在瀏覽器打開 http://localhost:8000/topology-3d.html
```

#### VS Code
- 安裝 "Live Server" 擴展
- 右鍵點擊 `topology-3d.html`，選擇 "Open with Live Server"

## ⚙️ 配置

### 修改 Exporter URL

編輯 `topology-3d.html` 文件，找到 `CONFIG` 對象：

```javascript
const CONFIG = {
    exporterUrls: {
        node1: 'http://192.168.50.158:9101/metrics',
        node2: 'http://192.168.50.31:9101/metrics',
        node3: 'http://192.168.50.94:9101/metrics',
        node4: 'http://192.168.50.155:9101/metrics',
        router: null // router 是虛擬節點
    },
    updateInterval: 2000, // 更新間隔（毫秒）
    // ...
};
```

### 單節點模式

如果只想顯示本地節點，可以修改為：

```javascript
const CONFIG = {
    exporterUrl: 'http://localhost:9101/metrics',
    updateInterval: 2000,
    // ...
};
```

## 🎮 控制說明

- **鼠標左鍵拖拽**：旋轉視角
- **鼠標滾輪**：縮放
- **鼠標右鍵拖拽**：平移視角
- **重置視角按鈕**：恢覆默認視角
- **自動旋轉按鈕**：開啟/關閉自動旋轉
- **線框模式按鈕**：切換節點顯示模式

## 🎨 可視化說明

### 節點顏色
- **藍色**：Router（中心節點）
- **綠色**：活躍的 Node（有連接）
- **灰色**：空閒的 Node（無連接）

### 節點大小
- 節點大小根據連接數動態變化
- 連接數越多，節點越大

### 連接線
- **黃色線條**：表示節點到 router 的連接
- **線條粗細和顏色**：根據流量強度變化
- **脈沖動畫**：有流量時線條會閃爍

## 🔧 解決 CORS 問題

如果遇到 CORS 錯誤，有以下幾種解決方案：

### 方案 1：配置 Exporter 允許 CORS

修改 `ollama_exporter.py`，添加 CORS 支持：

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生產環境應該限制具體域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 方案 2：使用代理服務器

創建一個簡單的代理服務器來轉發請求。

### 方案 3：使用瀏覽器擴展

安裝 CORS 相關的瀏覽器擴展（僅用於開發測試）。

## 📊 數據說明

拓撲圖顯示以下信息：

- **連接數**：當前 ESTABLISHED 狀態的連接數
- **發送速率**：每秒發送的字節數
- **接收速率**：每秒接收的字節數
- **總流量**：發送 + 接收的總速率

## 🐛 故障排除

### 問題：顯示"連接失敗"

**可能原因**：
1. Exporter 沒有運行
2. URL 配置錯誤
3. CORS 限制

**解決方法**：
1. 檢查 exporter 是否運行：`curl http://localhost:9101/metrics`
2. 檢查 URL 配置是否正確
3. 使用本地服務器打開 HTML 文件

### 問題：顯示模擬數據

**原因**：無法連接到任何 exporter（通常是 CORS 問題）

**解決方法**：
1. 使用本地服務器打開 HTML 文件
2. 配置 exporter 允許 CORS
3. 檢查網絡連接和防火墻設置

### 問題：節點不顯示

**可能原因**：
1. 數據解析錯誤
2. 節點名稱不匹配

**解決方法**：
1. 打開瀏覽器開發者工具（F12）查看控制台錯誤
2. 檢查 exporter 返回的 metrics 格式
3. 確認節點名稱與配置一致

## 📝 注意事項

1. **性能**：如果節點很多，可能會影響性能，建議調整 `updateInterval`
2. **瀏覽器兼容性**：需要支持 WebGL 的現代瀏覽器
3. **網絡**：確保能夠訪問所有 exporter 的 URL
4. **安全**：生產環境應該限制 CORS 允許的域名

## 🎯 下一步

- 添加更多節點類型和連接關系
- 支持自定義節點位置
- 添加歷史數據趨勢圖
- 支持導出截圖或視頻

