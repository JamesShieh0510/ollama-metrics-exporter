# 3D 拓扑图使用说明

## 🎨 功能特点

- **3D 可视化**：使用 Three.js 创建的炫酷 3D 网络拓扑图
- **实时更新**：每 2 秒自动从 exporter 获取最新数据
- **交互式控制**：支持鼠标拖拽、缩放、旋转视角
- **动态效果**：节点大小和颜色根据连接数和流量动态变化
- **连接线动画**：连接线根据流量强度显示不同的颜色和透明度

## 🚀 快速开始

### 方法 1：直接打开 HTML 文件

1. 确保至少有一个 exporter 正在运行（`python ollama_exporter.py`）
2. 直接用浏览器打开 `topology-3d.html` 文件

**注意**：由于浏览器的 CORS（跨域资源共享）安全策略，如果 exporter 运行在不同的端口或域名，可能会遇到跨域问题。

### 方法 2：使用本地服务器（推荐）

为了避免 CORS 问题，建议使用本地服务器：

#### Python 3
```bash
# 在项目目录下运行
python3 -m http.server 8000
# 然后在浏览器打开 http://localhost:8000/topology-3d.html
```

#### Node.js
```bash
# 安装 http-server（如果还没有）
npm install -g http-server

# 在项目目录下运行
http-server -p 8000
# 然后在浏览器打开 http://localhost:8000/topology-3d.html
```

#### VS Code
- 安装 "Live Server" 扩展
- 右键点击 `topology-3d.html`，选择 "Open with Live Server"

## ⚙️ 配置

### 修改 Exporter URL

编辑 `topology-3d.html` 文件，找到 `CONFIG` 对象：

```javascript
const CONFIG = {
    exporterUrls: {
        node1: 'http://192.168.50.158:9101/metrics',
        node2: 'http://192.168.50.31:9101/metrics',
        node3: 'http://192.168.50.94:9101/metrics',
        node4: 'http://192.168.50.155:9101/metrics',
        router: null // router 是虚拟节点
    },
    updateInterval: 2000, // 更新间隔（毫秒）
    // ...
};
```

### 单节点模式

如果只想显示本地节点，可以修改为：

```javascript
const CONFIG = {
    exporterUrl: 'http://localhost:9101/metrics',
    updateInterval: 2000,
    // ...
};
```

## 🎮 控制说明

- **鼠标左键拖拽**：旋转视角
- **鼠标滚轮**：缩放
- **鼠标右键拖拽**：平移视角
- **重置视角按钮**：恢复默认视角
- **自动旋转按钮**：开启/关闭自动旋转
- **线框模式按钮**：切换节点显示模式

## 🎨 可视化说明

### 节点颜色
- **蓝色**：Router（中心节点）
- **绿色**：活跃的 Node（有连接）
- **灰色**：空闲的 Node（无连接）

### 节点大小
- 节点大小根据连接数动态变化
- 连接数越多，节点越大

### 连接线
- **黄色线条**：表示节点到 router 的连接
- **线条粗细和颜色**：根据流量强度变化
- **脉冲动画**：有流量时线条会闪烁

## 🔧 解决 CORS 问题

如果遇到 CORS 错误，有以下几种解决方案：

### 方案 1：配置 Exporter 允许 CORS

修改 `ollama_exporter.py`，添加 CORS 支持：

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应该限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 方案 2：使用代理服务器

创建一个简单的代理服务器来转发请求。

### 方案 3：使用浏览器扩展

安装 CORS 相关的浏览器扩展（仅用于开发测试）。

## 📊 数据说明

拓扑图显示以下信息：

- **连接数**：当前 ESTABLISHED 状态的连接数
- **发送速率**：每秒发送的字节数
- **接收速率**：每秒接收的字节数
- **总流量**：发送 + 接收的总速率

## 🐛 故障排除

### 问题：显示"连接失败"

**可能原因**：
1. Exporter 没有运行
2. URL 配置错误
3. CORS 限制

**解决方法**：
1. 检查 exporter 是否运行：`curl http://localhost:9101/metrics`
2. 检查 URL 配置是否正确
3. 使用本地服务器打开 HTML 文件

### 问题：显示模拟数据

**原因**：无法连接到任何 exporter（通常是 CORS 问题）

**解决方法**：
1. 使用本地服务器打开 HTML 文件
2. 配置 exporter 允许 CORS
3. 检查网络连接和防火墙设置

### 问题：节点不显示

**可能原因**：
1. 数据解析错误
2. 节点名称不匹配

**解决方法**：
1. 打开浏览器开发者工具（F12）查看控制台错误
2. 检查 exporter 返回的 metrics 格式
3. 确认节点名称与配置一致

## 📝 注意事项

1. **性能**：如果节点很多，可能会影响性能，建议调整 `updateInterval`
2. **浏览器兼容性**：需要支持 WebGL 的现代浏览器
3. **网络**：确保能够访问所有 exporter 的 URL
4. **安全**：生产环境应该限制 CORS 允许的域名

## 🎯 下一步

- 添加更多节点类型和连接关系
- 支持自定义节点位置
- 添加历史数据趋势图
- 支持导出截图或视频

