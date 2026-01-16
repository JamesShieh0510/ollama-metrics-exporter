#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Ollama HumanEval runner (pass@1)
- Input: HumanEval-style problems.jsonl
- Output: results.jsonl and summary in stdout

Requires:
  pip install requests python-dotenv

Usage:
  # 方式1: 使用命令行參數
  python ollama_humaneval_runner.py \
    --model qwen2.5-coder:14b \
    --problems /path/to/problems.jsonl \
    --out results.jsonl \
    --num-samples 1 \
    --temperature 0.0 \
    --timeout 8

  # 方式2: 使用 .env 文件配置（推薦）
  # 創建 .env 文件：
  #   OLLAMA_BASE_URL=http://localhost:11435
  #   OLLAMA_MODEL=qwen2.5-coder:14b
  #   OLLAMA_TEMPERATURE=0.0
  #   OLLAMA_TOP_P=1.0
  #   OLLAMA_SEED=42
  #   OLLAMA_TIMEOUT=8
  #   OLLAMA_NUM_PREDICT=2048
  # 然後運行：
  python ollama_humaneval_runner.py --problems /path/to/problems.jsonl

  # 命令行參數會覆蓋 .env 中的設置

Notes:
- This is an evaluation harness. Do NOT run untrusted datasets.
- It executes model-generated code in a subprocess. Still, treat as unsafe.
- 環境變量優先級：命令行參數 > .env 文件 > 默認值
"""

import argparse
import json
import os
import re
import sys
import time
import tempfile
import subprocess
import csv
from typing import Dict, Any, List, Optional, Tuple

import requests
from dotenv import load_dotenv

# 加載環境變量
load_dotenv()


CODE_FENCE_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)

SYSTEM_PROMPT = (
    "You are a coding assistant. "
    "Return ONLY valid Python code. "
    "Do not include explanations. "
    "Do not wrap the code in markdown fences. "
    "Make sure the function matches the prompt exactly."
)

def read_jsonl(path: str) -> List[Dict[str, Any]]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items

def write_jsonl(path: str, rows: List[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_csv(path: str, results: List[Dict[str, Any]]) -> None:
    """寫入 CSV 文件，包含排名"""
    if not results:
        return
    
    # 按 pass@1 和 tokens/s 排序（先按通過率，通過的在前，再按速度）
    sorted_results = sorted(
        results,
        key=lambda x: (
            not x.get("ok", False),  # False 在前（未通過），True 在後（通過）
            -x.get("eval_tokens_per_sec", 0)  # 降序（快的在前）
        )
    )
    
    # CSV 欄位
    fieldnames = [
        "rank",
        "task_id",
        "model",
        "pass_status",
        "ok",
        "gen_time_s",
        "exec_time_s",
        "eval_count",
        "prompt_eval_count",
        "eval_tokens_per_sec",
        "prompt_tokens_per_sec",
        "eval_duration_s",
        "prompt_eval_duration_s",
        "sample_index",
        "error",
    ]
    
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for rank, r in enumerate(sorted_results, start=1):
            row = {}
            row["rank"] = rank
            row["task_id"] = r.get("task_id", "")
            row["model"] = r.get("model", "")
            row["pass_status"] = "PASS" if r.get("ok") else "FAIL"
            row["ok"] = r.get("ok", False)
            row["gen_time_s"] = r.get("gen_time_s")
            row["exec_time_s"] = r.get("exec_time_s")
            row["eval_count"] = r.get("eval_count", 0)
            row["prompt_eval_count"] = r.get("prompt_eval_count", 0)
            row["eval_tokens_per_sec"] = round(r.get("eval_tokens_per_sec", 0), 2)
            row["prompt_tokens_per_sec"] = round(r.get("prompt_tokens_per_sec", 0), 2)
            # 轉換納秒為秒
            eval_duration_ns = r.get("eval_duration_ns", 0)
            prompt_eval_duration_ns = r.get("prompt_eval_duration_ns", 0)
            row["eval_duration_s"] = round(eval_duration_ns / 1e9, 4) if eval_duration_ns else 0
            row["prompt_eval_duration_s"] = round(prompt_eval_duration_ns / 1e9, 4) if prompt_eval_duration_ns else 0
            row["sample_index"] = r.get("sample_index")
            row["error"] = r.get("error", "")
            writer.writerow(row)

def extract_code(text: str, keep_last_def: bool = True) -> str:
    """
    Try to extract code with improved stability:
    - If response contains ``` ``` fences, take the first fenced block
    - If keep_last_def is True, only keep the last function definition
    - Else return raw text
    
    Args:
        text: Raw response text
        keep_last_def: If True, only keep the last function definition to avoid noise
    """
    code = ""
    m = CODE_FENCE_RE.search(text or "")
    if m:
        code = m.group(1).strip()
    else:
        code = (text or "").strip()
    
    if keep_last_def and code:
        # 只保留最後一個 def 函數定義
        def_pattern = re.compile(r'^def\s+\w+', re.MULTILINE)
        def_matches = list(def_pattern.finditer(code))
        
        if len(def_matches) > 1:
            # 找到最後一個 def 的位置
            last_def_start = def_matches[-1].start()
            # 從最後一個 def 開始提取
            code = code[last_def_start:]
            # 移除前面的空行和註釋
            code = code.lstrip()
    
    return code

def ollama_generate(
    base_url: str,
    model: str,
    prompt: str,
    temperature: float,
    top_p: float,
    seed: Optional[int],
    num_predict: Optional[int],
) -> Tuple[str, Dict[str, Any]]:
    """
    Generate response from Ollama and return response text with metadata.
    
    Returns:
        Tuple of (response_text, metadata_dict)
        metadata includes: eval_count, prompt_eval_count, eval_duration, prompt_eval_duration, etc.
    """
    url = base_url.rstrip("/") + "/api/generate"
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "system": SYSTEM_PROMPT,
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": top_p,
        },
    }
    if seed is not None:
        payload["options"]["seed"] = seed
    if num_predict is not None:
        payload["options"]["num_predict"] = num_predict

    r = requests.post(url, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    
    response_text = data.get("response", "")
    
    # 提取 tokens 相關信息
    metadata = {
        "eval_count": data.get("eval_count", 0),
        "prompt_eval_count": data.get("prompt_eval_count", 0),
        "eval_duration": data.get("eval_duration", 0),  # nanoseconds
        "prompt_eval_duration": data.get("prompt_eval_duration", 0),  # nanoseconds
        "total_duration": data.get("total_duration", 0),  # nanoseconds
    }
    
    # 計算 tokens/s
    if metadata["eval_duration"] > 0:
        eval_duration_s = metadata["eval_duration"] / 1e9
        metadata["eval_tokens_per_sec"] = metadata["eval_count"] / eval_duration_s if eval_duration_s > 0 else 0
    else:
        metadata["eval_tokens_per_sec"] = 0
    
    if metadata["prompt_eval_duration"] > 0:
        prompt_eval_duration_s = metadata["prompt_eval_duration"] / 1e9
        metadata["prompt_tokens_per_sec"] = metadata["prompt_eval_count"] / prompt_eval_duration_s if prompt_eval_duration_s > 0 else 0
    else:
        metadata["prompt_tokens_per_sec"] = 0
    
    return response_text, metadata

def build_program(problem: Dict[str, Any], completion_code: str) -> str:
    """
    HumanEval problems typically have:
      - prompt: includes function signature and docstring
      - test: python asserts + check(entry_point)
      - entry_point: function name
    Strategy:
      - Write completion_code as-is (model should include function def)
      - Append the problem's test code
      - Ensure it runs when executed as script
    """
    test_code = problem.get("test", "")
    # Some datasets include "check(candidate)" style; others directly assert.
    # We'll just append it; assume it's self-contained.
    program = completion_code.rstrip() + "\n\n" + test_code.rstrip() + "\n"
    return program

def run_python(program: str, timeout_s: int) -> Dict[str, Any]:
    """
    Execute the program in a subprocess with timeout.
    Returns dict with pass/fail and error info.
    """
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "main.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(program)

        t0 = time.time()
        try:
            cp = subprocess.run(
                [sys.executable, path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_s,
                check=False,  # 不抛出异常，手动检查返回码
            )
            dt = time.time() - t0
            ok = (cp.returncode == 0)
            return {
                "ok": ok,
                "time_s": dt,
                "returncode": cp.returncode,
                "stdout": cp.stdout[-4000:],  # trim
                "stderr": cp.stderr[-4000:],
            }
        except subprocess.TimeoutExpired as e:
            dt = time.time() - t0
            return {
                "ok": False,
                "time_s": dt,
                "returncode": None,
                "stdout": (e.stdout or "")[-4000:] if hasattr(e, "stdout") else "",
                "stderr": (e.stderr or "")[-4000:] if hasattr(e, "stderr") else "",
                "error": "timeout",
            }

def make_prompt(problem: Dict[str, Any]) -> str:
    """
    Strongly constrain to reduce "extra text":
    - Ask to output only code
    - Include original prompt as spec
    """
    p = problem.get("prompt", "")
    return (
        "Write the Python solution code for the following task.\n"
        "Rules:\n"
        "1) Output ONLY Python code.\n"
        "2) Do NOT use markdown fences.\n"
        "3) Implement exactly the required function(s).\n\n"
        f"{p}\n"
    )

def main():
    # 從環境變量讀取默認值
    default_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    default_model = os.getenv("OLLAMA_MODEL", None)
    default_temperature = float(os.getenv("OLLAMA_TEMPERATURE", "0.0"))
    default_top_p = float(os.getenv("OLLAMA_TOP_P", "1.0"))
    default_seed = int(os.getenv("OLLAMA_SEED", "42")) if os.getenv("OLLAMA_SEED") else None
    default_timeout = int(os.getenv("OLLAMA_TIMEOUT", "8"))
    default_num_predict = int(os.getenv("OLLAMA_NUM_PREDICT")) if os.getenv("OLLAMA_NUM_PREDICT") else None
    
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=default_base_url, help=f"Ollama base URL (default from .env: {default_base_url})")
    ap.add_argument("--model", default=default_model, required=not default_model, 
                    help=f"Ollama model name, e.g. qwen2.5-coder:14b (default from .env: {default_model})")
    ap.add_argument("--problems", required=True, help="Path to HumanEval problems.jsonl")
    # 获取项目根目录
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DEFAULT_OUTPUT = os.path.join(PROJECT_ROOT, "data", "results.jsonl")
    ap.add_argument("--out", default=DEFAULT_OUTPUT, help="Output JSONL for per-problem results")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of problems (0 = all)")
    ap.add_argument("--num-samples", type=int, default=1, help="Completions per problem (for pass@k style); keep 1 for pass@1")
    ap.add_argument("--temperature", type=float, default=default_temperature, 
                    help=f"Temperature (default from .env: {default_temperature})")
    ap.add_argument("--top-p", type=float, default=default_top_p, 
                    help=f"Top-p (default from .env: {default_top_p})")
    ap.add_argument("--seed", type=int, default=default_seed, 
                    help=f"Seed for determinism (default from .env: {default_seed})")
    ap.add_argument("--timeout", type=int, default=default_timeout, 
                    help=f"Per-run timeout seconds (default from .env: {default_timeout})")
    ap.add_argument("--num-predict", type=int, default=default_num_predict, 
                    help=f"Max tokens to generate (default from .env: {default_num_predict})")
    ap.add_argument("--keep-last-def", action="store_true", default=True,
                    help="Only keep the last function definition to avoid noise (default: True)")
    ap.add_argument("--no-keep-last-def", dest="keep_last_def", action="store_false",
                    help="Disable keeping only the last function definition")
    ap.add_argument("--csv", default=None, help="Output CSV file path (optional)")
    args = ap.parse_args()

    problems = read_jsonl(args.problems)
    if args.limit and args.limit > 0:
        problems = problems[: args.limit]

    results: List[Dict[str, Any]] = []
    total = 0
    passed_any = 0
    total_time_gen = 0.0
    total_time_exec = 0.0

    for i, prob in enumerate(problems, start=1):
        task_id = prob.get("task_id") or prob.get("id") or f"task_{i}"
        prompt = make_prompt(prob)

        best = {
            "ok": False,
            "gen_time_s": None,
            "exec_time_s": None,
            "sample_index": None,
            "response_raw": None,
            "code": None,
            "run": None,
            "metadata": {},
        }

        for s in range(args.num_samples):
            # If you want different randomness per sample, vary seed:
            seed = args.seed + s if args.seed is not None else None

            t0 = time.time()
            try:
                resp, metadata = ollama_generate(
                    base_url=args.base_url,
                    model=args.model,
                    prompt=prompt,
                    temperature=args.temperature,
                    top_p=args.top_p,
                    seed=seed,
                    num_predict=args.num_predict,
                )
            except Exception as e:
                gen_dt = time.time() - t0
                sample_res = {
                    "ok": False,
                    "error": f"ollama_generate_failed: {repr(e)}",
                    "gen_time_s": gen_dt,
                }
                # keep going
                if best["sample_index"] is None:
                    best.update({
                        "gen_time_s": gen_dt,
                        "sample_index": s,
                        "response_raw": "",
                        "code": "",
                        "run": sample_res,
                        "metadata": {},
                    })
                continue

            gen_dt = time.time() - t0
            total_time_gen += gen_dt

            code = extract_code(resp, keep_last_def=args.keep_last_def)
            program = build_program(prob, code)
            run_res = run_python(program, timeout_s=args.timeout)
            total_time_exec += run_res.get("time_s", 0.0)

            if run_res.get("ok"):
                best.update({
                    "ok": True,
                    "gen_time_s": gen_dt,
                    "exec_time_s": run_res.get("time_s"),
                    "sample_index": s,
                    "response_raw": resp,
                    "code": code,
                    "run": run_res,
                    "metadata": metadata,
                })
                break  # pass@1: stop at first success for this problem

            # record first failure as best if nothing yet
            if best["sample_index"] is None:
                best.update({
                    "ok": False,
                    "gen_time_s": gen_dt,
                    "exec_time_s": run_res.get("time_s"),
                    "sample_index": s,
                    "response_raw": resp,
                    "code": code,
                    "run": run_res,
                    "metadata": metadata,
                })

        total += 1
        if best["ok"]:
            passed_any += 1

        metadata = best.get("metadata", {})
        row = {
            "task_id": task_id,
            "model": args.model,
            "ok": best["ok"],
            "sample_index": best["sample_index"],
            "gen_time_s": best["gen_time_s"],
            "exec_time_s": best["exec_time_s"],
            "stdout": (best["run"] or {}).get("stdout") if best["run"] else None,
            "stderr": (best["run"] or {}).get("stderr") if best["run"] else None,
            "error": (best["run"] or {}).get("error") if best["run"] else None,
            # Tokens 相關信息
            "eval_count": metadata.get("eval_count", 0),
            "prompt_eval_count": metadata.get("prompt_eval_count", 0),
            "eval_tokens_per_sec": metadata.get("eval_tokens_per_sec", 0),
            "prompt_tokens_per_sec": metadata.get("prompt_tokens_per_sec", 0),
            "eval_duration_ns": metadata.get("eval_duration", 0),
            "prompt_eval_duration_ns": metadata.get("prompt_eval_duration", 0),
            # Keep these for debugging; you can remove if you want smaller output:
            "code": best["code"],
            "response_raw": best["response_raw"],
        }
        results.append(row)

        status = "PASS" if best["ok"] else "FAIL"
        tokens_info = ""
        if metadata.get("eval_tokens_per_sec"):
            tokens_info = f" | {metadata['eval_tokens_per_sec']:.1f} tokens/s"
        print(f"[{i}/{len(problems)}] {status} {task_id}{tokens_info}")

    write_jsonl(args.out, results)

    # 輸出 CSV（如果指定）
    if args.csv:
        write_csv(args.csv, results)

    # 計算排名和統計
    pass_rate = (passed_any / total) if total else 0.0
    avg_tokens_per_sec = 0.0
    if results:
        tokens_per_sec_list = [r.get("eval_tokens_per_sec", 0) for r in results if r.get("eval_tokens_per_sec", 0) > 0]
        if tokens_per_sec_list:
            avg_tokens_per_sec = sum(tokens_per_sec_list) / len(tokens_per_sec_list)
    
    print("\n===== Summary =====")
    print(f"Model: {args.model}")
    print(f"Problems: {total}")
    print(f"Passed: {passed_any}")
    print(f"pass@1: {pass_rate:.4f}")
    print(f"Total gen time (s): {total_time_gen:.2f}")
    print(f"Total exec time (s): {total_time_exec:.2f}")
    if total:
        print(f"Avg gen time/prob (s): {total_time_gen/total:.2f}")
        print(f"Avg exec time/prob (s): {total_time_exec/total:.2f}")
    if avg_tokens_per_sec > 0:
        print(f"Avg tokens/s: {avg_tokens_per_sec:.2f}")
    print(f"Results: {args.out}")
    if args.csv:
        print(f"CSV: {args.csv}")

if __name__ == "__main__":
    main()
