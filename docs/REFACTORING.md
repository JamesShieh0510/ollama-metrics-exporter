# 项目重构说明

## 重构日期
2025-01-14

## 重构目标
整理项目根目录，将文件按功能分类到不同目录，提高项目可维护性。

## 新的目录结构

```
ollama-metrics-exporter/
├── src/                    # Python 源代码
│   ├── ollama_exporter.py  # Metrics exporter
│   ├── ollama_gateway.py   # Gateway 服务
│   └── ollama_humaneval_runner.py  # HumanEval 评估工具
├── config/                 # 配置文件
│   ├── node_config.json    # 节点配置
│   └── grafana-dashboard.json  # Grafana 仪表板配置
├── scripts/                # 启动和工具脚本
│   ├── start.sh            # 启动 exporter
│   ├── start.bat           # Windows 启动脚本
│   ├── start_gateway.sh    # 启动 gateway
│   ├── test_gateway.sh     # Gateway 测试脚本
│   └── check_metrics.sh    # Metrics 检查脚本
├── static/                 # 静态文件
│   └── topology-3d.html    # 3D 拓扑可视化
├── data/                   # 数据文件
│   └── results.jsonl       # 评估结果（由脚本生成）
├── backups/                # 备份文件
│   └── node_config.json.backup.*  # 配置文件备份
├── docs/                   # 文档目录
│   ├── README.md           # 文档索引
│   ├── GATEWAY_README.md
│   ├── NODE_CONFIG_README.md
│   └── ... (其他文档)
├── requirements.txt        # Python 依赖
├── README.md              # 项目说明
└── .gitignore             # Git 忽略文件
```

## 主要变更

### 1. Python 源代码
- **原位置**: 根目录
- **新位置**: `src/`
- **文件**: 
  - `ollama_exporter.py`
  - `ollama_gateway.py`
  - `ollama_humaneval_runner.py`

### 2. 配置文件
- **原位置**: 根目录
- **新位置**: `config/`
- **文件**:
  - `node_config.json`
  - `grafana-dashboard.json`

### 3. 脚本文件
- **原位置**: 根目录
- **新位置**: `scripts/`
- **文件**:
  - `start.sh`
  - `start.bat`
  - `start_gateway.sh`
  - `test_gateway.sh`
  - `check_metrics.sh`

### 4. 静态文件
- **原位置**: 根目录
- **新位置**: `static/`
- **文件**:
  - `topology-3d.html`

### 5. 数据文件
- **原位置**: 根目录
- **新位置**: `data/`
- **文件**:
  - `results.jsonl`

### 6. 备份文件
- **原位置**: 根目录
- **新位置**: `backups/`
- **文件**:
  - `node_config.json.backup.*`

## 代码更新

### 1. `src/ollama_gateway.py`
- 更新了 `CONFIG_FILE` 的默认路径，使用项目根目录相对路径
- 更新了 `topology-3d.html` 的路径引用
- 更新了备份文件的保存路径到 `backups/` 目录

**关键变更**:
```python
# 获取项目根目录（src 的父目录）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.getenv("NODE_CONFIG_FILE", os.path.join(PROJECT_ROOT, "config", "node_config.json"))
```

### 2. `src/ollama_humaneval_runner.py`
- 更新了默认输出路径到 `data/results.jsonl`

### 3. 启动脚本
- `scripts/start.sh`: 更新 Python 脚本路径为 `src/ollama_exporter.py`
- `scripts/start_gateway.sh`: 更新 Python 脚本路径为 `src/ollama_gateway.py`

### 4. README.md
- 更新了启动脚本的路径引用
- 添加了项目结构说明

## 环境变量

以下环境变量仍然有效，但路径已自动适配：

- `NODE_CONFIG_FILE`: 如果未设置，默认使用 `config/node_config.json`
- 其他环境变量保持不变

## 迁移指南

### 对于现有用户

1. **更新启动命令**:
   ```bash
   # 旧方式
   ./start.sh
   
   # 新方式
   ./scripts/start.sh
   ```

2. **配置文件位置**:
   - 配置文件已移动到 `config/` 目录
   - 如果使用环境变量 `NODE_CONFIG_FILE`，请更新路径或使用新的默认路径

3. **数据文件**:
   - 评估结果现在保存在 `data/results.jsonl`
   - 备份文件保存在 `backups/` 目录

### 对于开发者

1. **导入路径**: Python 脚本现在在 `src/` 目录，导入时需要注意路径
2. **配置文件**: 使用 `PROJECT_ROOT` 变量来构建相对于项目根目录的路径
3. **测试**: 确保测试脚本使用正确的路径

## 向后兼容性

- 环境变量 `NODE_CONFIG_FILE` 仍然支持，可以指定完整路径
- 所有功能保持不变，只是文件组织更清晰

## 后续建议

1. 考虑添加 `__init__.py` 使 `src/` 成为 Python 包
2. 考虑将测试文件组织到 `tests/` 目录
3. 考虑添加配置文件模板到 `config/` 目录
