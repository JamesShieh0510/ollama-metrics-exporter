#!/bin/bash
# 檢查 metrics 的腳本

echo "=== 檢查 Ollama Exporter Metrics ==="
echo ""

# 節點列表
NODES=(
    "192.168.50.158:9101:node1"
    "192.168.50.31:9101:node2"
    "192.168.50.94:9101:node3"
    "192.168.50.155:9101:node4"
)

for node_info in "${NODES[@]}"; do
    IFS=':' read -r ip port node_name <<< "$node_info"
    echo "--- 檢查 $node_name ($ip:$port) ---"
    
    if curl -s --max-time 2 "http://$ip:$port/metrics" > /dev/null 2>&1; then
        echo "✅ Exporter 運行中"
        
        # 檢查關鍵 metrics
        metrics=$(curl -s --max-time 2 "http://$ip:$port/metrics")
        
        if echo "$metrics" | grep -q "ollama_connections"; then
            echo "✅ 找到 ollama_connections metric"
            echo "$metrics" | grep "ollama_connections" | head -3
        else
            echo "❌ 未找到 ollama_connections metric"
        fi
        
        if echo "$metrics" | grep -q "ollama_bytes_sent_total"; then
            echo "✅ 找到 ollama_bytes_sent_total metric"
        else
            echo "❌ 未找到 ollama_bytes_sent_total metric"
        fi
        
        if echo "$metrics" | grep -q "ollama_bytes_recv_total"; then
            echo "✅ 找到 ollama_bytes_recv_total metric"
        else
            echo "❌ 未找到 ollama_bytes_recv_total metric"
        fi
    else
        echo "❌ Exporter 無法連接"
    fi
    echo ""
done

echo "=== 檢查完成 ==="

