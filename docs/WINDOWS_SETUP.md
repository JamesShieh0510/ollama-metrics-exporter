# Windows 部署指南

## 概述

本指南介绍如何在 Windows 系统上部署和运行 Ollama Metrics Exporter 和 Gateway。

## 系统要求

- Windows 10 或更高版本
- Python 3.6+
- PowerShell 5.1+（Windows 10+ 默认已安装）

## 安装 Python

1. 从 [python.org](https://www.python.org/downloads/) 下载 Python
2. 安装时勾选 "Add Python to PATH"
3. 验证安装：
   ```powershell
   python --version
   pip --version
   ```

## 安装依赖

```powershell
cd C:\path\to\ollama-metrics-exporter
pip install -r requirements.txt
```

## 运行服务

### 方式 1: 直接运行（开发/测试）

**Exporter**:
```powershell
python src\ollama_exporter.py
```

**Gateway**:
```powershell
python src\ollama_gateway.py
```

### 方式 2: 使用 PM2（推荐）

1. 安装 PM2:
   ```powershell
   npm install -g pm2
   ```

2. 启动服务:
   ```powershell
   pm2 start ecosystem.config.js
   ```

3. 查看状态:
   ```powershell
   pm2 list
   pm2 logs ollama-gateway
   pm2 logs ollama-exporter
   ```

### 方式 3: 使用 Windows 服务（生产环境）

可以使用 [NSSM (Non-Sucking Service Manager)](https://nssm.cc/) 将 Python 脚本注册为 Windows 服务。

## 权限问题解决

### ✅ 已解决：不需要管理员权限

代码已更新，**自动使用 PowerShell 或 netstat**，**不需要管理员权限**。

**工作原理**：
1. 优先使用 PowerShell 的 `Get-NetTCPConnection`（最快，不需要管理员权限）
2. 备选使用 `netstat`（Windows 默认已安装）
3. 如果 `psutil` 可用且有权限，也会尝试使用

### 验证

启动服务后，检查是否正常工作：

```powershell
# 检查 metrics
curl http://localhost:9101/metrics

# 或使用 PowerShell
Invoke-WebRequest -Uri http://localhost:9101/metrics
```

如果看到连接数指标正常更新，说明工作正常。

### 如果仍然遇到权限问题

1. **检查 PowerShell 是否可用**:
   ```powershell
   powershell -Command "Get-Command Get-NetTCPConnection"
   ```

2. **测试 PowerShell 命令**:
   ```powershell
   powershell -Command "Get-NetTCPConnection -LocalPort 11434 -ErrorAction SilentlyContinue"
   ```

3. **测试 netstat**:
   ```powershell
   netstat -an | findstr :11434
   ```

4. **如果都不行**（不推荐）:
   - 可以尝试以管理员身份运行 PowerShell
   - 但通常不需要这样做

## 配置文件

配置文件位于 `config\` 目录：

- `config\node_config.json` - 节点配置
- `config\grafana-dashboard.json` - Grafana 仪表板配置

## 环境变量

创建 `.env` 文件（可选）：

```env
# Exporter 配置
NODE_NAME=node1
OLLAMA_PORT=11434

# Gateway 配置
GATEWAY_PORT=11435
SCHEDULING_STRATEGY=round_robin
NODE_CONFIG_FILE=config\node_config.json
```

## 启动脚本

### 使用批处理文件

创建 `scripts\start_exporter.bat`:

```batch
@echo off
cd /d %~dp0\..
python src\ollama_exporter.py
pause
```

创建 `scripts\start_gateway.bat`:

```batch
@echo off
cd /d %~dp0\..
python src\ollama_gateway.py
pause
```

### 使用 PowerShell 脚本

创建 `scripts\start_exporter.ps1`:

```powershell
Set-Location $PSScriptRoot\..
python src\ollama_exporter.py
```

## 防火墙配置

如果需要在其他机器上访问，需要配置 Windows 防火墙：

```powershell
# 允许 Exporter 端口 (9101)
New-NetFirewallRule -DisplayName "Ollama Exporter" -Direction Inbound -LocalPort 9101 -Protocol TCP -Action Allow

# 允许 Gateway 端口 (11435)
New-NetFirewallRule -DisplayName "Ollama Gateway" -Direction Inbound -LocalPort 11435 -Protocol TCP -Action Allow
```

## 故障排除

### 问题：无法获取连接信息

**检查**：
1. PowerShell 是否可用
2. netstat 是否可用
3. 查看日志中的错误信息

**解决**：
```powershell
# 测试 PowerShell
powershell -Command "Get-NetTCPConnection -LocalPort 11434"

# 测试 netstat
netstat -an | findstr :11434
```

### 问题：端口被占用

**检查**：
```powershell
netstat -ano | findstr :9101
netstat -ano | findstr :11435
```

**解决**：
- 修改 `.env` 文件中的端口配置
- 或停止占用端口的进程

### 问题：PM2 无法启动

**检查**：
```powershell
pm2 --version
node --version
```

**解决**：
- 确保已安装 Node.js
- 确保 PM2 已正确安装

## 性能优化

### 使用 PowerShell（推荐）

PowerShell 的 `Get-NetTCPConnection` 比 `netstat` 更快，代码会自动优先使用。

### 禁用不必要的功能

如果不需要某些 metrics，可以注释掉相关代码以提高性能。

## 监控和日志

### 查看日志

**PM2**:
```powershell
pm2 logs ollama-exporter
pm2 logs ollama-gateway
```

**直接运行**:
日志会直接输出到控制台。

### 日志位置

如果配置了日志文件，通常位于：
- `logs\exporter-error.log`
- `logs\exporter-out.log`
- `logs\gateway-error.log`
- `logs\gateway-out.log`

## 生产环境建议

1. **使用 PM2** 或 Windows 服务管理进程
2. **配置日志轮转** 避免日志文件过大
3. **设置自动重启** 确保服务高可用
4. **监控资源使用** 定期检查 CPU 和内存
5. **配置防火墙** 只开放必要的端口

## 相关文档

- [PM2 部署指南](PM2_SETUP.md)
- [解决 root 权限问题](ROOT_PERMISSIONS_FIX.md)
- [故障排除指南](TROUBLESHOOTING.md)
