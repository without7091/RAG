"""
手动测试 RAG 检索接口的脚本。

放在仓库根目录运行，支持 JSON / SSE 两种模式，并内置多种常见测试场景。

示例：
  python manual_retrieve_test.py --kb kb_xxx --query "怎么处理网关连接失败" --scenario json_basic
  python manual_retrieve_test.py --kb kb_xxx --query "怎么处理网关连接失败" --scenario json_with_rewrite
  python manual_retrieve_test.py --kb kb_xxx --query "怎么处理网关连接失败" --scenario json_with_rewrite_debug
  python manual_retrieve_test.py --kb kb_xxx --query "怎么处理网关连接失败" --scenario sse_basic
  python manual_retrieve_test.py --kb kb_xxx --query "怎么处理网关连接失败" --scenario sse_with_rewrite
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


RETRIEVE_PATH = "/api/v1/retrieve"
DEFAULT_BASE_URL = f"http://localhost:8000{RETRIEVE_PATH}"


SCENARIOS: dict[str, dict[str, Any]] = {
    "json_basic": {
        "stream": False,
        "enable_reranker": True,
        "enable_context_synthesis": True,
        "enable_query_rewrite": False,
        "query_rewrite_debug": False,
        "description": "基础 JSON 检索：开启 reranker + 上下文拼接，不做 query 改写",
    },
    "json_no_reranker": {
        "stream": False,
        "enable_reranker": False,
        "enable_context_synthesis": True,
        "enable_query_rewrite": False,
        "query_rewrite_debug": False,
        "description": "关闭 reranker，直接看混合召回结果",
    },
    "json_no_context": {
        "stream": False,
        "enable_reranker": True,
        "enable_context_synthesis": False,
        "enable_query_rewrite": False,
        "query_rewrite_debug": False,
        "description": "关闭上下文拼接，只看命中 chunk 本身",
    },
    "json_with_rewrite": {
        "stream": False,
        "enable_reranker": True,
        "enable_context_synthesis": True,
        "enable_query_rewrite": True,
        "query_rewrite_debug": False,
        "description": "开启 query 改写，但不返回 debug 信息",
    },
    "json_with_rewrite_debug": {
        "stream": False,
        "enable_reranker": True,
        "enable_context_synthesis": True,
        "enable_query_rewrite": True,
        "query_rewrite_debug": True,
        "description": "开启 query 改写，并返回改写计划/候选池调试信息",
    },
    "json_strict_threshold": {
        "stream": False,
        "enable_reranker": True,
        "enable_context_synthesis": True,
        "enable_query_rewrite": False,
        "query_rewrite_debug": False,
        "min_score": 0.1,
        "description": "显式使用 min_score=0.1，方便测试 reranker 后全部被过滤为空的边界情况",
    },
    "sse_basic": {
        "stream": True,
        "enable_reranker": True,
        "enable_context_synthesis": True,
        "enable_query_rewrite": False,
        "query_rewrite_debug": False,
        "description": "基础 SSE 检索，观察流式状态",
    },
    "sse_with_rewrite": {
        "stream": True,
        "enable_reranker": True,
        "enable_context_synthesis": True,
        "enable_query_rewrite": True,
        "query_rewrite_debug": False,
        "description": "SSE + query 改写，观察 query_rewrite / embedding_query / hybrid_search 等状态",
    },
    "sse_with_rewrite_debug": {
        "stream": True,
        "enable_reranker": True,
        "enable_context_synthesis": True,
        "enable_query_rewrite": True,
        "query_rewrite_debug": True,
        "description": "SSE + query 改写 + debug，最终 result 会带 debug 字段",
    },
}


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    scenario = SCENARIOS[args.scenario]
    payload: dict[str, Any] = {
        "user_id": args.user_id,
        "knowledge_base_id": args.kb,
        "query": normalize_cli_text(args.query),
        "top_k": args.top_k,
        "top_n": args.top_n,
        "stream": scenario["stream"],
        "enable_reranker": scenario["enable_reranker"],
        "enable_context_synthesis": scenario["enable_context_synthesis"],
        "enable_query_rewrite": scenario["enable_query_rewrite"],
        "query_rewrite_debug": scenario["query_rewrite_debug"],
    }
    if "min_score" in scenario:
        payload["min_score"] = scenario["min_score"]
    if args.min_score is not None:
        payload["min_score"] = args.min_score
    return payload


def resolve_retrieve_url(base_url: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        return base_url.rstrip("/")

    normalized_path = parsed.path.rstrip("/")
    if normalized_path.endswith(RETRIEVE_PATH):
        path = normalized_path
    elif normalized_path.endswith("/api/v1"):
        path = f"{normalized_path}/retrieve"
    elif normalized_path in ("", "/"):
        path = RETRIEVE_PATH
    else:
        path = f"{normalized_path}{RETRIEVE_PATH}"

    return urllib.parse.urlunparse(parsed._replace(path=path, query="", fragment=""))


def build_connection_hint(base_url: str) -> str | None:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.hostname not in {"localhost", "127.0.0.1"}:
        return None

    if parsed.port == 3000:
        return (
            "你当前请求的是前端 3000 端口；如果只启动了后端，请改用 "
            "`http://localhost:8000/api/v1/retrieve`，或直接省略 `--base-url`。"
        )

    if parsed.port in {None, 8000}:
        return "请确认后端服务正在 `http://localhost:8000` 监听。"

    return None


def should_bypass_proxy(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.hostname in {"localhost", "127.0.0.1"}


def open_url(request: urllib.request.Request, timeout: int):
    if should_bypass_proxy(request.full_url):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)


def post_json(url: str, payload: dict[str, Any], timeout: int) -> int:
    request = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with open_url(request, timeout=timeout) as response:
        status_code = response.getcode()
        body = response.read().decode("utf-8")
        print(f"HTTP {status_code}")
        print_json(body)
        return status_code


def post_sse(url: str, payload: dict[str, Any], timeout: int) -> int:
    request = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with open_url(request, timeout=timeout) as response:
        status_code = response.getcode()
        print(f"HTTP {status_code}")
        print("--- SSE START ---")

        current_event = ""
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line:
                continue

            if line.startswith("event:"):
                current_event = line.split(":", 1)[1].strip()
                print(f"\n[event] {current_event}")
                continue

            if not line.startswith("data:"):
                print(line)
                continue

            data_text = line.split(":", 1)[1].strip()
            try:
                parsed = json.loads(data_text)
            except json.JSONDecodeError:
                print(data_text)
                continue

            if current_event == "status":
                step = parsed.get("step")
                candidates = parsed.get("candidates")
                if candidates is None:
                    print(f"  step={step}")
                else:
                    print(f"  step={step}, candidates={candidates}")
            elif current_event == "result":
                print_json(json.dumps(parsed, ensure_ascii=False))
            elif current_event == "error":
                print_json(json.dumps(parsed, ensure_ascii=False))
            else:
                print_json(json.dumps(parsed, ensure_ascii=False))

        print("\n--- SSE END ---")
        return status_code


def print_json(text: str) -> None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        print(text)
        return
    print(json.dumps(parsed, ensure_ascii=False, indent=2))


def normalize_cli_text(text: str | None) -> str:
    if text is None:
        return ""
    if "\\u" in text or "\\x" in text:
        try:
            return text.encode("utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            return text
    return text


def list_scenarios() -> None:
    print("可用测试场景：")
    for name, config in SCENARIOS.items():
        print(f"- {name}: {config['description']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="手动测试 /api/v1/retrieve 接口")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="检索接口地址；可传 http://localhost:8000 或完整 /api/v1/retrieve",
    )
    parser.add_argument("--kb", help="knowledge_base_id")
    parser.add_argument("--query", help="查询文本")
    parser.add_argument("--user-id", default="playground", help="user_id")
    parser.add_argument("--scenario", default="json_basic", choices=sorted(SCENARIOS.keys()))
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--min-score", type=float, default=None, help="覆盖场景中的 min_score")
    parser.add_argument("--timeout", type=int, default=120, help="请求超时时间（秒）")
    parser.add_argument("--list-scenarios", action="store_true", help="仅打印可用场景")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.list_scenarios:
        list_scenarios()
        return 0

    if not args.kb or not args.query:
        print("错误：必须提供 --kb 和 --query", file=sys.stderr)
        print("你也可以先运行: python manual_retrieve_test.py --list-scenarios")
        return 2

    request_url = resolve_retrieve_url(args.base_url)
    payload = build_payload(args)
    scenario = SCENARIOS[args.scenario]
    print(f"场景: {args.scenario}")
    print(f"说明: {scenario['description']}")
    print(f"请求地址: {request_url}")
    print("请求体:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print()

    try:
        if payload["stream"]:
            post_sse(request_url, payload, args.timeout)
        else:
            post_json(request_url, payload, args.timeout)
        return 0
    except urllib.error.HTTPError as exc:
        print(f"HTTPError: {exc.code}", file=sys.stderr)
        body = exc.read().decode("utf-8", errors="replace")
        print_json(body)
        return 1
    except urllib.error.URLError as exc:
        print(f"URLError: {exc}", file=sys.stderr)
        hint = build_connection_hint(request_url)
        if hint:
            print(hint, file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
