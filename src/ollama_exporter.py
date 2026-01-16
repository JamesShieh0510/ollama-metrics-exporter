import os
import platform
import asyncio
import subprocess
import re
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import (
    Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
)
from fastapi.responses import Response
import uvicorn
from dotenv import load_dotenv
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# 檢測操作系統
IS_WINDOWS = platform.system() == 'Windows'
IS_MAC = platform.system() == 'Darwin'
IS_LINUX = platform.system() == 'Linux'

# Load environment variables from .env file
load_dotenv()

OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))  # 監控的 Ollama 端口
app = FastAPI()

# 添加 CORS 支持，允许前端页面访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境建议限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# 邊 (edges) - 從各節點到 router 的連接
ollama_node_to_router = Gauge(
    "ollama_node_to_router",
    "Connection from node to router (for NodeGraph edges)",
    ["source", "target"]
)

# 連接狀態追蹤（用於計算流量變化）
_last_connections = {}
_last_bytes_sent = {}
_last_bytes_recv = {}
_connection_start_times = {}  # 追蹤連接開始時間，用於估算流量

def get_port_connections_psutil(port):
    """使用 psutil 獲取指定端口的所有連接（需要權限）"""
    connections = []
    try:
        if IS_WINDOWS:
            kind = 'inet'
        else:
            kind = 'inet'
        
        for conn in psutil.net_connections(kind=kind):
            if conn.laddr and conn.laddr.port == port:
                connections.append(conn)
            elif conn.raddr and conn.raddr.port == port:
                connections.append(conn)
    except (psutil.AccessDenied, PermissionError):
        return None  # 返回 None 表示需要降级到其他方法
    except Exception as e:
        print(f"psutil 獲取連接時發生錯誤: {e}")
        return None
    return connections

def get_port_connections_lsof(port):
    """使用 lsof 命令獲取指定端口的所有連接（macOS/Linux，不需要 root）"""
    connections = []
    try:
        # lsof -i :PORT 列出使用指定端口的所有连接
        result = subprocess.run(
            ['lsof', '-i', f':{port}', '-n', '-P'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            # 跳过标题行
            for line in lines[1:]:
                if line.strip():
                    connections.append(line)
        return connections
    except FileNotFoundError:
        return None  # lsof 不可用
    except subprocess.TimeoutExpired:
        return None
    except Exception as e:
        print(f"lsof 獲取連接時發生錯誤: {e}")
        return None

def get_port_connections_ss(port):
    """使用 ss 命令獲取指定端口的所有連接（Linux，不需要 root）"""
    connections = []
    try:
        # ss -tn state established '( dport = :PORT or sport = :PORT )'
        result = subprocess.run(
            ['ss', '-tn', 'state', 'established', f'( dport = :{port} or sport = :{port} )'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            for line in lines[1:]:  # 跳过标题行
                if line.strip():
                    connections.append(line)
        return connections
    except FileNotFoundError:
        return None  # ss 不可用
    except subprocess.TimeoutExpired:
        return None
    except Exception as e:
        print(f"ss 獲取連接時發生錯誤: {e}")
        return None

def get_port_connections_powershell(port):
    """使用 PowerShell 獲取指定端口的所有連接（Windows，不需要管理員權限）"""
    connections = []
    try:
        # PowerShell: Get-NetTCPConnection -LocalPort PORT -ErrorAction SilentlyContinue
        ps_command = f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,State | Format-Table -AutoSize"
        result = subprocess.run(
            ['powershell', '-Command', ps_command],
            capture_output=True,
            text=True,
            timeout=5,
            shell=True
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split('\n')
            # 跳过标题行和分隔线
            for line in lines:
                if line.strip() and 'LocalAddress' not in line and '---' not in line:
                    connections.append(line)
        return connections
    except FileNotFoundError:
        return None  # PowerShell 不可用
    except subprocess.TimeoutExpired:
        return None
    except Exception as e:
        print(f"PowerShell 獲取連接時發生錯誤: {e}")
        return None

def get_port_connections_netstat(port):
    """使用 netstat 命令獲取指定端口的所有連接（跨平台，不需要 root）"""
    connections = []
    try:
        if IS_WINDOWS:
            # Windows: netstat -an | findstr :PORT
            # 使用 findstr 过滤，更高效
            result = subprocess.run(
                ['netstat', '-an'],
                capture_output=True,
                text=True,
                timeout=5,
                shell=True  # Windows 上需要 shell=True
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    # 检查是否包含端口号（格式: :PORT 或 :PORT空格）
                    if line and f':{port}' in line:
                        connections.append(line)
        else:
            # Unix: netstat -an | grep :PORT
            result = subprocess.run(
                ['netstat', '-an'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if f':{port}' in line:
                        connections.append(line)
        return connections
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None
    except Exception as e:
        print(f"netstat 獲取連接時發生錯誤: {e}")
        return None

def count_connections_from_output(connections, port):
    """从命令输出中统计连接数"""
    if not connections:
        return 0, 0
    
    established_count = 0
    listen_count = 0
    
    for conn in connections:
        conn_str = str(conn).upper()
        
        if IS_WINDOWS:
            # Windows netstat 输出格式: TCP    0.0.0.0:11434    0.0.0.0:0    LISTENING
            # Windows PowerShell 输出格式: State 列显示 Listen, Established 等
            if 'ESTABLISHED' in conn_str or 'ESTAB' in conn_str:
                established_count += 1
            elif 'LISTEN' in conn_str or 'LISTENING' in conn_str:
                listen_count += 1
            # Windows netstat 状态码: LISTENING, ESTABLISHED, TIME_WAIT, CLOSE_WAIT 等
            elif 'TIME_WAIT' in conn_str or 'CLOSE_WAIT' in conn_str:
                # 这些状态也算作已建立过的连接
                established_count += 1
            # 如果包含端口但没有明确状态，检查是否是监听状态（通常有 0.0.0.0:PORT 或 :::PORT）
            elif f':{port}' in str(conn):
                # 检查是否是监听状态（本地地址是 0.0.0.0 或 ::，远程地址是 0.0.0.0:0）
                if '0.0.0.0:0' in conn_str or ':::0' in conn_str or '[*]' in conn_str:
                    listen_count += 1
                else:
                    established_count += 1
        else:
            # Unix/Linux/macOS 输出格式
            if 'ESTABLISHED' in conn_str or 'ESTAB' in conn_str:
                established_count += 1
            elif 'LISTEN' in conn_str or 'LISTENING' in conn_str:
                listen_count += 1
            # 如果没有明确状态，但包含端口，假设是已建立连接
            elif f':{port}' in str(conn):
                established_count += 1
    
    return established_count, listen_count

def get_port_connections(port):
    """獲取指定端口的所有連接（自动选择最佳方法）"""
    # 方法 1: 尝试使用 psutil（如果可用且有权限）
    if PSUTIL_AVAILABLE:
        psutil_conns = get_port_connections_psutil(port)
        if psutil_conns is not None:
            # 转换 psutil 连接对象为可统计的格式
            established = sum(1 for c in psutil_conns if getattr(c, 'status', '') in ['ESTABLISHED', 5])
            listen = sum(1 for c in psutil_conns if getattr(c, 'status', '') in ['LISTEN', 'LISTENING', 2])
            return psutil_conns, established, listen
    
    # 方法 2: 尝试使用系统命令（不需要 root）
    connections = None
    established = 0
    listen = 0
    
    if IS_MAC or IS_LINUX:
        # macOS/Linux: 优先使用 lsof
        connections = get_port_connections_lsof(port)
        if connections:
            established, listen = count_connections_from_output(connections, port)
            return connections, established, listen
        
        # Linux: 尝试使用 ss
        if IS_LINUX:
            connections = get_port_connections_ss(port)
            if connections:
                established, listen = count_connections_from_output(connections, port)
                return connections, established, listen
    
    # 方法 3: Windows 优先使用 PowerShell
    if IS_WINDOWS:
        connections = get_port_connections_powershell(port)
        if connections:
            established, listen = count_connections_from_output(connections, port)
            return connections, established, listen
    
    # 方法 4: 使用 netstat（跨平台备选）
    connections = get_port_connections_netstat(port)
    if connections:
        established, listen = count_connections_from_output(connections, port)
        return connections, established, listen
    
    # 如果所有方法都失败，返回空结果
    if IS_WINDOWS:
        print(f"⚠️  警告: 無法獲取端口 {port} 的連接信息")
        print(f"   提示: 請確保 PowerShell 或 netstat 命令可用")
        print(f"   嘗試: 以管理員身份運行可能可以解決問題")
    else:
        print(f"⚠️  警告: 無法獲取端口 {port} 的連接信息")
        print(f"   提示: 請確保系統已安裝 lsof、ss 或 netstat 命令")
    return [], 0, 0

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
            # 獲取連接數（自动选择最佳方法）
            result = get_port_connections(OLLAMA_PORT)
            if isinstance(result, tuple) and len(result) == 3:
                connections, established_count, listen_count = result
            else:
                # 兼容旧代码（如果返回的是连接列表）
                connections = result
                established_count = 0
                listen_count = 0
                
                # 如果是 psutil 连接对象，需要解析状态
                if connections and PSUTIL_AVAILABLE and hasattr(connections[0], 'status'):
                    for conn in connections:
                        state = getattr(conn, 'status', None)
                        if state is None:
                            state = 'UNKNOWN'
                        elif IS_WINDOWS:
                            if isinstance(state, int):
                                state_map = {2: 'LISTEN', 5: 'ESTABLISHED'}
                                state = state_map.get(state, 'UNKNOWN')
                            elif state.upper() in ['LISTEN', 'LISTENING']:
                                state = 'LISTEN'
                            elif state.upper() in ['ESTABLISHED']:
                                state = 'ESTABLISHED'
                        
                        if state == 'ESTABLISHED':
                            established_count += 1
                        elif state == 'LISTEN':
                            listen_count += 1
            
            # 更新連接數 metrics（主要關注 ESTABLISHED）
            ollama_connections.labels(node=NODE_NAME, state="ESTABLISHED").set(established_count)
            ollama_connections.labels(node=NODE_NAME, state="LISTEN").set(listen_count)
            
            # 🌟 更新網絡拓撲 metrics
            # 設置虛擬 router 節點（使用相同的 ollama_connections metric）
            # 計算所有節點的總連接數（這在單個 exporter 中就是當前節點的連接數）
            ollama_connections.labels(node="router", state="ESTABLISHED").set(established_count)
            
            # 設置從當前節點到 router 的邊
            # 邊的值 = 當前節點的連接數
            ollama_node_to_router.labels(source=NODE_NAME, target="router").set(established_count)
            
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
    # 🌟 初始化網絡拓撲 metrics
    ollama_connections.labels(node="router", state="ESTABLISHED").set(0)
    ollama_node_to_router.labels(source=NODE_NAME, target="router").set(0)
    # 啟動後台監控任務
    asyncio.create_task(monitor_port())

# ---- Metrics endpoint ----
@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9101)