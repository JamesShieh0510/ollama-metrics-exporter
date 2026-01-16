#!/bin/bash

# Ollama Gateway 测试脚本

GATEWAY_URL="${GATEWAY_URL:-http://localhost:11435}"

echo "Testing Ollama Gateway at $GATEWAY_URL"
echo "========================================"
echo ""

# 测试1: 健康检查
echo "1. Testing health endpoint..."
curl -s "$GATEWAY_URL/health" | jq '.' || echo "Health check failed"
echo ""
echo ""

# 测试2: 节点状态
echo "2. Testing nodes endpoint..."
curl -s "$GATEWAY_URL/nodes" | jq '.' || echo "Nodes endpoint failed"
echo ""
echo ""

# 测试3: 列出模型（需要至少一个节点可用）
echo "3. Testing API proxy (list models)..."
curl -s "$GATEWAY_URL/api/tags" | jq '.' || echo "API proxy failed"
echo ""
echo ""

# 测试4: Prometheus metrics
echo "4. Testing metrics endpoint..."
curl -s "$GATEWAY_URL/metrics" | head -20 || echo "Metrics endpoint failed"
echo ""
echo ""

echo "========================================"
echo "Tests completed!"

