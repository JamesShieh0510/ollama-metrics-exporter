# Grafana Dashboard 設置指南

## 概述

這個 Grafana Dashboard 用於監控 Ollama 集群的網絡連接和流量。包含 4 個 Ollama 節點和 1 個路由器。

## 節點配置

| Node | IP | Hostname | Node ID |
|------|----|----------|---------|
| m3max | 192.168.50.158 | m3max.local / m3max-128gb.local | node1 |
| m1max | 192.168.50.31 | m1max.local / m1max-64gb.local | node2 |
| m1 | 192.168.50.94 | m1.local / m1-16gb.local | node3 |
| i7 | 192.168.50.155 | i74080.local / i7g13-4080-32gb.local | node4 |
| Router | 192.168.50.1 | - | router |

## 導入 Dashboard

1. 登入 Grafana
2. 點擊左側選單的 **Dashboards** → **Import**
3. 點擊 **Upload JSON file**，選擇 `grafana-dashboard.json`
4. 選擇你的 Prometheus 數據源
5. 點擊 **Import**

## Dashboard 面板說明

### 1. Ollama 連接數
- 顯示所有節點的 ESTABLISHED 和 LISTEN 連接數
- 時間序列圖表

### 2. Ollama 流量速率
- 顯示各節點的發送和接收速率（Bytes/s）
- 使用 `rate()` 函數計算 5 分鐘平均速率

### 3. 各節點連接數統計
- Node1 (m3max) - 連接數
- Node2 (m1max) - 連接數
- Node3 (m1) - 連接數
- Node4 (i7) - 連接數
- 單個統計面板，顯示當前連接數

### 4. 總流量累計
- 顯示所有節點的總發送和接收字節數累計值

### 5. 各節點流量速率
- 按節點分組顯示流量速率

### 6. 網絡拓撲圖 (Node Graph)
- 顯示所有節點的網絡拓撲視圖
- 節點大小反映流量大小
- 節點標籤顯示節點 ID
- 主要統計：總流量速率 (sent + recv)
- 次要統計：連接數

## 配置 Prometheus 數據源

確保你的 Prometheus 數據源已正確配置，並且能夠抓取所有節點的 metrics：

```yaml
# prometheus.yml 示例
scrape_configs:
  - job_name: 'ollama-exporter'
    static_configs:
      - targets:
        - '192.168.50.158:9101'  # node1
        - '192.168.50.31:9101'   # node2
        - '192.168.50.94:9101'   # node3
        - '192.168.50.155:9101'  # node4
```

## Node Graph 說明

Node Graph 面板會自動從 Prometheus metrics 中提取節點信息：

- **節點 ID**: 從 `node` label 提取（node1, node2, node3, node4）
- **主要統計**: 總流量速率（發送 + 接收）
- **次要統計**: 當前連接數
- **節點大小**: 根據流量大小動態調整

注意：Node Graph 需要 Grafana 8.0+ 版本，並且需要正確的數據格式。如果節點沒有顯示，請檢查：

1. Prometheus 數據源是否正確配置
2. Metrics 是否包含 `node` label
3. 數據是否為 instant query（instant: true）

## 自定義配置

如果需要添加路由器節點到 Node Graph，你可能需要：

1. 在 Prometheus 中配置路由器監控
2. 或者手動添加路由器節點到 Node Graph（需要自定義數據源或 transformations）

## 刷新頻率

Dashboard 預設每 10 秒自動刷新，可以在右上角調整。

## 時間範圍

預設顯示最近 1 小時的數據，可以在右上角調整時間範圍。

