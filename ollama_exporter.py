import os
import platform
import asyncio
from fastapi import FastAPI
from prometheus_client import (
    Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
)
from fastapi.responses import Response
import uvicorn
from dotenv import load_dotenv
import psutil

# 檢測操作系統
IS_WINDOWS = platform.system() == 'Windows'
IS_MAC = platform.system() == 'Darwin'
IS_LINUX = platform.system() == 'Linux'

# Load environment variables from .env file
load_dotenv()

OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))  # 監控的 Ollama 端口
app = FastAPI()

# ---- Prometheus metrics ----
NODE_NAME = os.getenv("NODE_NAME", "node1")  # 從 .env 讀取，預設為 node1

# 連接數相關 metrics
ollama_connections = Gauge(
    "ollama_connections",
    "Current number of connections to Ollama port",
    ["node", "state"]
)

# 流量相關 metrics
ollama_bytes_sent = Counter(
    "ollama_bytes_sent_total",
    "Total bytes sent to Ollama port",
    ["node"]
)

ollama_bytes_recv = Counter(
    "ollama_bytes_recv_total",
    "Total bytes received from Ollama port",
    ["node"]
)

# 連接狀態追蹤（用於計算流量變化）
_last_connections = {}
_last_bytes_sent = {}
_last_bytes_recv = {}
_connection_start_times = {}  # 追蹤連接開始時間，用於估算流量

def get_port_connections(port):
    """獲取指定端口的所有連接"""
    connections = []
    try:
        # Windows 和 Unix 系統使用不同的參數
        if IS_WINDOWS:
            # Windows 上使用 'all' 或 'inet'，但行為可能不同
            kind = 'inet'
        else:
            # Mac/Linux 使用 'inet'
            kind = 'inet'
        
        for conn in psutil.net_connections(kind=kind):
            # 檢查是否為監聽該端口的連接（服務端）
            if conn.laddr and conn.laddr.port == port:
                connections.append(conn)
            # 檢查是否為連接到該端口的連接（客戶端）
            elif conn.raddr and conn.raddr.port == port:
                connections.append(conn)
    except (psutil.AccessDenied, PermissionError):
        # 某些系統需要 root/管理員權限
        if IS_WINDOWS:
            print(f"警告: 需要管理員權限來監控端口 {port}，請以管理員身份運行")
        else:
            print(f"警告: 需要 root 權限來監控端口 {port}，請以管理員權限運行")
    except Exception as e:
        print(f"獲取連接時發生錯誤: {e}")
    return connections

def estimate_traffic_from_connections(established_count, time_elapsed):
    """基於連接數和時間估算流量
    
    注意：這是一個估算方法，不是精確的網絡流量統計。
    由於被動監控無法直接獲取端口級別的網絡流量，我們使用連接數
    和連接持續時間來估算。這個估算基於以下假設：
    - 每個活躍連接平均每秒產生一定量的流量
    - 流量與連接數和時間成正比
    """
    if established_count == 0:
        return 0, 0
    
    # 估算參數（可根據實際情況調整）
    # 假設每個連接平均每秒產生 10KB 的流量（發送+接收）
    # 這是一個保守的估算，實際流量可能更高
    BYTES_PER_CONN_PER_SEC = 10 * 1024  # 10KB per connection per second
    
    # 計算估算的總流量
    estimated_total = established_count * BYTES_PER_CONN_PER_SEC * time_elapsed
    
    # 假設發送和接收各佔一半
    estimated_sent = estimated_total // 2
    estimated_recv = estimated_total // 2
    
    return estimated_sent, estimated_recv

async def monitor_port():
    """定期監控端口連接和流量"""
    global _last_connections, _last_bytes_sent, _last_bytes_recv, _connection_start_times
    import time as time_module
    
    last_check_time = time_module.time()
    
    while True:
        try:
            # 獲取連接數
            connections = get_port_connections(OLLAMA_PORT)
            
            # 統計不同狀態的連接（只統計 ESTABLISHED 狀態的連接）
            established_count = 0
            listen_count = 0
            states = {}
            
            for conn in connections:
                state = getattr(conn, 'status', None)
                # Windows 上狀態值可能不同，需要標準化
                if state is None:
                    state = 'UNKNOWN'
                elif IS_WINDOWS:
                    # Windows 上狀態可能是數字或不同的字符串
                    # 標準化狀態名稱
                    if isinstance(state, int):
                        # Windows 使用數字狀態碼，需要轉換
                        # TCP 狀態: 2=LISTEN, 5=ESTABLISHED
                        state_map = {2: 'LISTEN', 5: 'ESTABLISHED'}
                        state = state_map.get(state, 'UNKNOWN')
                    elif state.upper() in ['LISTEN', 'LISTENING']:
                        state = 'LISTEN'
                    elif state.upper() in ['ESTABLISHED']:
                        state = 'ESTABLISHED'
                
                states[state] = states.get(state, 0) + 1
                if state == 'ESTABLISHED':
                    established_count += 1
                elif state == 'LISTEN':
                    listen_count += 1
            
            # 更新連接數 metrics（主要關注 ESTABLISHED）
            ollama_connections.labels(node=NODE_NAME, state="ESTABLISHED").set(established_count)
            ollama_connections.labels(node=NODE_NAME, state="LISTEN").set(listen_count)
            
            # 計算時間差
            current_time = time_module.time()
            time_elapsed = current_time - last_check_time
            last_check_time = current_time
            
            # 使用連接數和時間來估算流量
            # 注意：這是一個估算方法，不是精確的網絡流量統計
            if established_count > 0:
                estimated_sent, estimated_recv = estimate_traffic_from_connections(
                    established_count, time_elapsed
                )
                
                # 更新 counter（累加估算的流量）
                if estimated_sent > 0:
                    ollama_bytes_sent.labels(node=NODE_NAME).inc(estimated_sent)
                if estimated_recv > 0:
                    ollama_bytes_recv.labels(node=NODE_NAME).inc(estimated_recv)
            
            _last_connections[NODE_NAME] = established_count
            
        except Exception as e:
            print(f"監控錯誤: {e}")
            import traceback
            traceback.print_exc()
        
        await asyncio.sleep(2)  # 每 2 秒檢查一次

# ✅ 啟動時開始監控
@app.on_event("startup")
async def startup_event():
    # 初始化所有 metrics，確保 Prometheus 可以看到它們
    ollama_connections.labels(node=NODE_NAME, state="ESTABLISHED").set(0)
    ollama_connections.labels(node=NODE_NAME, state="LISTEN").set(0)
    # 初始化 counter（觸發第一次記錄，讓 Prometheus 知道這些 metrics 存在）
    ollama_bytes_sent.labels(node=NODE_NAME).inc(0)
    ollama_bytes_recv.labels(node=NODE_NAME).inc(0)
    # 啟動後台監控任務
    asyncio.create_task(monitor_port())

# ---- Metrics endpoint ----
@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9101)