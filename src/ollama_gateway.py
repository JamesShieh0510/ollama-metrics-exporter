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
# 获取项目根目录（src 的父目录）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 处理配置文件路径
_config_file_env = os.getenv("NODE_CONFIG_FILE")
if _config_file_env:
    # 如果环境变量是绝对路径，直接使用
    if os.path.isabs(_config_file_env):
        CONFIG_FILE = _config_file_env
    else:
        # 如果是相对路径，先尝试相对于项目根目录
        # 如果环境变量是旧路径 "node_config.json"，自动转换为新路径
        if _config_file_env == "node_config.json":
            CONFIG_FILE = os.path.join(PROJECT_ROOT, "config", "node_config.json")
        else:
            # 其他相对路径，相对于项目根目录
            CONFIG_FILE = os.path.join(PROJECT_ROOT, _config_file_env)
else:
    # 默认路径：config/node_config.json
    CONFIG_FILE = os.path.join(PROJECT_ROOT, "config", "node_config.json")

# 调试信息：打印配置路径
print(f"🔧 PROJECT_ROOT: {PROJECT_ROOT}")
print(f"🔧 CONFIG_FILE: {CONFIG_FILE}")
print(f"🔧 Config file exists: {os.path.exists(CONFIG_FILE)}")
if not os.path.exists(CONFIG_FILE):
    # 如果文件不存在，尝试查找旧位置（向后兼容）
    old_config = os.path.join(PROJECT_ROOT, "node_config.json")
    if os.path.exists(old_config):
        print(f"⚠️  Found config at old location: {old_config}")
        print(f"⚠️  Please move it to: {CONFIG_FILE}")
        CONFIG_FILE = old_config
node_config = {}
model_patterns = {}
model_name_mapping = {}
default_model_size = 7
config_data = {}  # 保存完整的配置數據

def resolve_env_var(value: str) -> str:
    """解析環境變量引用，支持 ${VAR} 格式"""
    if not isinstance(value, str):
        return value
    # 匹配 ${VAR} 格式
    pattern = r'\$\{([^}]+)\}'
    def replace_var(match):
        var_name = match.group(1)
        return os.getenv(var_name, match.group(0))  # 如果環境變量不存在，返回原字符串
    return re.sub(pattern, replace_var, value)

def resolve_config_values(config: Dict) -> Dict:
    """遞歸解析配置中的環境變量引用"""
    if isinstance(config, dict):
        return {k: resolve_config_values(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [resolve_config_values(item) for item in config]
    elif isinstance(config, str):
        return resolve_env_var(config)
    else:
        return config

def load_config():
    """加載節點配置文件"""
    global node_config, model_patterns, model_name_mapping, default_model_size, config_data, NODES
    try:
        print(f"📂 Loading config from: {CONFIG_FILE}")
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
            print(f"   ✅ Config file loaded, found {len(config_data.get('nodes', []))} nodes in config")
            # 解析環境變量引用
            config_data = resolve_config_values(config_data)
            print(f"   ✅ Environment variables resolved")
            
            node_config = {node["name"]: node for node in config_data.get("nodes", [])}
            model_patterns = config_data.get("model_name_patterns", {})
            model_name_mapping = config_data.get("model_name_mapping", {})
            default_model_size = config_data.get("default_model_size_b", 7)
            
            # 從配置文件構建 NODES 列表
            NODES.clear()
            nodes_list = config_data.get("nodes", [])
            print(f"   📋 Processing {len(nodes_list)} nodes...")
            for node_cfg in nodes_list:
                node_type = node_cfg.get("type", "local")
                if node_type == "external":
                    # 外部節點
                    node = {
                        "name": node_cfg["name"],
                        "type": "external",
                        "api_url": node_cfg.get("api_url"),
                        "api_key": node_cfg.get("api_key", ""),
                        "timeout_seconds": node_cfg.get("timeout_seconds", 300),
                        "headers": node_cfg.get("headers", {}),
                        "weight": 1.0,
                        "enabled": node_cfg.get("enabled", True),
                        "config": node_cfg,  # 保存完整配置
                    }
                else:
                    # 本地節點（保持向後兼容，如果配置文件中沒有 hosts，使用硬編碼的默認值）
                    # 默認節點配置（根據 GATEWAY_README.md）
                    default_hosts = {
                        "node1": ["192.168.50.158", "m3max", "m3max.local", "m3max-128gb.local"],
                        "node2": ["192.168.50.31", "m1max", "m1max.local", "m1max-64gb.local"],
                        "node3": ["192.168.50.94", "m1", "m1.local", "m1-16gb.local"],
                        "node4": ["192.168.50.155", "i7", "i74080.local", "i7g13-4080-32gb.local"],
                    }
                    
                    node_name = node_cfg["name"]
                    hosts = node_cfg.get("hosts", default_hosts.get(node_name, []))
                    
                    node = {
                        "name": node_name,
                        "type": "local",
                        "hosts": hosts,
                        "port": node_cfg.get("port", 11434),
                        "weight": node_cfg.get("weight", 1.0),
                        "enabled": node_cfg.get("enabled", True),
                        "config": node_cfg,
                    }
                NODES.append(node)
                print(f"      ✅ Added node: {node['name']} (type: {node.get('type', 'local')})")
            
            print(f"   📊 Total nodes in NODES: {len(NODES)}")
            # 重新初始化節點狀態（只為新節點）
            for node in NODES:
                if node["name"] not in node_stats:
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
                else:
                    # 更新現有節點的權重
                    node_stats[node["name"]]["current_weight"] = node["weight"]
                    node_stats[node["name"]]["effective_weight"] = node["weight"]
            
            # 移除已刪除的節點
            node_names = {node["name"] for node in NODES}
            for node_name in list(node_stats.keys()):
                if node_name not in node_names:
                    del node_stats[node_name]
                    del node_models[node_name]
            
        print(f"✅ Loaded node configuration from {CONFIG_FILE}")
        local_nodes = sum(1 for n in NODES if n.get("type") == "local")
        external_nodes = sum(1 for n in NODES if n.get("type") == "external")
        print(f"   📊 {len(NODES)} nodes total: {local_nodes} local, {external_nodes} external")
        if len(NODES) > 0:
            print(f"   📋 Node names: {[n['name'] for n in NODES]}")
        else:
            print(f"   ⚠️  WARNING: NODES list is empty after loading config!")
        return True
    except FileNotFoundError:
        print(f"⚠️  Warning: Config file {CONFIG_FILE} not found, using default configuration")
        config_data = {
            "nodes": [],
            "model_name_patterns": {},
            "model_name_mapping": {},
            "default_model_size_b": 7
        }
        NODES.clear()  # 確保清空
        return False
    except Exception as e:
        print(f"❌ Error loading config file: {e}")
        import traceback
        traceback.print_exc()
        NODES.clear()  # 確保清空
        return False

def save_config(new_config: dict) -> Tuple[bool, str]:
    """保存節點配置文件"""
    try:
        # 驗證配置格式
        if not isinstance(new_config, dict):
            return False, "配置必須是 JSON 對象"
        
        # 創建備份
        backups_dir = os.path.join(PROJECT_ROOT, "backups")
        os.makedirs(backups_dir, exist_ok=True)
        backup_filename = f"{os.path.basename(CONFIG_FILE)}.backup.{int(time.time())}"
        backup_file = os.path.join(backups_dir, backup_filename)
        if os.path.exists(CONFIG_FILE):
            import shutil
            shutil.copy2(CONFIG_FILE, backup_file)
            print(f"📦 Created backup: {backup_file}")
        
        # 保存新配置
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_config, f, indent=2, ensure_ascii=False)
        
        # 重新加載配置
        if load_config():
            # 打印配置摘要
            nodes_count = len(node_config)
            patterns_count = len(model_patterns)
            mappings_count = len(model_name_mapping)
            print(f"📊 配置已生效: {nodes_count} 個節點, {patterns_count} 個模式, {mappings_count} 個映射")
            return True, f"✅ 配置已保存並立即生效（備份: {os.path.basename(backup_file)}）"
        else:
            return False, "配置已保存但重新加載失敗"
    except Exception as e:
        return False, f"保存配置時發生錯誤: {str(e)}"

# 節點配置（將從配置文件動態加載，必須在 load_config() 之前定義）
NODES: List[Dict] = []

# 節點狀態追蹤（必須在 load_config() 之前定義，因為 load_config() 會使用它們）
node_stats: Dict[str, Dict] = {}
node_models: Dict[str, Set[str]] = {}

# 初始加載配置
load_config()

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

# 調度策略類型
SCHEDULING_STRATEGY = os.getenv("SCHEDULING_STRATEGY", "round_robin")  # round_robin, least_connections, weighted_round_robin

# 節點狀態追蹤（已在 load_config() 之前定義，這裡只是註釋說明）
# node_stats 和 node_models 已在上面定義

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
            print(f"  Node {node_name} rejected: model '{model_name}' not found on node")
            continue
        
        # 第二步：檢查節點硬件是否適合該模型大小
        if not is_node_suitable_for_model(node_name, model_size_b):
            # 獲取節點的配置範圍以便調試
            node_cfg = node_config.get(node_name, {})
            ranges = node_cfg.get("supported_model_ranges", [])
            print(f"  Node {node_name} rejected: model size {model_size_b}B not in supported range {ranges}")
            continue
        
        # 第三步：檢查節點是否啟用且健康
        if not node.get("enabled", True):
            print(f"  Node {node_name} rejected: disabled")
            continue
        if not node_stats[node_name]["is_healthy"]:
            print(f"  Node {node_name} rejected: unhealthy")
            continue
        
        print(f"  ✓ Node {node_name} accepted for model {model_name} ({model_size_b}B)")
        filtered.append(node)
    
    return filtered


def select_node(model_name: Optional[str] = None, model_size_b: Optional[int] = None) -> Optional[Dict]:
    """根據調度策略選擇節點，支持模型感知的節點選擇"""
    # 如果提供了模型信息，先過濾節點
    candidate_nodes = NODES
    if model_name and model_size_b is not None:
        print(f"🔍 Filtering nodes for model '{model_name}' ({model_size_b}B)...")
        candidate_nodes = filter_nodes_by_model(NODES, model_name, model_size_b)
        print(f"   Found {len(candidate_nodes)} suitable node(s) after filtering")
        # 如果過濾後沒有節點，回退到所有節點（允許模型下載）
        if not candidate_nodes:
            print(f"⚠️  Warning: No suitable nodes found for model {model_name} ({model_size_b}B), falling back to all healthy nodes")
            candidate_nodes = [n for n in NODES if n.get("enabled", True) and node_stats[n["name"]]["is_healthy"]]
            print(f"   Fallback: Using {len(candidate_nodes)} healthy node(s): {[n['name'] for n in candidate_nodes]}")
    
    # 根據調度策略選擇
    if SCHEDULING_STRATEGY == "least_connections":
        return NodeSelector.least_connections(candidate_nodes)
    elif SCHEDULING_STRATEGY == "weighted_round_robin":
        return NodeSelector.weighted_round_robin(candidate_nodes)
    else:  # 默認使用 round_robin
        return NodeSelector.round_robin(candidate_nodes)


def get_node_url(node: Dict) -> str:
    """獲取節點的完整URL"""
    node_type = node.get("type", "local")
    if node_type == "external":
        # 外部節點使用 api_url
        api_url = node.get("api_url", "")
        # 確保 URL 以 / 結尾（如果需要的話）
        if api_url and not api_url.endswith("/"):
            return api_url
        return api_url
    else:
        # 本地節點使用 hosts 和 port
        hosts = node.get("hosts", [])
        if not hosts:
            raise ValueError(f"Local node {node.get('name')} has no hosts configured")
        port = node.get("port", 11434)
        return f"http://{hosts[0]}:{port}"


def get_node_headers(node: Dict) -> Dict[str, str]:
    """獲取節點的請求頭（包括 API key）"""
    headers = {}
    node_type = node.get("type", "local")
    
    if node_type == "external":
        # 外部節點：添加配置的 headers
        config_headers = node.get("headers", {})
        headers.update(config_headers)
        
        # 如果有 api_key，添加到 Authorization header（如果還沒有設置）
        api_key = node.get("api_key", "")
        if api_key and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {api_key}"
    
    return headers

async def get_node_models(node: Dict) -> Set[str]:
    """獲取節點上已下載的模型列表（只返回模型名，不含tag）"""
    try:
        base_url = get_node_url(node)
        url = f"{base_url}/api/tags"
        
        # 構建請求頭
        headers = get_node_headers(node)
        
        # 設置超時
        timeout_seconds = node.get("timeout_seconds", 5.0) if node.get("type") == "external" else 5.0
        timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                models = set()
                for model_info in data.get("models", []):
                    model_name = model_info.get("name", "")
                    if not model_name:
                        continue
                    # 移除版本標籤，只保留模型名（用於節點過濾）
                    # 例如 "qwen2.5-coder:30b" -> "qwen2.5-coder"
                    if ":" in model_name:
                        model_name = model_name.split(":")[0]
                    models.add(model_name)
                print(f"  ✓ {node['name']}: Found {len(models)} models: {sorted(models)}")
                return models
    except Exception as e:
        print(f"  ❌ Failed to get models from {node['name']}: {e}")
    return set()


async def health_check_node(node: Dict) -> bool:
    """健康檢查節點並同步模型列表"""
    try:
        base_url = get_node_url(node)
        url = f"{base_url}/api/tags"
        
        # 構建請求頭
        headers = get_node_headers(node)
        
        # 設置超時
        timeout_seconds = node.get("timeout_seconds", 5.0) if node.get("type") == "external" else 5.0
        timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
            is_healthy = response.status_code == 200
            node_stats[node["name"]]["is_healthy"] = is_healthy
            node_stats[node["name"]]["last_health_check"] = time.time()
            node_health.labels(node=node["name"]).set(1 if is_healthy else 0)
            
            # 同步模型列表
            if is_healthy:
                print(f"🔄 Syncing models from {node['name']}...")
                models = await get_node_models(node)
                old_count = len(node_models.get(node["name"], set()))
                node_models[node["name"]] = models
                new_count = len(models)
                node_stats[node["name"]]["last_model_sync"] = time.time()
                if old_count != new_count:
                    print(f"  📊 {node['name']}: Model count changed from {old_count} to {new_count}")
            
            return is_healthy
    except Exception as e:
        print(f"❌ Health check failed for {node['name']}: {e}")
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
    print("🚀 Starting Ollama Gateway...")
    
    # 初始化metrics
    for node in NODES:
        active_connections.labels(node=node["name"]).set(0)
        node_health.labels(node=node["name"]).set(0)
    
    # 啟動健康檢查任務
    asyncio.create_task(periodic_health_check())
    
    # 立即執行一次健康檢查和模型同步
    print("🔄 Performing initial health check and model sync...")
    for node in NODES:
        if node.get("enabled", True):
            await health_check_node(node)
    
    # 打印初始模型統計
    total_models = sum(len(models) for models in node_models.values())
    print(f"✅ Gateway started. Total unique models across all nodes: {total_models}")
    for node_name, models in node_models.items():
        if models:
            print(f"   {node_name}: {len(models)} models")


@app.on_event("shutdown")
async def shutdown_event():
    """關閉時清理資源"""
    await client.aclose()


async def proxy_request(request: Request, path: str):
    """代理請求到選定的節點"""
    # 處理 OPTIONS 請求（CORS preflight）- 直接返回，不轉發到後端
    if request.method == "OPTIONS":
        return Response(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Max-Age": "3600",
            }
        )
    
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
    
    # 特殊處理：/api/tags 請求應該已經被上面的路由處理了，這裡不應該到達
    # 但為了安全，我們還是檢查一下
    if path == "/api/tags" or path == "api/tags":
        # 這不應該發生，因為 /api/tags 已經有專門的路由
        # 但如果到達這裡，我們返回所有節點的聚合列表
        pass
    
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
        print(f"📝 Request for model: {display_name} ({model_size_b}B)")
    else:
        # 沒有模型名稱的請求（如 /api/tags, /api/version 等）
        print(f"📝 Request without model: {path}")
    
    # 選擇節點（基於模型信息）
    # 如果沒有模型名稱，select_node 會返回所有健康節點
    node = select_node(model_name, model_size_b)
    if not node:
        raise HTTPException(status_code=503, detail="No healthy nodes available")
    
    node_name = node["name"]
    node_url = get_node_url(node)
    target_url = f"{node_url}{path}"
    
    # 打印轉發信息
    display_name = full_model_name if full_model_name else model_name
    if display_name:
        print(f"→ Forwarding request to {node_name} ({node_url}) for model: {display_name}")
    else:
        print(f"→ Forwarding request to {node_name} ({node_url}) for path: {path}")
    
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
        headers.pop("connection", None)
        headers.pop("keep-alive", None)
        headers.pop("transfer-encoding", None)
        
        # 如果是外部節點，添加節點的 headers（包括 API key）
        node_headers = get_node_headers(node)
        headers.update(node_headers)
        
        # 使用之前讀取的body
        body = body_bytes
        
        # 轉發請求
        params = dict(request.query_params)
        
        # 設置超時（外部節點可能有不同的超時設置）
        timeout_seconds = node.get("timeout_seconds", 300.0) if node.get("type") == "external" else 300.0
        timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        
        try:
            # 為外部節點創建新的客戶端（使用自定義超時），本地節點使用全局客戶端
            if node.get("type") == "external":
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as external_client:
                    response = await external_client.request(
                        method=method,
                        url=target_url,
                        headers=headers,
                        content=body,
                        params=params,
                    )
            else:
                response = await client.request(
                    method=method,
                    url=target_url,
                    headers=headers,
                    content=body,
                    params=params,
                )
        except httpx.RequestError as e:
            print(f"❌ Request error to {node_name} ({target_url}): {e}")
            raise
        
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
        
        # 過濾響應頭，移除不應該傳遞的headers
        response_headers = {}
        skip_headers = {
            "content-length", "transfer-encoding", "connection", 
            "keep-alive", "proxy-authenticate", "proxy-authorization",
            "te", "trailer", "upgrade"
        }
        for key, value in response.headers.items():
            if key.lower() not in skip_headers:
                response_headers[key] = value
        
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
                headers=response_headers,
                media_type=response.headers.get("content-type", "text/event-stream")
            )
        else:
            # 普通響應
            content = await response.aread()
            node_stats[node_name]["active_connections"] -= 1
            active_connections.labels(node=node_name).set(node_stats[node_name]["active_connections"])
            
            # 確保 content-type 正確設置
            content_type = response.headers.get("content-type", "application/json")
            
            return Response(
                content=content,
                status_code=status_code,
                headers=response_headers,
                media_type=content_type
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
        
        import traceback
        error_details = traceback.format_exc()
        print(f"❌ Error proxying to {node_name} ({target_url}): {e}")
        print(f"   Path: {path}, Method: {method}")
        print(f"   Error details: {error_details}")
        raise HTTPException(
            status_code=502, 
            detail=f"Error proxying to {node_name}: {str(e)}"
        )


# 根路徑顯示儀表板（包含運行中的進程）（必須在通配符路由之前）
@app.get("/", response_class=HTMLResponse)
async def root():
    """根路徑，顯示儀表板頁面（包含運行中的進程）"""
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
                    max-width: 1400px;
                    margin: 20px auto;
                    padding: 20px;
                    background: #f5f7fa;
                }
                h1 { color: #2563eb; }
                h2 { color: #374151; margin-top: 30px; }
                .endpoint {
                    background: white;
                    padding: 15px;
                    margin: 10px 0;
                    border-radius: 8px;
                    border-left: 4px solid #2563eb;
                }
                .nodes-ps {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 15px;
                    margin-top: 20px;
                }
                .node-card {
                    background: white;
                    padding: 15px;
                    border-radius: 8px;
                    border-left: 4px solid #10b981;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                }
                .node-card.error {
                    border-left-color: #ef4444;
                }
                .node-card h3 {
                    margin: 0 0 10px 0;
                    color: #1e40af;
                    font-size: 16px;
                }
                .process-item {
                    background: #f8f9fa;
                    padding: 10px;
                    margin: 8px 0;
                    border-radius: 6px;
                    border-left: 3px solid #3b82f6;
                }
                .process-item strong {
                    color: #1e40af;
                    display: block;
                    margin-bottom: 5px;
                }
                .process-detail {
                    font-size: 12px;
                    color: #6b7280;
                    margin: 3px 0;
                }
                .loading {
                    color: #6b7280;
                    font-style: italic;
                }
                .error-msg {
                    color: #ef4444;
                    font-size: 14px;
                }
                .refresh-btn {
                    background: #2563eb;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    border-radius: 6px;
                    cursor: pointer;
                    font-size: 14px;
                    margin: 10px 0;
                }
                .refresh-btn:hover {
                    background: #1d4ed8;
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
                .status-badge {
                    display: inline-block;
                    padding: 2px 8px;
                    border-radius: 12px;
                    font-size: 11px;
                    font-weight: 600;
                    margin-left: 8px;
                }
                .status-running {
                    background: #d1fae5;
                    color: #065f46;
                }
                .status-idle {
                    background: #f3f4f6;
                    color: #6b7280;
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
                <h3>🎯 <a href="/routing">模型路由查看器</a></h3>
                <p>查看模型分配规则和查询模型会路由到哪些节点</p>
                <code>GET /routing</code>
            </div>
            
            <div class="endpoint">
                <h3>⚙️ <a href="/config">節點配置編輯器</a></h3>
                <p>通過網頁界面編輯 node_config.json 配置文件</p>
                <code>GET /config</code>
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
            
            <h2>🔄 運行中的進程 <span id="refresh-status" style="font-size: 12px; color: #6b7280; font-weight: normal;"></span></h2>
            <button class="refresh-btn" onclick="loadNodesPS(true)">刷新</button>
            <div id="nodes-ps" class="nodes-ps">
                <div class="loading">正在加載...</div>
            </div>
            
            <script>
                let isFirstLoad = true;
                let nodeCards = {};
                
                function formatBytes(bytes) {
                    if (!bytes || bytes === 0) return '0 B';
                    const k = 1024;
                    const sizes = ['B', 'KB', 'MB', 'GB'];
                    const i = Math.floor(Math.log(bytes) / Math.log(k));
                    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
                }
                
                function formatDuration(seconds) {
                    if (!seconds) return '0s';
                    const hours = Math.floor(seconds / 3600);
                    const minutes = Math.floor((seconds % 3600) / 60);
                    const secs = Math.floor(seconds % 60);
                    if (hours > 0) {
                        return `${hours}h ${minutes}m ${secs}s`;
                    } else if (minutes > 0) {
                        return `${minutes}m ${secs}s`;
                    } else {
                        return `${secs}s`;
                    }
                }
                
                function updateRefreshStatus(text) {
                    const statusEl = document.getElementById('refresh-status');
                    if (statusEl) {
                        statusEl.textContent = text;
                        setTimeout(() => {
                            if (statusEl.textContent === text) {
                                statusEl.textContent = '';
                            }
                        }, 2000);
                    }
                }
                
                function createNodeCard(nodeName, nodeData) {
                    const card = document.createElement('div');
                    card.className = 'node-card';
                    card.id = `node-card-${nodeName}`;
                    
                    // 檢查是否有錯誤或無法獲取數據
                    // 檢查是否是外部節點且不支持 /api/ps（這是正常的）
                    const isExternalNoPS = nodeData.error && (nodeData.error.includes('does not support /api/ps') || nodeData.error.includes('External API'));
                    
                    if (nodeData.error || (!nodeData.ps && nodeData.error !== null)) {
                        card.classList.add('error');
                        // 對於外部節點不支持 /api/ps 的情況，使用藍色邊框表示這是信息而非錯誤
                        if (isExternalNoPS) {
                            card.style.borderLeftColor = '#3b82f6';
                        }
                        const errorMsg = nodeData.error || '無法獲取數據';
                        const url = nodeData.url || 'N/A';
                        card.innerHTML = `
                            <h3>${nodeName.toUpperCase()}</h3>
                            <div class="error-msg" style="${isExternalNoPS ? 'color: #3b82f6;' : ''}">${errorMsg}</div>
                            <div class="process-detail">URL: ${url}</div>
                            ${isExternalNoPS ? '<div class="process-detail" style="color: #6b7280; font-size: 12px; margin-top: 8px;">ℹ️ 外部 API 服務通常不支持進程查詢端點，這是正常現象</div>' : ''}
                        `;
                    } else {
                        // 兼容兩種格式：標準的 processes 和可能的 models 格式
                        let processes = [];
                        if (nodeData.ps.processes) {
                            // 標準格式：{"processes": [...]}
                            processes = nodeData.ps.processes;
                        } else if (nodeData.ps.models) {
                            // 兼容格式：{"models": [...]} - 這些是已加載到內存的模型，不是運行中的進程
                            // 將 models 轉換為顯示格式
                            processes = nodeData.ps.models.map(model => ({
                                model: model.name || model.model,
                                loaded: true,
                                size: model.size,
                                size_vram: model.size_vram,
                                expires_at: model.expires_at,
                                parameter_size: model.details?.parameter_size,
                                context_length: model.context_length
                            }));
                        }
                        
                        const statusClass = processes.length > 0 ? 'status-running' : 'status-idle';
                        const statusText = processes.length > 0 ? `${processes.length} ${processes[0]?.loaded ? '已加載' : '運行中'}` : '空閒';
                        
                        let processesHTML = '';
                        if (processes.length === 0) {
                            processesHTML = '<div class="process-detail" style="color: #6b7280; font-style: italic;">目前沒有運行中的進程<br><small>注意：只顯示正在處理的請求，已完成的請求不會顯示</small></div>';
                        } else {
                            processes.forEach(proc => {
                                if (proc.loaded) {
                                    // 已加載的模型（不是運行中的進程）
                                    processesHTML += `
                                        <div class="process-item" style="border-left-color: #3b82f6;">
                                            <strong>${proc.model || 'Unknown'}</strong>
                                            <div class="process-detail" style="color: #6b7280; font-size: 11px;">已加載到內存（非運行中進程）</div>
                                            ${proc.parameter_size ? `<div class="process-detail">參數大小: ${proc.parameter_size}</div>` : ''}
                                            ${proc.size_vram ? `<div class="process-detail">VRAM 使用: ${formatBytes(proc.size_vram)}</div>` : ''}
                                            ${proc.context_length ? `<div class="process-detail">上下文長度: ${proc.context_length.toLocaleString()}</div>` : ''}
                                            ${proc.expires_at ? `<div class="process-detail">過期時間: ${new Date(proc.expires_at).toLocaleString()}</div>` : ''}
                                        </div>
                                    `;
                                } else {
                                    // 運行中的進程
                                    processesHTML += `
                                        <div class="process-item">
                                            <strong>${proc.model || 'Unknown'}</strong>
                                            <div class="process-detail">進程 ID: ${proc.pid || 'N/A'}</div>
                                            <div class="process-detail">創建時間: ${proc.created_at ? new Date(proc.created_at).toLocaleString() : 'N/A'}</div>
                                            ${proc.prompt_eval_count ? `<div class="process-detail">Prompt Tokens: ${proc.prompt_eval_count}</div>` : ''}
                                            ${proc.eval_count ? `<div class="process-detail">Completion Tokens: ${proc.eval_count}</div>` : ''}
                                            ${proc.total_duration ? `<div class="process-detail">總時長: ${formatDuration(proc.total_duration / 1e9)}</div>` : ''}
                                            ${proc.load_duration ? `<div class="process-detail">加載時長: ${formatDuration(proc.load_duration / 1e9)}</div>` : ''}
                                            ${proc.prompt_eval_duration ? `<div class="process-detail">Prompt 處理: ${formatDuration(proc.prompt_eval_duration / 1e9)}</div>` : ''}
                                            ${proc.eval_duration ? `<div class="process-detail">生成時長: ${formatDuration(proc.eval_duration / 1e9)}</div>` : ''}
                                        </div>
                                    `;
                                }
                            });
                        }
                        
                        card.innerHTML = `
                            <h3>${nodeName.toUpperCase()} <span class="status-badge ${statusClass}">${statusText}</span></h3>
                            <div class="process-detail" style="margin-bottom: 10px;">URL: ${nodeData.url}</div>
                            ${processesHTML}
                        `;
                    }
                    
                    return card;
                }
                
                async function loadNodesPS(manualRefresh = false) {
                    const container = document.getElementById('nodes-ps');
                    
                    // 只在首次加載時顯示加載狀態
                    if (isFirstLoad) {
                        container.innerHTML = '<div class="loading">正在加載...</div>';
                        isFirstLoad = false;
                    } else if (manualRefresh) {
                        updateRefreshStatus('刷新中...');
                    }
                    
                    try {
                        const response = await fetch('/nodes/ps');
                        if (!response.ok) {
                            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                        }
                        const data = await response.json();
                        
                        console.log('Nodes PS data:', data); // 調試用
                        
                        // 如果是首次加載，清空容器
                        if (!nodeCards || Object.keys(nodeCards).length === 0) {
                            container.innerHTML = '';
                        }
                        
                        // 檢查是否有數據
                        if (!data || Object.keys(data).length === 0) {
                            if (isFirstLoad) {
                                container.innerHTML = '<div class="error-msg">沒有找到任何節點配置</div>';
                            } else {
                                updateRefreshStatus('沒有節點數據');
                            }
                            return;
                        }
                        
                        // 更新或創建每個節點的卡片
                        for (const [nodeName, nodeData] of Object.entries(data)) {
                            const cardId = `node-card-${nodeName}`;
                            let card = document.getElementById(cardId);
                            
                            if (!card) {
                                // 如果卡片不存在，創建新的
                                card = createNodeCard(nodeName, nodeData);
                                container.appendChild(card);
                                nodeCards[nodeName] = card;
                            } else {
                                // 如果卡片已存在，更新內容（平滑更新）
                                const newCard = createNodeCard(nodeName, nodeData);
                                card.replaceWith(newCard);
                                nodeCards[nodeName] = newCard;
                            }
                        }
                        
                        if (manualRefresh) {
                            updateRefreshStatus('已更新');
                        }
                    } catch (error) {
                        console.error('Error loading nodes PS:', error);
                        if (isFirstLoad) {
                            container.innerHTML = `<div class="error-msg">加載失敗: ${error.message}<br><small>請檢查瀏覽器控制台獲取詳細信息</small></div>`;
                        } else {
                            updateRefreshStatus('刷新失敗: ' + error.message);
                        }
                    }
                }
                
                // 頁面加載時自動獲取
                loadNodesPS();
                
                // 每 5 秒自動背景刷新（不顯示加載狀態）
                setInterval(() => loadNodesPS(false), 5000);
            </script>
        </body>
        </html>
        """
    return HTMLResponse(content=welcome_html)


# 拓撲可視化頁面（必須在通配符路由之前）
@app.get("/topology", response_class=HTMLResponse)
async def topology_viewer():
    """3D 網絡拓撲可視化頁面"""
    try:
        html_file = os.path.join(PROJECT_ROOT, "static", "topology-3d.html")
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


# 節點狀態端點（JSON API）
@app.get("/api/nodes")
async def get_nodes_api():
    """獲取所有節點狀態（JSON API）"""
    # 如果 NODES 為空，嘗試重新加載配置
    if not NODES:
        print("⚠️  Warning: NODES list is empty in /api/nodes, attempting to reload config...")
        load_config()
        if not NODES:
            print("❌ Error: NODES list is still empty after reload in /api/nodes")
            print(f"   Config file path: {CONFIG_FILE}")
            print(f"   Config file exists: {os.path.exists(CONFIG_FILE)}")
            return {
                "scheduling_strategy": SCHEDULING_STRATEGY,
                "nodes": [],
                "_error": "No nodes configured",
                "_config_file": CONFIG_FILE,
                "_config_file_exists": os.path.exists(CONFIG_FILE),
            }
    
    nodes_info = []
    for node in NODES:
        # 確保節點狀態已初始化
        if node["name"] not in node_stats:
            node_stats[node["name"]] = {
                "active_connections": 0,
                "total_requests": 0,
                "failed_requests": 0,
                "last_health_check": None,
                "is_healthy": False,
                "current_weight": node.get("weight", 1.0),
                "effective_weight": node.get("weight", 1.0),
                "last_model_sync": None,
            }
        if node["name"] not in node_models:
            node_models[node["name"]] = set()
        
        node_info = {
            "name": node["name"],
            "type": node.get("type", "local"),
            "weight": node.get("weight", 1.0),
            "enabled": node.get("enabled", True),
            "stats": node_stats[node["name"]],
            "models": list(node_models.get(node["name"], set())),
            "config": node_config.get(node["name"], {}),
        }
        if node.get("type") == "external":
            node_info["api_url"] = node.get("api_url")
        else:
            node_info["hosts"] = node.get("hosts", [])
            node_info["port"] = node.get("port", 11434)
        nodes_info.append(node_info)
    
    print(f"📊 /api/nodes returning {len(nodes_info)} nodes: {[n['name'] for n in nodes_info]}")
    return {
        "scheduling_strategy": SCHEDULING_STRATEGY,
        "nodes": nodes_info
    }

# 節點狀態端點（HTML 頁面）
@app.get("/nodes", response_class=HTMLResponse)
async def get_nodes():
    """節點狀態頁面"""
    html_content = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>節點狀態 - Ollama Gateway</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
            background: #f5f7fa;
            padding: 20px;
        }
        .container {
            max-width: 1600px;
            margin: 0 auto;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 20px;
            text-align: center;
        }
        .header h1 {
            font-size: 28px;
            margin-bottom: 10px;
        }
        .toolbar {
            padding: 20px;
            background: white;
            border-radius: 12px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            align-items: center;
        }
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.2s;
        }
        .btn-primary {
            background: #2563eb;
            color: white;
        }
        .btn-primary:hover {
            background: #1d4ed8;
        }
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            margin: 2px;
        }
        .status-healthy {
            background: #d1fae5;
            color: #065f46;
        }
        .status-unhealthy {
            background: #fee2e2;
            color: #991b1b;
        }
        .status-enabled {
            background: #dbeafe;
            color: #1e40af;
        }
        .status-disabled {
            background: #f3f4f6;
            color: #6b7280;
        }
        .status-external {
            background: #fef3c7;
            color: #92400e;
        }
        .nodes-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
        }
        .node-card {
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            border-left: 4px solid #10b981;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .node-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }
        .node-card.unhealthy {
            border-left-color: #ef4444;
        }
        .node-card.external {
            border-left-color: #f59e0b;
        }
        .node-card.disabled {
            border-left-color: #9ca3af;
            opacity: 0.7;
        }
        .node-card h3 {
            color: #1e40af;
            margin-bottom: 15px;
            font-size: 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .node-info {
            margin: 10px 0;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 6px;
        }
        .node-info strong {
            color: #374151;
            display: block;
            margin-bottom: 5px;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .node-info .value {
            color: #1f2937;
            font-size: 14px;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
            margin-top: 15px;
        }
        .stat-item {
            background: #eff6ff;
            padding: 10px;
            border-radius: 6px;
            text-align: center;
        }
        .stat-item .label {
            font-size: 11px;
            color: #6b7280;
            margin-bottom: 5px;
        }
        .stat-item .value {
            font-size: 18px;
            font-weight: 600;
            color: #2563eb;
        }
        .models-list {
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #e5e7eb;
        }
        .models-list strong {
            display: block;
            margin-bottom: 8px;
            color: #374151;
            font-size: 13px;
        }
        .models-tags {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }
        .model-tag {
            background: #e0e7ff;
            color: #3730a3;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 500;
        }
        .no-models {
            color: #9ca3af;
            font-size: 12px;
            font-style: italic;
        }
        .ranges-list {
            margin-top: 10px;
        }
        .range-item {
            background: #f0fdf4;
            padding: 6px 10px;
            margin: 5px 0;
            border-radius: 4px;
            font-size: 12px;
            color: #065f46;
        }
        .back-link {
            display: inline-block;
            margin-bottom: 20px;
            color: #2563eb;
            text-decoration: none;
            font-weight: 600;
        }
        .back-link:hover {
            text-decoration: underline;
        }
        .loading {
            text-align: center;
            padding: 40px;
            color: #6b7280;
        }
        .error-msg {
            background: #fee2e2;
            color: #991b1b;
            padding: 15px;
            border-radius: 8px;
            margin: 20px 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📡 節點狀態</h1>
            <p>查看所有節點的詳細信息和狀態</p>
        </div>
        
        <a href="/" class="back-link">← 返回首頁</a>
        
        <div class="toolbar">
            <button class="btn btn-primary" onclick="loadNodes()">🔄 刷新</button>
            <span id="status-text" style="color: #6b7280; font-size: 14px;"></span>
        </div>
        
        <div id="nodes-container" class="loading">正在加載節點信息...</div>
    </div>

    <script>
        async function loadNodes() {
            const container = document.getElementById('nodes-container');
            const statusText = document.getElementById('status-text');
            
            try {
                statusText.textContent = '正在加載...';
                const response = await fetch('/api/nodes');
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                const data = await response.json();
                
                console.log('Nodes data:', data); // 調試用
                
                if (!data.nodes || data.nodes.length === 0) {
                    container.innerHTML = '<div class="error-msg">沒有找到任何節點配置</div>';
                    statusText.textContent = '沒有節點';
                    return;
                }
                
                let html = '<div class="nodes-grid">';
                
                data.nodes.forEach(node => {
                    console.log('Processing node:', node.name, 'type:', node.type); // 調試用
                    const isHealthy = node.stats && node.stats.is_healthy;
                    const isEnabled = node.enabled !== false;
                    const isExternal = node.type === 'external';
                    
                    let cardClass = 'node-card';
                    if (!isEnabled) {
                        cardClass += ' disabled';
                    } else if (!isHealthy) {
                        cardClass += ' unhealthy';
                    } else if (isExternal) {
                        cardClass += ' external';
                    }
                    
                    // 構建地址信息
                    let addressInfo = '';
                    if (isExternal) {
                        addressInfo = `<div class="node-info">
                            <strong>API URL</strong>
                            <div class="value">${node.api_url || 'N/A'}</div>
                        </div>`;
                    } else if (node.hosts && node.hosts.length > 0) {
                        addressInfo = `<div class="node-info">
                            <strong>地址</strong>
                            <div class="value">${node.hosts[0]}:${node.port || 11434}</div>
                            ${node.hosts.length > 1 ? `<div style="font-size: 11px; color: #6b7280; margin-top: 4px;">其他: ${node.hosts.slice(1).join(', ')}</div>` : ''}
                        </div>`;
                    }
                    
                    // 構建配置信息
                    let configInfo = '';
                    if (node.config) {
                        const config = node.config;
                        if (config.description) {
                            configInfo += `<div class="node-info">
                                <strong>描述</strong>
                                <div class="value">${config.description}</div>
                            </div>`;
                        }
                        if (config.memory_gb) {
                            configInfo += `<div class="node-info">
                                <strong>內存</strong>
                                <div class="value">${config.memory_gb} GB</div>
                            </div>`;
                        }
                        if (config.supported_model_ranges && config.supported_model_ranges.length > 0) {
                            configInfo += `<div class="node-info">
                                <strong>支持的模型範圍</strong>
                                <div class="ranges-list">
                                    ${config.supported_model_ranges.map(range => {
                                        const min = range.min_params_b || 0;
                                        const max = range.max_params_b === null ? '∞' : range.max_params_b;
                                        return `<div class="range-item">${min}B ~ ${max}B${range.description ? ' (' + range.description + ')' : ''}</div>`;
                                    }).join('')}
                                </div>
                            </div>`;
                        }
                    }
                    
                    // 構建統計信息
                    const stats = node.stats || {};
                    const statsHtml = `
                        <div class="stats-grid">
                            <div class="stat-item">
                                <div class="label">活躍連接</div>
                                <div class="value">${stats.active_connections || 0}</div>
                            </div>
                            <div class="stat-item">
                                <div class="label">總請求數</div>
                                <div class="value">${stats.total_requests || 0}</div>
                            </div>
                            <div class="stat-item">
                                <div class="label">失敗請求</div>
                                <div class="value">${stats.failed_requests || 0}</div>
                            </div>
                            <div class="stat-item">
                                <div class="label">權重</div>
                                <div class="value">${node.weight || 1.0}</div>
                            </div>
                        </div>
                    `;
                    
                    // 構建模型列表
                    const models = node.models || [];
                    const modelsHtml = models.length > 0
                        ? `<div class="models-list">
                            <strong>已下載模型 (${models.length})</strong>
                            <div class="models-tags">
                                ${models.slice(0, 10).map(model => `<span class="model-tag">${model}</span>`).join('')}
                                ${models.length > 10 ? `<span class="model-tag">+${models.length - 10} 更多</span>` : ''}
                            </div>
                          </div>`
                        : `<div class="models-list">
                            <strong>已下載模型</strong>
                            <div class="no-models">暫無模型</div>
                          </div>`;
                    
                    html += `
                        <div class="${cardClass}">
                            <h3>
                                ${node.name.toUpperCase()}
                                <div>
                                    ${isExternal ? '<span class="status-badge status-external">外部</span>' : ''}
                                    <span class="status-badge ${isEnabled ? 'status-enabled' : 'status-disabled'}">${isEnabled ? '已啟用' : '已禁用'}</span>
                                    <span class="status-badge ${isHealthy ? 'status-healthy' : 'status-unhealthy'}">${isHealthy ? '健康' : '不健康'}</span>
                                </div>
                            </h3>
                            ${addressInfo}
                            ${configInfo}
                            ${statsHtml}
                            ${modelsHtml}
                        </div>
                    `;
                });
                
                html += '</div>';
                container.innerHTML = html;
                
                const localCount = data.nodes.filter(n => n.type === 'local').length;
                const externalCount = data.nodes.filter(n => n.type === 'external').length;
                statusText.textContent = `已加載 ${data.nodes.length} 個節點 (${localCount} 本地, ${externalCount} 外部) | 調度策略: ${data.scheduling_strategy} | 最後更新: ${new Date().toLocaleTimeString()}`;
                
            } catch (error) {
                console.error('Error loading nodes:', error);
                container.innerHTML = `<div class="error-msg">加載失敗: ${error.message}<br><small>請檢查瀏覽器控制台獲取詳細信息</small></div>`;
                statusText.textContent = '加載失敗';
            }
        }
        
        // 頁面加載時自動加載
        window.addEventListener('DOMContentLoaded', () => {
            loadNodes();
        });
        
        // 每 10 秒自動刷新
        setInterval(() => {
            loadNodes();
        }, 10000);
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


async def get_node_ps(node: Dict) -> Optional[Dict]:
    """獲取節點的運行中進程信息（/api/ps）"""
    # 外部節點可能不支持 /api/ps 端點，直接返回 None 並在調用處處理
    if node.get("type") == "external":
        # 對於外部節點，嘗試獲取但失敗時不報錯
        try:
            base_url = get_node_url(node)
            url = f"{base_url}/api/ps"
            headers = get_node_headers(node)
            
            timeout_seconds = node.get("timeout_seconds", 5.0)
            timeout = httpx.Timeout(timeout_seconds, connect=10.0)
            
            print(f"Fetching /api/ps from external node {node['name']}: {url}")
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    print(f"Got /api/ps from {node['name']}: {len(data.get('processes', []))} processes")
                    return data
                elif response.status_code == 404:
                    # 404 表示端點不存在，這是正常的（外部 API 可能不支持）
                    print(f"⚠️  External node {node['name']} does not support /api/ps endpoint (404)")
                    return None
                else:
                    print(f"⚠️  Failed to get /api/ps from {node['name']}: HTTP {response.status_code}")
                    return None
        except Exception as e:
            print(f"⚠️  External node {node['name']} /api/ps not available: {e}")
            return None
    
    # 本地節點
    try:
        base_url = get_node_url(node)
        url = f"{base_url}/api/ps"
        headers = get_node_headers(node)
        
        timeout = httpx.Timeout(5.0, connect=10.0)
        
        print(f"Fetching /api/ps from {node['name']}: {url}")
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                print(f"Got /api/ps from {node['name']}: {len(data.get('processes', []))} processes")
                return data
            else:
                print(f"Failed to get /api/ps from {node['name']}: HTTP {response.status_code}")
    except Exception as e:
        print(f"Failed to get /api/ps from {node['name']}: {e}")
    return None


# 診斷端點：查看配置狀態
@app.get("/debug/config")
async def debug_config():
    """診斷端點：查看配置加載狀態"""
    return {
        "config_file": CONFIG_FILE,
        "config_file_exists": os.path.exists(CONFIG_FILE),
        "config_file_path": os.path.abspath(CONFIG_FILE),
        "nodes_count": len(NODES),
        "nodes": [{"name": n["name"], "type": n.get("type", "local")} for n in NODES],
        "node_config_count": len(node_config),
        "node_config_keys": list(node_config.keys()),
        "config_data_nodes_count": len(config_data.get("nodes", [])),
    }

# 獲取所有節點的運行中進程信息
@app.get("/nodes/ps")
async def get_all_nodes_ps():
    """獲取所有節點的運行中進程信息"""
    result = {}
    
    # 如果 NODES 為空，嘗試重新加載配置
    if not NODES:
        print("⚠️  Warning: NODES list is empty, attempting to reload config...")
        load_config()
        if not NODES:
            print("❌ Error: NODES list is still empty after reload, no nodes configured")
            print(f"   Config file path: {CONFIG_FILE}")
            print(f"   Config file exists: {os.path.exists(CONFIG_FILE)}")
            return {
                "_error": "No nodes configured",
                "_config_file": CONFIG_FILE,
                "_config_file_exists": os.path.exists(CONFIG_FILE),
                "_config_file_path": os.path.abspath(CONFIG_FILE) if CONFIG_FILE else None,
            }
    
    for node in NODES:
        try:
            url = get_node_url(node)
        except (ValueError, KeyError) as e:
            # 如果無法構建 URL（例如缺少 hosts），使用錯誤信息
            url = f"Error: {str(e)}"
            print(f"⚠️  Warning: Cannot build URL for {node['name']}: {e}")
        
        # 確保節點狀態已初始化
        if node["name"] not in node_stats:
            node_stats[node["name"]] = {
                "active_connections": 0,
                "total_requests": 0,
                "failed_requests": 0,
                "last_health_check": None,
                "is_healthy": False,
                "current_weight": node.get("weight", 1.0),
                "effective_weight": node.get("weight", 1.0),
                "last_model_sync": None,
            }
        
        if not node.get("enabled", True):
            result[node["name"]] = {
                "url": url if isinstance(url, str) and not url.startswith("Error:") else "N/A",
                "ps": None,
                "error": "Node is disabled"
            }
        else:
            # 嘗試獲取進程信息（無論健康狀態如何）
            try:
                ps_data = await get_node_ps(node)
                # 對於外部節點，如果無法獲取進程信息，顯示友好提示
                if node.get("type") == "external" and not ps_data:
                    result[node["name"]] = {
                        "url": url if isinstance(url, str) and not url.startswith("Error:") else "N/A",
                        "ps": None,
                        "error": "External API does not support /api/ps endpoint (this is normal for cloud services)"
                    }
                else:
                    result[node["name"]] = {
                        "url": url if isinstance(url, str) and not url.startswith("Error:") else "N/A",
                        "ps": ps_data,
                        "error": None if ps_data else ("Node is not healthy" if not node_stats[node["name"]]["is_healthy"] else "Failed to fetch process data")
                    }
            except Exception as e:
                # 如果獲取失敗，仍然返回節點信息（帶錯誤）
                error_msg = f"Failed to fetch: {str(e)}"
                if node.get("type") == "external":
                    error_msg = "External API may not support /api/ps endpoint"
                result[node["name"]] = {
                    "url": url if isinstance(url, str) and not url.startswith("Error:") else "N/A",
                    "ps": None,
                    "error": error_msg
                }
    
    print(f"📊 Returning {len(result)} nodes for /nodes/ps")
    return result


async def get_node_loaded_models(node: Dict) -> List[str]:
    """獲取節點已加載到內存的模型列表"""
    try:
        base_url = get_node_url(node)
        url = f"{base_url}/api/ps"
        headers = get_node_headers(node)
        
        timeout_seconds = node.get("timeout_seconds", 5.0) if node.get("type") == "external" else 5.0
        timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                # 檢查是否有 models 字段（已加載的模型）
                if 'models' in data and isinstance(data['models'], list):
                    return [model.get('name') or model.get('model') for model in data['models'] if model.get('name') or model.get('model')]
    except Exception:
        pass
    return []


# 獲取所有節點的已加載模型
@app.get("/nodes/loaded-models")
async def get_all_nodes_loaded_models():
    """獲取所有節點已加載到內存的模型列表"""
    result = {}
    for node in NODES:
        if node.get("enabled", True) and node_stats[node["name"]]["is_healthy"]:
            models = await get_node_loaded_models(node)
            result[node["name"]] = {
                "models": models,
                "count": len(models)
            }
        else:
            result[node["name"]] = {
                "models": [],
                "count": 0
            }
    return result


# 獲取單個節點的所有已下載模型（通過 /api/tags）
async def get_node_tags(node: Dict) -> Dict:
    """獲取節點所有已下載的模型列表（通過 /api/tags）"""
    try:
        base_url = get_node_url(node)
        url = f"{base_url}/api/tags"
        headers = get_node_headers(node)
        
        timeout_seconds = node.get("timeout_seconds", 5.0) if node.get("type") == "external" else 5.0
        timeout = httpx.Timeout(timeout_seconds, connect=10.0)
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                return response.json()
            else:
                return {"models": []}
    except Exception as e:
        print(f"Error fetching tags from {node['name']}: {e}")
        return {"models": []}


@app.get("/nodes/{node_name}/tags")
async def get_node_tags_endpoint(node_name: str):
    """獲取指定節點的所有已下載模型"""
    node = next((n for n in NODES if n["name"] == node_name), None)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node {node_name} not found")
    
    if not node.get("enabled", True):
        raise HTTPException(status_code=400, detail=f"Node {node_name} is disabled")
    
    tags_data = await get_node_tags(node)
    return tags_data


# 聚合所有節點的模型列表（必須在通配符路由之前）
@app.get("/api/tags")
async def get_all_tags():
    """聚合所有節點的模型列表，返回統一的模型列表"""
    all_models = {}  # 使用字典來去重，key 是模型名，value 是模型信息
    all_models_list = []  # 最終返回的模型列表
    
    # 從所有健康節點獲取模型列表
    for node in NODES:
        if node.get("enabled", True) and node_stats[node["name"]]["is_healthy"]:
            try:
                tags_data = await get_node_tags(node)
                models = tags_data.get("models", [])
                
                for model_info in models:
                    model_name = model_info.get("name", "")
                    if not model_name:
                        continue
                    
                    # 如果模型不存在，或當前節點的模型信息更完整（有更多字段），則更新
                    if model_name not in all_models:
                        all_models[model_name] = model_info.copy()
                        # 添加節點信息，標記該模型在哪些節點可用
                        all_models[model_name]["_available_on_nodes"] = [node["name"]]
                    else:
                        # 模型已存在，添加節點信息
                        if node["name"] not in all_models[model_name].get("_available_on_nodes", []):
                            all_models[model_name]["_available_on_nodes"].append(node["name"])
                        
                        # 如果當前節點的模型信息更完整（有 size, modified_at 等），則更新
                        current_model = all_models[model_name]
                        if not current_model.get("size") and model_info.get("size"):
                            current_model["size"] = model_info["size"]
                        if not current_model.get("modified_at") and model_info.get("modified_at"):
                            current_model["modified_at"] = model_info["modified_at"]
                        if not current_model.get("digest") and model_info.get("digest"):
                            current_model["digest"] = model_info["digest"]
            except Exception as e:
                print(f"Error fetching tags from {node['name']} for aggregation: {e}")
                continue
    
    # 轉換為列表格式，移除內部使用的 _available_on_nodes 字段（或保留作為額外信息）
    for model_name, model_info in all_models.items():
        model_data = model_info.copy()
        # 可選：保留節點信息作為額外字段（如果客戶端需要知道模型在哪個節點）
        # model_data["available_on_nodes"] = model_data.pop("_available_on_nodes", [])
        # 或者移除內部字段，保持與 Ollama API 兼容
        model_data.pop("_available_on_nodes", None)
        all_models_list.append(model_data)
    
    # 按模型名稱排序
    all_models_list.sort(key=lambda x: x.get("name", ""))
    
    print(f"📦 Aggregated {len(all_models_list)} unique models from all nodes")
    
    return {"models": all_models_list}


# 模型路由查询 API
@app.get("/api/routing/query")
async def query_model_routing(model_name: str):
    """查询指定模型会路由到哪些节点"""
    try:
        # 提取模型信息
        full_model_name = model_name
        if ":" in model_name:
            base_name = model_name.split(":")[0]
        else:
            base_name = model_name
        
        # 计算模型大小
        model_size_b = get_model_size_b(base_name, full_model_name)
        
        # 获取所有可能的候选节点
        candidate_nodes = []
        rejected_nodes = []
        
        for node in NODES:
            node_name = node["name"]
            node_info = {
                "name": node_name,
                "type": node.get("type", "local"),
                "enabled": node.get("enabled", True),
                "healthy": node_stats[node_name]["is_healthy"],
                "has_model": base_name in node_models.get(node_name, set()),
                "suitable_for_size": is_node_suitable_for_model(node_name, model_size_b),
                "config": node_config.get(node_name, {}),
                "reasons": []
            }
            if node.get("type") == "external":
                node_info["api_url"] = node.get("api_url")
            else:
                node_info["hosts"] = node.get("hosts", [])
                node_info["port"] = node.get("port", 11434)
            
            # 检查各种条件
            if not node_info["enabled"]:
                node_info["reasons"].append("节点已禁用")
                rejected_nodes.append(node_info)
                continue
            
            if not node_info["healthy"]:
                node_info["reasons"].append("节点不健康")
                rejected_nodes.append(node_info)
                continue
            
            if not node_info["has_model"]:
                node_info["reasons"].append(f"节点上没有模型 '{base_name}'")
                rejected_nodes.append(node_info)
                continue
            
            if not node_info["suitable_for_size"]:
                node_cfg = node_config.get(node_name, {})
                ranges = node_cfg.get("supported_model_ranges", [])
                node_info["reasons"].append(f"模型大小 {model_size_b}B 不在支持范围内: {ranges}")
                rejected_nodes.append(node_info)
                continue
            
            # 所有条件都满足
            candidate_nodes.append(node_info)
        
        # 如果没有候选节点，显示回退节点
        fallback_nodes = []
        if not candidate_nodes:
            for node in NODES:
                if node.get("enabled", True) and node_stats[node["name"]]["is_healthy"]:
                    fallback_node = {
                        "name": node["name"],
                        "type": node.get("type", "local"),
                        "reason": "回退到所有健康节点（允许模型下载）"
                    }
                    if node.get("type") == "external":
                        fallback_node["api_url"] = node.get("api_url")
                    else:
                        fallback_node["hosts"] = node.get("hosts", [])
                        fallback_node["port"] = node.get("port", 11434)
                    fallback_nodes.append(fallback_node)
        
        return {
            "model_name": model_name,
            "base_name": base_name,
            "model_size_b": model_size_b,
            "size_detection": {
                "method": "从模型名称提取",
                "patterns_matched": [p for p in model_patterns.keys() if p.lower() in model_name.lower()],
                "mapping_matched": model_name_mapping.get(model_name) or model_name_mapping.get(base_name),
                "default_used": model_size_b == default_model_size
            },
            "candidate_nodes": candidate_nodes,
            "rejected_nodes": rejected_nodes,
            "fallback_nodes": fallback_nodes,
            "scheduling_strategy": SCHEDULING_STRATEGY,
            "will_use_fallback": len(candidate_nodes) == 0
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询路由时发生错误: {str(e)}")


@app.get("/api/routing/rules")
async def get_routing_rules():
    """获取所有路由规则"""
    nodes_info = []
    for node in NODES:
        node_info = {
            "name": node["name"],
            "type": node.get("type", "local"),
            "enabled": node.get("enabled", True),
            "healthy": node_stats[node["name"]]["is_healthy"],
            "config": node_config.get(node["name"], {}),
            "available_models": list(node_models.get(node["name"], set()))
        }
        if node.get("type") == "external":
            node_info["api_url"] = node.get("api_url")
        else:
            node_info["hosts"] = node.get("hosts", [])
            node_info["port"] = node.get("port", 11434)
        nodes_info.append(node_info)
    
    return {
        "nodes": nodes_info,
        "model_patterns": model_patterns,
        "model_mappings": model_name_mapping,
        "default_model_size_b": default_model_size,
        "scheduling_strategy": SCHEDULING_STRATEGY
    }


# 配置管理 API
@app.get("/api/config")
async def get_config_api():
    """獲取當前配置"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading config: {str(e)}")


@app.post("/api/config")
async def save_config_api(request: Request):
    """保存配置"""
    try:
        new_config = await request.json()
        success, message = save_config(new_config)
        if success:
            return {"success": True, "message": message}
        else:
            raise HTTPException(status_code=400, detail=message)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving config: {str(e)}")


@app.post("/api/config/reload")
async def reload_config_api():
    """重新加載配置（不保存）"""
    success = load_config()
    if success:
        return {"success": True, "message": "配置已重新加載"}
    else:
        raise HTTPException(status_code=500, detail="重新加載配置失敗")


# 模型路由查看器
@app.get("/routing", response_class=HTMLResponse)
async def routing_viewer():
    """模型路由规则查看器"""
    html_content = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>模型路由查看器 - Ollama Gateway</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
            background: #f5f7fa;
            padding: 20px;
        }
        .container {
            max-width: 1600px;
            margin: 0 auto;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 20px;
            text-align: center;
        }
        .header h1 {
            font-size: 28px;
            margin-bottom: 10px;
        }
        .section {
            background: white;
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .section h2 {
            color: #1e40af;
            margin-bottom: 20px;
            font-size: 20px;
            border-bottom: 2px solid #e5e7eb;
            padding-bottom: 10px;
        }
        .query-box {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        .query-box input {
            flex: 1;
            padding: 12px;
            border: 2px solid #e5e7eb;
            border-radius: 8px;
            font-size: 16px;
        }
        .query-box input:focus {
            outline: none;
            border-color: #2563eb;
        }
        .query-box button {
            padding: 12px 24px;
            background: #2563eb;
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
        }
        .query-box button:hover {
            background: #1d4ed8;
        }
        .result {
            margin-top: 20px;
            padding: 20px;
            border-radius: 8px;
            display: none;
        }
        .result.show {
            display: block;
        }
        .result.success {
            background: #d1fae5;
            border: 2px solid #10b981;
        }
        .result.warning {
            background: #fef3c7;
            border: 2px solid #f59e0b;
        }
        .result.error {
            background: #fee2e2;
            border: 2px solid #ef4444;
        }
        .node-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }
        .node-card {
            border: 2px solid #e5e7eb;
            border-radius: 8px;
            padding: 20px;
            background: white;
        }
        .node-card.candidate {
            border-color: #10b981;
            background: #f0fdf4;
        }
        .node-card.rejected {
            border-color: #ef4444;
            background: #fef2f2;
            opacity: 0.7;
        }
        .node-card.fallback {
            border-color: #f59e0b;
            background: #fffbeb;
        }
        .node-card h3 {
            color: #1e40af;
            margin-bottom: 10px;
            font-size: 18px;
        }
        .node-card .status {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            margin-bottom: 10px;
        }
        .status.healthy {
            background: #d1fae5;
            color: #065f46;
        }
        .status.unhealthy {
            background: #fee2e2;
            color: #991b1b;
        }
        .status.enabled {
            background: #dbeafe;
            color: #1e40af;
        }
        .status.disabled {
            background: #f3f4f6;
            color: #6b7280;
        }
        .node-card .info {
            margin: 8px 0;
            color: #4b5563;
            font-size: 14px;
        }
        .node-card .info strong {
            color: #1f2937;
        }
        .node-card .ranges {
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #e5e7eb;
        }
        .node-card .range-item {
            background: #f8f9fa;
            padding: 8px;
            margin: 5px 0;
            border-radius: 6px;
            font-size: 13px;
        }
        .node-card .reasons {
            margin-top: 10px;
            padding-top: 10px;
            border-top: 1px solid #e5e7eb;
        }
        .node-card .reason {
            color: #dc2626;
            font-size: 13px;
            margin: 5px 0;
        }
        .rules-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        .rule-item {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #3b82f6;
        }
        .rule-item h4 {
            color: #1e40af;
            margin-bottom: 8px;
            font-size: 14px;
        }
        .rule-item .pattern {
            font-family: 'Monaco', 'Courier New', monospace;
            background: white;
            padding: 4px 8px;
            border-radius: 4px;
            display: inline-block;
            margin: 2px;
        }
        .model-info {
            background: #eff6ff;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 15px;
        }
        .model-info h3 {
            color: #1e40af;
            margin-bottom: 10px;
        }
        .model-info .detail {
            margin: 5px 0;
            color: #4b5563;
        }
        .back-link {
            display: inline-block;
            margin-bottom: 20px;
            color: #2563eb;
            text-decoration: none;
            font-weight: 600;
        }
        .back-link:hover {
            text-decoration: underline;
        }
        .loading {
            text-align: center;
            padding: 20px;
            color: #6b7280;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎯 模型路由查看器</h1>
            <p>查看模型分配规则和查询模型会路由到哪些节点</p>
        </div>
        
        <a href="/" class="back-link">← 返回首頁</a>
        
        <!-- 查询工具 -->
        <div class="section">
            <h2>🔍 模型路由查询</h2>
            <div class="query-box">
                <input type="text" id="modelInput" placeholder="输入模型名称，例如: qwen3-coder:30b, llama2-70b, mistral:7b-instruct" value="">
                <button onclick="queryModel()">查询</button>
            </div>
            <div id="queryResult" class="result"></div>
        </div>
        
        <!-- 路由规则 -->
        <div class="section">
            <h2>📋 节点配置和规则</h2>
            <div id="rulesContent" class="loading">正在加载规则...</div>
        </div>
    </div>

    <script>
        // 查询模型路由
        async function queryModel() {
            const modelName = document.getElementById('modelInput').value.trim();
            if (!modelName) {
                alert('请输入模型名称');
                return;
            }
            
            const resultDiv = document.getElementById('queryResult');
            resultDiv.className = 'result loading';
            resultDiv.innerHTML = '正在查询...';
            resultDiv.classList.add('show');
            
            try {
                const response = await fetch(`/api/routing/query?model_name=${encodeURIComponent(modelName)}`);
                const data = await response.json();
                
                if (!response.ok) {
                    throw new Error(data.detail || '查询失败');
                }
                
                displayQueryResult(data);
            } catch (error) {
                resultDiv.className = 'result error show';
                resultDiv.innerHTML = `<strong>错误:</strong> ${error.message}`;
            }
        }
        
        function displayQueryResult(data) {
            const resultDiv = document.getElementById('queryResult');
            
            let html = `
                <div class="model-info">
                    <h3>📦 模型信息: ${data.model_name}</h3>
                    <div class="detail"><strong>基础名称:</strong> ${data.base_name}</div>
                    <div class="detail"><strong>识别大小:</strong> ${data.model_size_b}B</div>
                    <div class="detail"><strong>调度策略:</strong> ${data.scheduling_strategy}</div>
                </div>
            `;
            
            if (data.candidate_nodes.length > 0) {
                resultDiv.className = 'result success show';
                html += `<h3 style="margin-top: 20px; margin-bottom: 15px;">✅ 候选节点 (${data.candidate_nodes.length})</h3>`;
                html += '<div class="node-grid">';
                data.candidate_nodes.forEach(node => {
                    html += renderNodeCard(node, 'candidate');
                });
                html += '</div>';
            } else {
                resultDiv.className = 'result warning show';
                html += `<h3 style="margin-top: 20px; margin-bottom: 15px;">⚠️ 没有符合条件的节点</h3>`;
                if (data.fallback_nodes.length > 0) {
                    html += `<p style="margin-bottom: 15px;">将回退到以下健康节点（允许模型下载）:</p>`;
                    html += '<div class="node-grid">';
                    data.fallback_nodes.forEach(node => {
                        html += renderNodeCard(node, 'fallback');
                    });
                    html += '</div>';
                }
            }
            
            if (data.rejected_nodes.length > 0) {
                html += `<h3 style="margin-top: 20px; margin-bottom: 15px;">❌ 被拒绝的节点 (${data.rejected_nodes.length})</h3>`;
                html += '<div class="node-grid">';
                data.rejected_nodes.forEach(node => {
                    html += renderNodeCard(node, 'rejected');
                });
                html += '</div>';
            }
            
            resultDiv.innerHTML = html;
        }
        
        function renderNodeCard(node, type) {
            let html = `<div class="node-card ${type}">`;
            html += `<h3>${node.name.toUpperCase()}</h3>`;
            
            if (node.enabled !== undefined) {
                html += `<span class="status ${node.enabled ? 'enabled' : 'disabled'}">${node.enabled ? '已启用' : '已禁用'}</span> `;
            }
            if (node.healthy !== undefined) {
                html += `<span class="status ${node.healthy ? 'healthy' : 'unhealthy'}">${node.healthy ? '健康' : '不健康'}</span>`;
            }
            
            if (node.type === 'external') {
                html += `<div class="info"><strong>API URL:</strong> ${node.api_url || 'N/A'}</div>`;
            } else if (node.hosts && node.hosts.length > 0) {
                html += `<div class="info"><strong>地址:</strong> ${node.hosts[0]}:${node.port || 11434}</div>`;
            }
            
            if (node.config && node.config.supported_model_ranges) {
                html += '<div class="ranges"><strong>支持的模型范围:</strong>';
                node.config.supported_model_ranges.forEach(range => {
                    const min = range.min_params_b || 0;
                    const max = range.max_params_b === null ? '∞' : range.max_params_b;
                    html += `<div class="range-item">${min}B ~ ${max}B ${range.description ? '(' + range.description + ')' : ''}</div>`;
                });
                html += '</div>';
            }
            
            if (node.has_model !== undefined) {
                html += `<div class="info"><strong>有模型:</strong> ${node.has_model ? '✅ 是' : '❌ 否'}</div>`;
            }
            
            if (node.suitable_for_size !== undefined) {
                html += `<div class="info"><strong>大小合适:</strong> ${node.suitable_for_size ? '✅ 是' : '❌ 否'}</div>`;
            }
            
            if (node.reasons && node.reasons.length > 0) {
                html += '<div class="reasons"><strong>拒绝原因:</strong>';
                node.reasons.forEach(reason => {
                    html += `<div class="reason">• ${reason}</div>`;
                });
                html += '</div>';
            }
            
            if (node.reason) {
                html += `<div class="info" style="color: #f59e0b;"><strong>说明:</strong> ${node.reason}</div>`;
            }
            
            html += '</div>';
            return html;
        }
        
        // 加载路由规则
        async function loadRules() {
            try {
                const response = await fetch('/api/routing/rules');
                const data = await response.json();
                
                let html = '<div class="node-grid">';
                data.nodes.forEach(node => {
                    html += `
                        <div class="node-card ${node.healthy && node.enabled ? 'candidate' : 'rejected'}">
                            <h3>${node.name.toUpperCase()}</h3>
                            <span class="status ${node.enabled ? 'enabled' : 'disabled'}">${node.enabled ? '已启用' : '已禁用'}</span>
                            <span class="status ${node.healthy ? 'healthy' : 'unhealthy'}">${node.healthy ? '健康' : '不健康'}</span>
                            ${node.type === 'external' ? 
                                `<div class="info"><strong>API URL:</strong> ${node.api_url || 'N/A'}</div>` : 
                                `<div class="info"><strong>地址:</strong> ${node.hosts && node.hosts.length > 0 ? node.hosts[0] + ':' + node.port : 'N/A'}</div>`
                            }
                            ${node.config.memory_gb ? `<div class="info"><strong>内存:</strong> ${node.config.memory_gb}GB</div>` : ''}
                            ${node.config.description ? `<div class="info"><strong>描述:</strong> ${node.config.description}</div>` : ''}
                            ${node.config.supported_model_ranges ? `
                                <div class="ranges">
                                    <strong>支持的模型范围:</strong>
                                    ${node.config.supported_model_ranges.map(range => {
                                        const min = range.min_params_b || 0;
                                        const max = range.max_params_b === null ? '∞' : range.max_params_b;
                                        return `<div class="range-item">${min}B ~ ${max}B ${range.description ? '(' + range.description + ')' : ''}</div>`;
                                    }).join('')}
                                </div>
                            ` : ''}
                            ${node.available_models.length > 0 ? `
                                <div class="info" style="margin-top: 10px;">
                                    <strong>可用模型 (${node.available_models.length}):</strong><br>
                                    <small style="color: #6b7280;">${node.available_models.slice(0, 5).join(', ')}${node.available_models.length > 5 ? '...' : ''}</small>
                                </div>
                            ` : ''}
                        </div>
                    `;
                });
                html += '</div>';
                
                html += '<h2 style="margin-top: 30px;">🔤 模型名称模式匹配</h2>';
                html += '<div class="rules-grid">';
                Object.entries(data.model_patterns).forEach(([pattern, size]) => {
                    html += `
                        <div class="rule-item">
                            <h4>模式: <span class="pattern">${pattern}</span></h4>
                            <div>识别为: <strong>${size}B</strong></div>
                        </div>
                    `;
                });
                html += '</div>';
                
                if (Object.keys(data.model_mappings).length > 0) {
                    html += '<h2 style="margin-top: 30px;">🗺️ 模型名称映射</h2>';
                    html += '<div class="rules-grid">';
                    Object.entries(data.model_mappings).forEach(([name, size]) => {
                        html += `
                            <div class="rule-item">
                                <h4>模型: <span class="pattern">${name}</span></h4>
                                <div>映射为: <strong>${size}B</strong></div>
                            </div>
                        `;
                    });
                    html += '</div>';
                }
                
                html += `<div style="margin-top: 20px; padding: 15px; background: #eff6ff; border-radius: 8px;">
                    <strong>默认模型大小:</strong> ${data.default_model_size_b}B<br>
                    <strong>调度策略:</strong> ${data.scheduling_strategy}
                </div>`;
                
                document.getElementById('rulesContent').innerHTML = html;
            } catch (error) {
                document.getElementById('rulesContent').innerHTML = `<div class="result error show">加载失败: ${error.message}</div>`;
            }
        }
        
        // 页面加载时自动加载规则
        window.addEventListener('DOMContentLoaded', () => {
            loadRules();
        });
        
        // 支持 Enter 键查询
        document.getElementById('modelInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                queryModel();
            }
        });
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


# 配置編輯頁面
@app.get("/config", response_class=HTMLResponse)
async def config_editor():
    """配置編輯器頁面"""
    html_content = """
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>節點配置編輯器 - Ollama Gateway</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', sans-serif;
            background: #f5f7fa;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        .header h1 {
            font-size: 28px;
            margin-bottom: 10px;
        }
        .header p {
            opacity: 0.9;
        }
        .toolbar {
            padding: 20px;
            background: #f8f9fa;
            border-bottom: 1px solid #e9ecef;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        .btn-primary {
            background: #2563eb;
            color: white;
        }
        .btn-primary:hover {
            background: #1d4ed8;
        }
        .btn-success {
            background: #10b981;
            color: white;
        }
        .btn-success:hover {
            background: #059669;
        }
        .btn-secondary {
            background: #6b7280;
            color: white;
        }
        .btn-secondary:hover {
            background: #4b5563;
        }
        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .content {
            padding: 30px;
        }
        .editor-container {
            position: relative;
        }
        #configEditor {
            width: 100%;
            min-height: 600px;
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 14px;
            line-height: 1.6;
            padding: 20px;
            border: 2px solid #e5e7eb;
            border-radius: 8px;
            resize: vertical;
            tab-size: 2;
        }
        #configEditor:focus {
            outline: none;
            border-color: #2563eb;
            box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
        }
        .status {
            margin-top: 15px;
            padding: 12px;
            border-radius: 6px;
            display: none;
        }
        .status.success {
            background: #d1fae5;
            color: #065f46;
            border: 1px solid #10b981;
        }
        .status.error {
            background: #fee2e2;
            color: #991b1b;
            border: 1px solid #ef4444;
        }
        .status.info {
            background: #dbeafe;
            color: #1e40af;
            border: 1px solid #3b82f6;
        }
        .status.show {
            display: block;
        }
        .help-text {
            margin-top: 20px;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 6px;
            border-left: 4px solid #3b82f6;
        }
        .help-text h3 {
            margin-bottom: 10px;
            color: #1e40af;
        }
        .help-text ul {
            margin-left: 20px;
            color: #4b5563;
        }
        .help-text li {
            margin: 5px 0;
        }
        .back-link {
            display: inline-block;
            margin-bottom: 20px;
            color: #2563eb;
            text-decoration: none;
            font-weight: 600;
        }
        .back-link:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚙️ 節點配置編輯器</h1>
            <p>編輯 node_config.json 配置文件</p>
        </div>
        <div class="toolbar">
            <a href="/" class="btn btn-secondary">← 返回首頁</a>
            <button class="btn btn-primary" onclick="loadConfig()">🔄 重新載入</button>
            <button class="btn btn-success" onclick="saveConfig()">💾 保存配置</button>
            <button class="btn btn-secondary" onclick="formatJSON()">✨ 格式化 JSON</button>
            <button class="btn btn-secondary" onclick="validateJSON()">✓ 驗證 JSON</button>
        </div>
        <div class="content">
            <div class="editor-container">
                <textarea id="configEditor" spellcheck="false"></textarea>
            </div>
            <div id="status" class="status"></div>
            <div class="help-text">
                <h3>📖 使用說明</h3>
                <ul>
                    <li><strong>重新載入</strong>：從文件重新讀取當前配置（會丟棄未保存的修改）</li>
                    <li><strong>保存配置</strong>：保存當前編輯的配置到文件並<strong>立即生效</strong>（無需重啟服務）</li>
                    <li><strong>格式化 JSON</strong>：自動格式化 JSON 代碼，使其更易讀</li>
                    <li><strong>驗證 JSON</strong>：檢查 JSON 語法是否正確</li>
                    <li>保存前會自動創建備份文件（格式：node_config.json.backup.時間戳）</li>
                    <li><strong>配置會立即生效</strong>：保存後新的請求會自動使用新配置進行節點選擇</li>
                    <li>支持 Ctrl+S (Windows/Linux) 或 Cmd+S (Mac) 快捷鍵保存</li>
                </ul>
            </div>
        </div>
    </div>

    <script>
        let originalConfig = '';

        async function loadConfig() {
            const editor = document.getElementById('configEditor');
            const status = document.getElementById('status');
            
            try {
                showStatus('正在載入配置...', 'info');
                const response = await fetch('/api/config');
                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || '載入配置失敗');
                }
                const config = await response.json();
                originalConfig = JSON.stringify(config, null, 2);
                editor.value = originalConfig;
                showStatus('配置已載入', 'success');
            } catch (error) {
                showStatus('載入配置失敗: ' + error.message, 'error');
            }
        }

        async function saveConfig() {
            const editor = document.getElementById('configEditor');
            const configText = editor.value.trim();
            
            // 驗證 JSON
            let config;
            try {
                config = JSON.parse(configText);
            } catch (error) {
                showStatus('JSON 格式錯誤: ' + error.message, 'error');
                return;
            }
            
            try {
                showStatus('正在保存配置...', 'info');
                const response = await fetch('/api/config', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: configText
                });
                
                const result = await response.json();
                
                if (response.ok) {
                    originalConfig = configText;
                    showStatus(result.message || '配置已保存並重新加載', 'success');
                } else {
                    showStatus('保存失敗: ' + (result.detail || result.message || '未知錯誤'), 'error');
                }
            } catch (error) {
                showStatus('保存配置時發生錯誤: ' + error.message, 'error');
            }
        }

        function formatJSON() {
            const editor = document.getElementById('configEditor');
            
            try {
                const config = JSON.parse(editor.value);
                const formatted = JSON.stringify(config, null, 2);
                editor.value = formatted;
                showStatus('JSON 已格式化', 'success');
            } catch (error) {
                showStatus('JSON 格式錯誤，無法格式化: ' + error.message, 'error');
            }
        }

        function validateJSON() {
            const editor = document.getElementById('configEditor');
            
            try {
                JSON.parse(editor.value);
                showStatus('✓ JSON 格式正確', 'success');
            } catch (error) {
                showStatus('✗ JSON 格式錯誤: ' + error.message, 'error');
            }
        }

        function showStatus(message, type) {
            const status = document.getElementById('status');
            status.textContent = message;
            status.className = 'status ' + type + ' show';
            
            if (type === 'success' || type === 'info') {
                setTimeout(() => {
                    status.classList.remove('show');
                }, 3000);
            }
        }

        // 頁面加載時自動載入配置
        window.addEventListener('DOMContentLoaded', () => {
            loadConfig();
        });

        // 監聽 Ctrl+S 快捷鍵保存
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                saveConfig();
            }
        });
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


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

