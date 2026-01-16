# PM2 部署指南

## 概述

PM2 是一个 Node.js 进程管理器，可以用来管理 Python 应用。本指南介绍如何使用 PM2 部署 Ollama Gateway 和 Exporter。

## 安装 PM2

```bash
npm install -g pm2
```

## 配置文件

项目根目录提供了 `ecosystem.config.js` 配置文件，可以直接使用：

```bash
pm2 start ecosystem.config.js
```

## 手动配置

### Gateway 配置

```javascript
{
  name: 'ollama-gateway',
  script: 'src/ollama_gateway.py',
  interpreter: 'python3',
  cwd: '/Users/jamesshieh/projects/ollama-metrics-exporter',
  watch: ['src', 'config'],
  ignore_watch: ['__pycache__', '*.log', 'data', 'backups'],
  autorestart: true,
  env: {
    GATEWAY_PORT: '11435',
    SCHEDULING_STRATEGY: 'round_robin',
    // 配置文件路径（可选，默认使用 config/node_config.json）
    // 如果设置为旧路径 "node_config.json"，会自动转换为 "config/node_config.json"
    // NODE_CONFIG_FILE: 'config/node_config.json'
  }
}
```

### Exporter 配置

```javascript
{
  name: 'ollama-exporter',
  script: 'src/ollama_exporter.py',
  interpreter: 'python3',
  cwd: '/Users/jamesshieh/projects/ollama-metrics-exporter',
  watch: ['src'],
  ignore_watch: ['__pycache__', '*.log', 'data', 'backups'],
  autorestart: true,
  env: {
    NODE_NAME: 'node1',
    OLLAMA_PORT: '11434',
  }
}
```

## 常用命令

### 启动服务

```bash
# 使用配置文件启动
pm2 start ecosystem.config.js

# 启动单个应用
pm2 start src/ollama_gateway.py --name ollama-gateway --interpreter python3

# 启动并设置环境变量
pm2 start src/ollama_gateway.py --name ollama-gateway --interpreter python3 --env NODE_CONFIG_FILE=config/node_config.json
```

### 查看状态

```bash
# 查看所有进程
pm2 list

# 查看详细信息
pm2 show ollama-gateway

# 查看日志
pm2 logs ollama-gateway
pm2 logs ollama-exporter

# 查看实时日志
pm2 logs --lines 100
```

### 管理服务

```bash
# 重启服务
pm2 restart ollama-gateway

# 停止服务
pm2 stop ollama-gateway

# 删除服务
pm2 delete ollama-gateway

# 重载服务（零停机时间）
pm2 reload ollama-gateway
```

### 保存和恢复

```bash
# 保存当前进程列表
pm2 save

# 设置开机自启
pm2 startup

# 恢复保存的进程列表
pm2 resurrect
```

## 配置文件路径说明

### 自动路径转换

代码会自动处理配置文件路径：

1. **如果环境变量未设置**：默认使用 `config/node_config.json`
2. **如果环境变量设置为 `node_config.json`**：自动转换为 `config/node_config.json`（向后兼容）
3. **如果环境变量设置为相对路径**：相对于项目根目录解析
4. **如果环境变量设置为绝对路径**：直接使用

### 示例

```javascript
// 方式1: 不设置环境变量（推荐）
// 自动使用 config/node_config.json

// 方式2: 明确指定新路径
env: {
  NODE_CONFIG_FILE: 'config/node_config.json'
}

// 方式3: 使用旧路径（会自动转换）
env: {
  NODE_CONFIG_FILE: 'node_config.json'  // 自动转换为 config/node_config.json
}

// 方式4: 使用绝对路径
env: {
  NODE_CONFIG_FILE: '/absolute/path/to/config.json'
}
```

## 监控和日志

### 查看实时监控

```bash
pm2 monit
```

### 日志管理

```bash
# 清空日志
pm2 flush

# 查看特定应用的日志
pm2 logs ollama-gateway --lines 50

# 查看错误日志
pm2 logs ollama-gateway --err
```

### 性能监控

```bash
# 查看进程信息
pm2 describe ollama-gateway

# 查看资源使用
pm2 monit
```

## 故障排除

### 配置文件找不到

如果看到错误：
```
⚠️  Warning: Config file node_config.json not found
```

**解决方案**：
1. 确保配置文件在 `config/node_config.json`
2. 或者设置环境变量 `NODE_CONFIG_FILE=config/node_config.json`
3. 代码会自动处理旧路径 `node_config.json`，但建议更新为新路径

### 检查配置路径

代码启动时会打印配置路径信息：
```
🔧 PROJECT_ROOT: /path/to/project
🔧 CONFIG_FILE: /path/to/project/config/node_config.json
🔧 Config file exists: True
```

### 重启服务

如果修改了配置文件，需要重启服务：

```bash
pm2 restart ollama-gateway
```

或者使用 watch 模式（已在配置中启用），修改文件后会自动重启。

## 最佳实践

1. **使用配置文件**：使用 `ecosystem.config.js` 统一管理配置
2. **设置日志目录**：将日志输出到 `logs/` 目录
3. **启用 watch 模式**：开发时启用，生产环境可关闭
4. **设置开机自启**：使用 `pm2 startup` 和 `pm2 save`
5. **监控资源**：定期使用 `pm2 monit` 检查资源使用情况

## 多节点部署

如果有多个节点，可以为每个节点创建不同的 PM2 配置：

```javascript
{
  name: 'ollama-exporter-node1',
  script: 'src/ollama_exporter.py',
  interpreter: 'python3',
  env: {
    NODE_NAME: 'node1',
    OLLAMA_PORT: '11434',
  }
},
{
  name: 'ollama-exporter-node2',
  script: 'src/ollama_exporter.py',
  interpreter: 'python3',
  env: {
    NODE_NAME: 'node2',
    OLLAMA_PORT: '11434',
  }
}
```
