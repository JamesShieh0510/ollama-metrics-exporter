# 節點配置說明

## 配置文件格式

`node_config.json` 用於定義節點的硬件規格和模型大小匹配規則。

## 配置結構

```json
{
  "nodes": [
    {
      "name": "node1",
      "memory_gb": 128,
      "description": "m3max-128gb",
      "supported_model_ranges": [
        {
          "min_params_b": 100,
          "max_params_b": null,
          "description": "120B+ 大模型"
        }
      ]
    }
  ],
  "model_name_patterns": {
    "120b": 120,
    "70b": 70,
    "8b": 8
  },
  "default_model_size_b": 7
}
```

## 字段說明

### nodes 數組

每個節點配置包含：

- **name** (string, 必需): 節點名稱，必須與 `ollama_gateway.py` 中定義的節點名稱一致
- **memory_gb** (number, 可選): 節點的內存大小（GB），用於文檔說明
- **description** (string, 可選): 節點描述
- **supported_model_ranges** (array, 可選): 支持的模型大小範圍列表

#### supported_model_ranges

每個範圍包含：

- **min_params_b** (number, 必需): 最小參數數量（B為單位）
- **max_params_b** (number, 可選): 最大參數數量（B為單位），`null` 表示無上限
- **description** (string, 可選): 範圍描述

### model_name_patterns

模型名稱模式映射，用於從模型名稱中提取參數數量。

- 鍵：模型名稱中包含的模式（不區分大小寫）
- 值：對應的參數數量（B為單位）

例如：
- `"120b": 120` 會匹配 `llama2-120b`、`qwen2.5-120B` 等
- `"70b": 70` 會匹配 `llama2-70b`、`mistral-70B` 等

### default_model_size_b

當無法從模型名稱中識別參數數量時使用的默認值（默認：7B）。

## 配置示例

### 完整配置示例

```json
{
  "nodes": [
    {
      "name": "node1",
      "memory_gb": 128,
      "description": "m3max-128gb",
      "supported_model_ranges": [
        {
          "min_params_b": 100,
          "max_params_b": null,
          "description": "120B+ 大模型"
        }
      ]
    },
    {
      "name": "node2",
      "memory_gb": 32,
      "description": "m1max-32gb",
      "supported_model_ranges": [
        {
          "min_params_b": 30,
          "max_params_b": 70,
          "description": "30B~70B 中型模型"
        }
      ]
    },
    {
      "name": "node3",
      "memory_gb": 16,
      "description": "m1-16gb",
      "supported_model_ranges": [
        {
          "min_params_b": 1,
          "max_params_b": 20,
          "description": "1B~20B 小模型"
        }
      ]
    },
    {
      "name": "node4",
      "memory_gb": 32,
      "description": "i7-4080-32gb",
      "supported_model_ranges": [
        {
          "min_params_b": 1,
          "max_params_b": 8,
          "description": "1B~8B 小模型（GPU加速）"
        }
      ]
    }
  ],
  "model_name_patterns": {
    "120b": 120,
    "120B": 120,
    "70b": 70,
    "70B": 70,
    "65b": 65,
    "65B": 65,
    "34b": 34,
    "34B": 34,
    "32b": 32,
    "32B": 32,
    "30b": 30,
    "30B": 30,
    "13b": 13,
    "13B": 13,
    "8b": 8,
    "8B": 8,
    "7b": 7,
    "7B": 7,
    "3b": 3,
    "3B": 3,
    "1b": 1,
    "1B": 1
  },
  "default_model_size_b": 7
}
```

## 節點選擇邏輯

當收到請求時，網關會按以下順序篩選節點：

1. **模型可用性檢查**
   - 只選擇已下載該模型的節點
   - 通過定期同步每個節點的 `/api/tags` 端點獲取模型列表

2. **硬件規格匹配**
   - 從模型名稱中提取參數數量
   - 檢查節點的 `supported_model_ranges` 配置
   - 只選擇參數數量在支持範圍內的節點

3. **調度策略選擇**
   - 在符合條件的節點中，根據 `SCHEDULING_STRATEGY` 選擇節點
   - 如果沒有符合條件的節點，回退到所有健康節點

## 模型名稱識別

網關會按以下優先順序識別參數數量：

1. **從 Tag 中提取**（優先級最高）: Ollama 的模型格式通常為 `model-name:tag`，tag 中經常包含參數數量
   - 支持格式：`:30b`, `:30B`, `:30-b`, `:30b-instruct`, `:30b:latest` 等
   - 例如：`qwen3-coder:30b` → 從 tag `30b` 中提取 → 30B

2. **模型名稱映射表**: 檢查 `model_name_mapping` 中的精確匹配
   - 例如：`qwen3-coder` → 30B（如果配置了映射）

3. **模式匹配**: 使用 `model_name_patterns` 中的模式進行匹配
   - 例如：`llama2-70b` → 匹配 `70b` 模式 → 70B

4. **正則表達式提取**: 從模型名稱中提取數字（例如 `70b` → 70）
   - 支持格式：`70b`, `120-b`, `7b-instruct` 等

5. **默認值**: 如果都失敗，使用 `default_model_size_b`

### 示例

- `qwen3-coder:30b` → 從 tag 提取 → **30B** ✅
- `llama2-70b:latest` → 從 tag 提取 → **70B** ✅
- `mistral:7b-instruct` → 從 tag 提取 → **7B** ✅
- `qwen2.5-120b` → 從名稱提取 → **120B** ✅
- `llama2` → 使用默認值 → **7B** ⚠️

## 注意事項

1. **節點名稱必須一致**: 配置中的 `name` 必須與 `ollama_gateway.py` 中定義的節點名稱完全一致

2. **範圍配置**: 
   - `max_params_b: null` 表示無上限
   - 範圍是包含邊界的（`min_params_b <= model_size <= max_params_b`）

3. **向後兼容**: 如果節點不在配置文件中，網關會允許該節點處理任何模型（向後兼容）

4. **模型同步**: 模型列表每 30 秒同步一次，新下載的模型可能需要等待下次同步才能被識別

## 調試

查看節點狀態和模型列表：

```bash
curl http://localhost:11435/nodes | jq
```

輸出會包含每個節點的：
- 已下載的模型列表
- 硬件配置信息
- 運行狀態

