#!/bin/bash

# Ollama Gateway 啟動腳本

echo "Starting Ollama Gateway..."

# 檢查Python環境
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is not installed"
    exit 1
fi

# 安裝依賴
echo "Installing dependencies..."
pip install -r requirements.txt

# 啟動網關
echo "Starting gateway on port ${GATEWAY_PORT:-11435}..."
python3 src/ollama_gateway.py

SCHEDULING_STRATEGY=round_robin
