# 解决 root 权限问题

## 问题描述

`ollama_exporter.py` 使用 `psutil.net_connections()` 来监控网络连接，在某些系统上需要 root 权限才能查看所有连接。

## ✅ 已实施的解决方案

代码已经更新，**自动使用多种方法**来获取网络连接信息，**不需要 root 权限**。

### 工作原理

代码会按以下顺序尝试不同的方法：

1. **psutil**（如果可用且有权限）
   - 优先使用，性能最好
   - 如果权限不足，自动降级到其他方法

2. **lsof**（macOS/Linux）
   - 不需要 root 权限
   - macOS 和大多数 Linux 系统默认安装

3. **ss**（Linux）
   - 现代 Linux 系统的推荐工具
   - 不需要 root 权限

4. **netstat**（跨平台）
   - 备选方案
   - Windows、macOS、Linux 都支持

### 系统要求

确保系统安装了以下命令之一：

**Windows**:
- ✅ **PowerShell**（Windows 10+ 默认已安装，推荐）
- ✅ **netstat**（Windows 默认已安装）

**macOS**:
```bash
# lsof 通常已预装，如果没有：
brew install lsof
```

**Linux (Debian/Ubuntu)**:
```bash
# 安装 lsof
sudo apt-get install lsof

# 或安装 ss (iproute2)
sudo apt-get install iproute2
```

**Linux (CentOS/RHEL)**:
```bash
# 安装 lsof
sudo yum install lsof

# 或安装 ss (iproute)
sudo yum install iproute
```

### 验证

启动 exporter 后，检查日志：

**Windows**:
```powershell
# 使用 PM2
pm2 logs ollama-exporter

# 或直接运行查看输出
python src/ollama_exporter.py
```

**macOS/Linux**:
```bash
pm2 logs ollama-exporter
```

如果看到连接数正常更新，说明正常工作。

如果看到警告信息：
```
⚠️  警告: 無法獲取端口 11434 的連接信息
```

**Windows 解决方案**:
1. 确保 PowerShell 可用（Windows 10+ 默认已安装）
2. 如果 PowerShell 不可用，netstat 应该可用
3. 如果都不行，可以尝试以管理员身份运行（不推荐，但作为最后手段）

**macOS/Linux 解决方案**:
请安装相应的系统命令（lsof、ss 或 netstat）

## 其他解决方案（如果上述方法不可用）

### 方案 1: 使用 Linux Capabilities（仅 Linux）

给 Python 进程授予特定的网络监控权限，而不是完整的 root 权限。

```bash
# 安装 libcap2-bin (Debian/Ubuntu)
sudo apt-get install libcap2-bin

# 给 Python 可执行文件授予 CAP_NET_ADMIN 权限
sudo setcap cap_net_admin,cap_net_raw+eip $(which python3)
```

**注意**：这会影响所有 Python 脚本，可能不安全。

### 方案 2: 使用 Docker（推荐用于生产环境）

在 Docker 容器中运行，容器可以以 root 身份运行而不影响主机系统。

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/ ./src/
COPY config/ ./config/

# 以 root 运行（容器内，不影响主机）
USER root

CMD ["python", "src/ollama_exporter.py"]
```

### 方案 3: 使用 systemd 服务（Linux）

创建 systemd 服务文件，可以配置特定的权限：

```ini
[Unit]
Description=Ollama Metrics Exporter
After=network.target

[Service]
Type=simple
User=your-user
ExecStart=/usr/bin/python3 /path/to/src/ollama_exporter.py
Restart=always

# 可选：授予特定能力（需要 systemd >= 229）
# CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW
# AmbientCapabilities=CAP_NET_ADMIN CAP_NET_RAW

[Install]
WantedBy=multi-user.target
```

## 故障排除

### 问题：仍然提示需要 root/管理员权限

**Windows 检查**：
```powershell
# 检查 PowerShell 是否可用
powershell -Command "Get-Command Get-NetTCPConnection"

# 测试 PowerShell 命令
powershell -Command "Get-NetTCPConnection -LocalPort 11434 -ErrorAction SilentlyContinue"

# 检查 netstat 是否可用
netstat -an | findstr :11434
```

**macOS/Linux 检查**：
```bash
# 检查命令是否可用
which lsof
which ss
which netstat

# 测试命令
lsof -i :11434
ss -tn state established '( dport = :11434 or sport = :11434 )'
netstat -an | grep :11434
```

**解决**：
1. 确认系统已安装相应的命令
2. 检查这些命令是否在 PATH 中
3. 查看 exporter 日志，确认使用了哪个方法
4. 如果所有方法都失败，可能需要以管理员/root 身份运行（不推荐）

### 问题：连接数为 0

**可能原因**：
1. 没有活跃连接
2. 命令执行失败
3. 端口号不正确

**检查**：
```bash
# 手动检查连接
lsof -i :11434
# 或
ss -tn state established '( dport = :11434 or sport = :11434 )'
```

## 性能说明

**Windows**:
- **PowerShell (Get-NetTCPConnection)**: 最快，推荐，不需要管理员权限
- **netstat**: 较慢，但兼容性最好，Windows 默认已安装
- **psutil**: 最快，但可能需要管理员权限查看所有连接

**macOS/Linux**:
- **psutil**: 最快，但需要权限
- **lsof**: 较快，macOS/Linux 推荐
- **ss**: 最快（Linux），但需要安装
- **netstat**: 较慢，但兼容性最好

代码会自动选择最快且可用的方法，优先使用不需要特殊权限的方法。
