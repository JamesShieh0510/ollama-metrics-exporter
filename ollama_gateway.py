"""
Ollama Gateway - 調度器和反向代理
統一網關，負責將LLM請求轉發到多個Ollama節點
"""
import os
import asyncio
import time
import json
import re
from typing import List, Optional, Dict, Set, Tuple
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
import httpx
from dotenv import load_dotenv
import uvicorn
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response as MetricsResponse

# 加載環境變量
load_dotenv()

# 加載節點配置
CONFIG_FILE = os.getenv("NODE_CONFIG_FILE", "node_config.json")
node_config = {}
model_patterns = {}
model_name_mapping = {}
default_model_size = 7

try:
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config_data = json.load(f)
        node_config = {node["name"]: node for node in config_data.get("nodes", [])}
        model_patterns = config_data.get("model_name_patterns", {})
        model_name_mapping = config_data.get("model_name_mapping", {})
        default_model_size = config_data.get("default_model_size_b", 7)
    print(f"Loaded node configuration from {CONFIG_FILE}")
except FileNotFoundError:
    print(f"Warning: Config file {CONFIG_FILE} not found, using default configuration")
except Exception as e:
    print(f"Error loading config file: {e}")

app = FastAPI(title="Ollama Gateway", version="1.0.0")

# CORS支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prometheus metrics
request_count = Counter(
    "gateway_requests_total",
    "Total number of requests processed",
    ["method", "endpoint", "node", "status"]
)

request_duration = Histogram(
    "gateway_request_duration_seconds",
    "Request duration in seconds",
    ["method", "endpoint", "node"]
)

active_connections = Gauge(
    "gateway_active_connections",
    "Number of active connections per node",
    ["node"]
)

node_health = Gauge(
    "gateway_node_health",
    "Health status of each node (1=healthy, 0=unhealthy)",
    ["node"]
)

# 節點配置
NODES = [
    {
        "name": "node1",
        "hosts": ["192.168.50.158", "m3max", "m3max.local", "m3max-128gb.local"],
        "port": 11434,
        "weight": 1.0,  # 負載均衡權重
        "enabled": True,
    },
    {
        "name": "node2",
        "hosts": ["192.168.50.31", "m1max", "m1max.local", "m1max-64gb.local"],
        "port": 11434,
        "weight": 1.0,
        "enabled": True,
    },
    {
        "name": "node3",
        "hosts": ["192.168.50.94", "m1", "m1.local", "m1-16gb.local"],
        "port": 11434,
        "weight": 1.0,
        "enabled": True,
    },
    {
        "name": "node4",
        "hosts": ["192.168.50.155", "i7", "i74080.local", "i7g13-4080-32gb.local"],
        "port": 11434,
        "weight": 1.0,
        "enabled": True,
    },
]

# 調度策略類型
SCHEDULING_STRATEGY = os.getenv("SCHEDULING_STRATEGY", "round_robin")  # round_robin, least_connections, weighted_round_robin

# 節點狀態追蹤
node_stats: Dict[str, Dict] = {}
node_models: Dict[str, Set[str]] = {}  # 每個節點上已下載的模型列表
for node in NODES:
    node_stats[node["name"]] = {
        "active_connections": 0,
        "total_requests": 0,
        "failed_requests": 0,
        "last_health_check": None,
        "is_healthy": True,
        "current_weight": node["weight"],
        "effective_weight": node["weight"],
        "last_model_sync": None,
    }
    node_models[node["name"]] = set()

# 輪詢索引
round_robin_index = 0

# HTTP客戶端（支持連接池和超時）
timeout = httpx.Timeout(300.0, connect=10.0)  # 5分鐘總超時，10秒連接超時
client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)


class NodeSelector:
    """節點選擇器 - 實現不同的調度策略"""
    
    @staticmethod
    def round_robin(nodes: List[Dict]) -> Optional[Dict]:
        """輪詢調度"""
        global round_robin_index
        enabled_nodes = [n for n in nodes if n.get("enabled", True) and node_stats[n["name"]]["is_healthy"]]
        if not enabled_nodes:
            return None
        node = enabled_nodes[round_robin_index % len(enabled_nodes)]
        round_robin_index += 1
        return node
    
    @staticmethod
    def least_connections(nodes: List[Dict]) -> Optional[Dict]:
        """最少連接數調度"""
        enabled_nodes = [
            n for n in nodes 
            if n.get("enabled", True) and node_stats[n["name"]]["is_healthy"]
        ]
        if not enabled_nodes:
            return None
        return min(enabled_nodes, key=lambda n: node_stats[n["name"]]["active_connections"])
    
    @staticmethod
    def weighted_round_robin(nodes: List[Dict]) -> Optional[Dict]:
        """加權輪詢調度"""
        enabled_nodes = [
            n for n in nodes 
            if n.get("enabled", True) and node_stats[n["name"]]["is_healthy"]
        ]
        if not enabled_nodes:
            return None
        
        # 找到當前權重最大的節點
        max_node = max(enabled_nodes, key=lambda n: node_stats[n["name"]]["current_weight"])
        
        # 更新權重：選中節點減去總權重，所有節點加上原始權重
        total_weight = sum(n["weight"] for n in enabled_nodes)
        for node in enabled_nodes:
            if node["name"] == max_node["name"]:
                node_stats[node["name"]]["current_weight"] -= total_weight
            node_stats[node["name"]]["current_weight"] += node["weight"]
        
        return max_node


def extract_model_name_from_request(request: Request, path: str) -> Optional[str]:
    """從請求中提取模型名稱"""
    try:
        # 從路徑中提取（例如 /api/generate）
        if path.startswith("/api/"):
            # 對於 POST 請求，從請求體中提取
            if request.method == "POST":
                # 注意：這裡我們需要異步讀取body，但為了不阻塞，我們先嘗試從URL參數獲取
                pass
        
        # 從查詢參數中獲取
        model = request.query_params.get("model")
        if model:
            # 移除版本標籤
            if ":" in model:
                model = model.split(":")[0]
            return model
        
        # 從路徑中提取（例如 /api/generate/model_name）
        path_parts = path.strip("/").split("/")
        if len(path_parts) >= 3 and path_parts[0] == "api":
            # 可能是 /api/generate 或 /api/chat 等，模型名在body中
            pass
            
    except Exception as e:
        print(f"Error extracting model name: {e}")
    return None


async def extract_model_name_from_body(body: bytes) -> Tuple[Optional[str], Optional[str]]:
    """從請求體中提取模型名稱
    
    Returns:
        (model_name, full_model_name): 模型名稱（不含tag）和完整模型名稱（含tag）
    """
    try:
        if body:
            data = json.loads(body.decode('utf-8'))
            full_model = data.get("model")
            if full_model:
                # 保留完整名稱，同時返回不含tag的版本
                model_name = full_model.split(":")[0] if ":" in full_model else full_model
                return model_name, full_model
    except Exception:
        pass
    return None, None


def get_model_size_b(model_name: str, full_model_name: Optional[str] = None) -> int:
    """從模型名稱中提取參數數量（B為單位）
    
    Ollama 的模型通常格式為：model-name:tag，其中 tag 經常包含參數數量（如 :30b, :70b-instruct）
    
    Args:
        model_name: 模型名稱（可能已移除tag）
        full_model_name: 完整的模型名稱（包含tag，如 qwen3-coder:30b）
    """
    if not model_name:
        return default_model_size
    
    # 優先檢查完整模型名稱（如果提供），因為 Ollama 的 tag 中通常包含參數數量
    if full_model_name:
        full_name_lower = full_model_name.lower()
        
        # 從完整名稱中提取參數數量（可能在tag中）
        # 支持多種格式：:30b, :30B, :30-b, :30b-instruct, :30b:latest 等
        # 優先匹配 tag 部分（冒號後面的內容）
        if ":" in full_model_name:
            tag_part = full_model_name.split(":")[-1].lower()  # 取最後一個冒號後的部分
            # 匹配 tag 中的參數數量（如 30b, 30-b, 30b-instruct 等）
            match = re.search(r'(\d+)\s*[-_]?\s*b\b', tag_part)
            if match:
                return int(match.group(1))
        
        # 如果 tag 中沒有找到，在整個完整名稱中搜索
        match = re.search(r'(\d+)\s*[-_]?\s*b\b', full_name_lower)
        if match:
            return int(match.group(1))
    
    # 檢查模型名稱映射表（精確匹配）
    if model_name in model_name_mapping:
        return model_name_mapping[model_name]
    
    # 檢查完整名稱的映射（如果提供）
    if full_model_name and full_model_name in model_name_mapping:
        return model_name_mapping[full_model_name]
    
    model_name_lower = model_name.lower()
    
    # 按照模式匹配，優先匹配更大的數字
    sorted_patterns = sorted(model_patterns.items(), key=lambda x: x[1], reverse=True)
    for pattern, size in sorted_patterns:
        if pattern.lower() in model_name_lower:
            return size
    
    # 如果沒有匹配到，嘗試用正則表達式提取數字
    # 匹配類似 "70b", "120b", "7b", "30-b" 等
    match = re.search(r'(\d+)\s*[-_]?\s*b\b', model_name_lower)
    if match:
        return int(match.group(1))
    
    # 默認返回配置的默認值
    return default_model_size


def is_node_suitable_for_model(node_name: str, model_size_b: int) -> bool:
    """檢查節點是否適合運行指定大小的模型"""
    if node_name not in node_config:
        # 如果節點不在配置中，允許使用（向後兼容）
        return True
    
    node_cfg = node_config[node_name]
    supported_ranges = node_cfg.get("supported_model_ranges", [])
    
    if not supported_ranges:
        return True  # 沒有配置範圍，允許使用
    
    for range_cfg in supported_ranges:
        min_params = range_cfg.get("min_params_b", 0)
        max_params = range_cfg.get("max_params_b")
        
        if max_params is None:
            # 無上限
            if model_size_b >= min_params:
                return True
        else:
            if min_params <= model_size_b <= max_params:
                return True
    
    return False


def filter_nodes_by_model(nodes: List[Dict], model_name: Optional[str], model_size_b: int) -> List[Dict]:
    """根據模型名稱和大小過濾節點"""
    if not model_name:
        # 如果沒有模型名稱，返回所有節點
        return nodes
    
    filtered = []
    for node in nodes:
        node_name = node["name"]
        
        # 第一步：檢查節點是否有該模型
        has_model = model_name in node_models.get(node_name, set())
        if not has_model:
            continue
        
        # 第二步：檢查節點硬件是否適合該模型大小
        if not is_node_suitable_for_model(node_name, model_size_b):
            continue
        
        # 第三步：檢查節點是否啟用且健康
        if not node.get("enabled", True):
            continue
        if not node_stats[node_name]["is_healthy"]:
            continue
        
        filtered.append(node)
    
    return filtered


def select_node(model_name: Optional[str] = None, model_size_b: Optional[int] = None) -> Optional[Dict]:
    """根據調度策略選擇節點，支持模型感知的節點選擇"""
    # 如果提供了模型信息，先過濾節點
    candidate_nodes = NODES
    if model_name and model_size_b is not None:
        candidate_nodes = filter_nodes_by_model(NODES, model_name, model_size_b)
        # 如果過濾後沒有節點，回退到所有節點（允許模型下載）
        if not candidate_nodes:
            print(f"Warning: No suitable nodes found for model {model_name} ({model_size_b}B), falling back to all nodes")
            candidate_nodes = [n for n in NODES if n.get("enabled", True) and node_stats[n["name"]]["is_healthy"]]
    
    # 根據調度策略選擇
    if SCHEDULING_STRATEGY == "least_connections":
        return NodeSelector.least_connections(candidate_nodes)
    elif SCHEDULING_STRATEGY == "weighted_round_robin":
        return NodeSelector.weighted_round_robin(candidate_nodes)
    else:  # 默認使用 round_robin
        return NodeSelector.round_robin(candidate_nodes)


def get_node_url(node: Dict) -> str:
    """獲取節點的完整URL（使用第一個host）"""
    return f"http://{node['hosts'][0]}:{node['port']}"


async def get_node_models(node: Dict) -> Set[str]:
    """獲取節點上已下載的模型列表"""
    try:
        url = f"{get_node_url(node)}/api/tags"
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                models = set()
                for model_info in data.get("models", []):
                    model_name = model_info.get("name", "")
                    # 移除版本標籤，只保留模型名
                    if ":" in model_name:
                        model_name = model_name.split(":")[0]
                    models.add(model_name)
                return models
    except Exception as e:
        print(f"Failed to get models from {node['name']}: {e}")
    return set()


async def health_check_node(node: Dict) -> bool:
    """健康檢查節點並同步模型列表"""
    try:
        url = f"{get_node_url(node)}/api/tags"
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            response = await client.get(url)
            is_healthy = response.status_code == 200
            node_stats[node["name"]]["is_healthy"] = is_healthy
            node_stats[node["name"]]["last_health_check"] = time.time()
            node_health.labels(node=node["name"]).set(1 if is_healthy else 0)
            
            # 同步模型列表
            if is_healthy:
                models = await get_node_models(node)
                node_models[node["name"]] = models
                node_stats[node["name"]]["last_model_sync"] = time.time()
            
            return is_healthy
    except Exception as e:
        print(f"Health check failed for {node['name']}: {e}")
        node_stats[node["name"]]["is_healthy"] = False
        node_stats[node["name"]]["last_health_check"] = time.time()
        node_health.labels(node=node["name"]).set(0)
        return False


async def periodic_health_check():
    """定期健康檢查所有節點"""
    while True:
        for node in NODES:
            if node.get("enabled", True):
                await health_check_node(node)
        await asyncio.sleep(30)  # 每30秒檢查一次


@app.on_event("startup")
async def startup_event():
    """啟動時初始化"""
    # 初始化metrics
    for node in NODES:
        active_connections.labels(node=node["name"]).set(0)
        node_health.labels(node=node["name"]).set(0)
    
    # 啟動健康檢查任務
    asyncio.create_task(periodic_health_check())
    
    # 立即執行一次健康檢查
    for node in NODES:
        if node.get("enabled", True):
            await health_check_node(node)


@app.on_event("shutdown")
async def shutdown_event():
    """關閉時清理資源"""
    await client.aclose()


async def proxy_request(request: Request, path: str):
    """代理請求到選定的節點"""
    # 先讀取請求體（用於提取模型信息）
    body_bytes = b""
    if request.method == "POST":
        try:
            body_bytes = await request.body()
        except Exception:
            pass
    
    # 提取模型信息
    model_name = None
    full_model_name = None
    model_size_b = None
    
    # 先從查詢參數獲取
    full_model_name = request.query_params.get("model")
    if full_model_name:
        model_name = full_model_name.split(":")[0] if ":" in full_model_name else full_model_name
    
    # 如果沒有，從請求體獲取
    if not model_name and body_bytes:
        model_name, full_model_name = await extract_model_name_from_body(body_bytes)
    
    # 計算模型大小（傳入完整名稱以便從tag中提取參數數量）
    if model_name:
        model_size_b = get_model_size_b(model_name, full_model_name)
        display_name = full_model_name if full_model_name else model_name
        print(f"Request for model: {display_name} ({model_size_b}B)")
    
    # 選擇節點（基於模型信息）
    node = select_node(model_name, model_size_b)
    if not node:
        raise HTTPException(status_code=503, detail="No healthy nodes available")
    
    node_name = node["name"]
    node_url = get_node_url(node)
    target_url = f"{node_url}{path}"
    
    # 更新連接數
    node_stats[node_name]["active_connections"] += 1
    active_connections.labels(node=node_name).set(node_stats[node_name]["active_connections"])
    
    start_time = time.time()
    status_code = 500
    method = request.method  # 在try塊外定義，確保異常處理中可用
    
    try:
        # 準備請求
        headers = dict(request.headers)
        # 移除可能導致問題的headers
        headers.pop("host", None)
        headers.pop("content-length", None)
        
        # 使用之前讀取的body
        body = body_bytes
        
        # 轉發請求
        params = dict(request.query_params)
        
        response = await client.request(
            method=method,
            url=target_url,
            headers=headers,
            content=body,
            params=params,
        )
        
        status_code = response.status_code
        node_stats[node_name]["total_requests"] += 1
        
        # 更新metrics
        request_count.labels(
            method=method,
            endpoint=path,
            node=node_name,
            status=status_code
        ).inc()
        
        duration = time.time() - start_time
        request_duration.labels(
            method=method,
            endpoint=path,
            node=node_name
        ).observe(duration)
        
        # 如果是流式響應
        if "text/event-stream" in response.headers.get("content-type", ""):
            async def generate():
                try:
                    async for chunk in response.aiter_bytes():
                        yield chunk
                finally:
                    node_stats[node_name]["active_connections"] -= 1
                    active_connections.labels(node=node_name).set(node_stats[node_name]["active_connections"])
            
            return StreamingResponse(
                generate(),
                status_code=status_code,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type", "text/event-stream")
            )
        else:
            # 普通響應
            content = await response.aread()
            node_stats[node_name]["active_connections"] -= 1
            active_connections.labels(node=node_name).set(node_stats[node_name]["active_connections"])
            
            return Response(
                content=content,
                status_code=status_code,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type", "application/json")
            )
    
    except httpx.TimeoutException:
        node_stats[node_name]["failed_requests"] += 1
        node_stats[node_name]["active_connections"] -= 1
        active_connections.labels(node=node_name).set(node_stats[node_name]["active_connections"])
        
        request_count.labels(
            method=method,
            endpoint=path,
            node=node_name,
            status="timeout"
        ).inc()
        
        raise HTTPException(status_code=504, detail=f"Request to {node_name} timed out")
    
    except Exception as e:
        node_stats[node_name]["failed_requests"] += 1
        node_stats[node_name]["active_connections"] -= 1
        active_connections.labels(node=node_name).set(node_stats[node_name]["active_connections"])
        
        request_count.labels(
            method=method,
            endpoint=path,
            node=node_name,
            status="error"
        ).inc()
        
        print(f"Error proxying to {node_name}: {e}")
        raise HTTPException(status_code=502, detail=f"Error proxying to {node_name}: {str(e)}")


# 根路徑重定向到拓撲頁面（必須在通配符路由之前）
@app.get("/", response_class=HTMLResponse)
async def root():
    """根路徑，重定向到拓撲可視化或顯示歡迎頁面"""
    try:
        # 嘗試返回拓撲頁面
        return await topology_viewer()
    except Exception:
        # 如果失敗，返回簡單的歡迎頁面
        welcome_html = """
        <!DOCTYPE html>
        <html lang="zh-TW">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Ollama Gateway</title>
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
                    max-width: 800px;
                    margin: 50px auto;
                    padding: 20px;
                    background: #f5f7fa;
                }
                h1 { color: #2563eb; }
                .endpoint {
                    background: white;
                    padding: 15px;
                    margin: 10px 0;
                    border-radius: 8px;
                    border-left: 4px solid #2563eb;
                }
                a {
                    color: #2563eb;
                    text-decoration: none;
                    font-weight: 600;
                }
                a:hover { text-decoration: underline; }
                code {
                    background: #f1f5f9;
                    padding: 2px 6px;
                    border-radius: 4px;
                    font-family: 'Monaco', 'Courier New', monospace;
                }
            </style>
        </head>
        <body>
            <h1>🚀 Ollama Gateway</h1>
            <p>統一的 Ollama 網關服務，提供負載均衡和智能節點選擇。</p>
            
            <div class="endpoint">
                <h3>📊 <a href="/topology">3D 網絡拓撲可視化</a></h3>
                <p>實時查看集群網絡拓撲和節點狀態</p>
            </div>
            
            <div class="endpoint">
                <h3>🔍 <a href="/health">健康檢查</a></h3>
                <p>查看網關和節點的健康狀態</p>
                <code>GET /health</code>
            </div>
            
            <div class="endpoint">
                <h3>📡 <a href="/nodes">節點狀態</a></h3>
                <p>查看所有節點的詳細信息和已下載的模型列表</p>
                <code>GET /nodes</code>
            </div>
            
            <div class="endpoint">
                <h3>📈 <a href="/metrics">Prometheus Metrics</a></h3>
                <p>Prometheus 監控指標</p>
                <code>GET /metrics</code>
            </div>
            
            <div class="endpoint">
                <h3>🤖 Ollama API</h3>
                <p>所有 Ollama API 請求會自動代理到合適的節點</p>
                <code>POST /api/generate</code><br>
                <code>GET /api/tags</code><br>
                <code>POST /api/chat</code>
            </div>
        </body>
        </html>
        """
        return HTMLResponse(content=welcome_html)


# 拓撲可視化頁面（必須在通配符路由之前）
@app.get("/topology", response_class=HTMLResponse)
async def topology_viewer():
    """3D 網絡拓撲可視化頁面"""
    try:
        html_file = os.path.join(os.path.dirname(__file__), "topology-3d.html")
        with open(html_file, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>錯誤</h1><p>找不到 topology-3d.html 文件</p>",
            status_code=404
        )
    except Exception as e:
        return HTMLResponse(
            content=f"<h1>錯誤</h1><p>讀取文件時發生錯誤: {str(e)}</p>",
            status_code=500
        )


# 健康檢查端點
@app.get("/health")
async def health():
    """網關健康檢查"""
    healthy_nodes = sum(1 for node in NODES if node_stats[node["name"]]["is_healthy"])
    return {
        "status": "healthy" if healthy_nodes > 0 else "degraded",
        "healthy_nodes": healthy_nodes,
        "total_nodes": len(NODES),
        "nodes": {
            node["name"]: {
                "healthy": node_stats[node["name"]]["is_healthy"],
                "active_connections": node_stats[node["name"]]["active_connections"],
                "total_requests": node_stats[node["name"]]["total_requests"],
                "failed_requests": node_stats[node["name"]]["failed_requests"],
            }
            for node in NODES
        }
    }


# 節點狀態端點
@app.get("/nodes")
async def get_nodes():
    """獲取所有節點狀態"""
    return {
        "scheduling_strategy": SCHEDULING_STRATEGY,
        "nodes": [
            {
                "name": node["name"],
                "hosts": node["hosts"],
                "port": node["port"],
                "weight": node["weight"],
                "enabled": node.get("enabled", True),
                "stats": node_stats[node["name"]],
                "models": list(node_models.get(node["name"], set())),
                "config": node_config.get(node["name"], {}),
            }
            for node in NODES
        ]
    }


# Prometheus metrics端點
@app.get("/metrics")
async def metrics():
    """Prometheus metrics"""
    return MetricsResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# 代理所有Ollama API請求（必須放在最後，作為通配符路由）
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_all(request: Request, path: str):
    """代理所有請求到Ollama節點"""
    return await proxy_request(request, f"/{path}")


if __name__ == "__main__":
    gateway_port = int(os.getenv("GATEWAY_PORT", "11435"))
    uvicorn.run(app, host="0.0.0.0", port=gateway_port)

