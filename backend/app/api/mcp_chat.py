"""
MCP AI Chat: proxies natural language conversations through a local LLM (Ollama)
with MinIO MCP tools available for the LLM to call.

The LLM endpoint is configurable — defaults to local Ollama but can point to
any OpenAI-compatible API (Ollama, vLLM, LiteLLM, OpenAI, etc.).

Routes:
  POST /api/demos/{demo_id}/minio/{cluster_id}/mcp/chat  (SSE stream)
  GET  /api/settings/llm                                   (get config)
  POST /api/settings/llm                                   (set config)
"""
import json
import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .mcp_proxy import _resolve_mcp_container, _mcp_request

logger = logging.getLogger(__name__)

router = APIRouter()

# --- LLM Configuration (persisted in env/settings file) ---

_llm_config = {
    "endpoint": os.environ.get("DEMOFORGE_LLM_ENDPOINT", "http://host.docker.internal:11434"),
    "model": os.environ.get("DEMOFORGE_LLM_MODEL", "qwen2.5:14b"),
    "api_type": os.environ.get("DEMOFORGE_LLM_API_TYPE", "ollama"),  # "ollama" or "openai"
}

LLM_SETTINGS_FILE = os.path.join(
    os.environ.get("DEMOFORGE_DATA_DIR", "./data"), "llm_settings.json"
)


def _load_llm_config():
    """Load LLM config from file if it exists."""
    try:
        if os.path.exists(LLM_SETTINGS_FILE):
            with open(LLM_SETTINGS_FILE) as f:
                saved = json.load(f)
                _llm_config.update(saved)
    except Exception:
        pass


def _save_llm_config():
    """Persist LLM config to file."""
    try:
        os.makedirs(os.path.dirname(LLM_SETTINGS_FILE), exist_ok=True)
        with open(LLM_SETTINGS_FILE, "w") as f:
            json.dump(_llm_config, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save LLM settings: {e}")


_load_llm_config()


class LLMConfigRequest(BaseModel):
    endpoint: str | None = None
    model: str | None = None
    api_type: str | None = None  # "ollama" or "openai"


class ChatRequest(BaseModel):
    messages: list[dict[str, str]]  # [{role: "user", content: "..."}]


@router.get("/api/settings/llm")
async def get_llm_config():
    return _llm_config


@router.post("/api/settings/llm")
async def set_llm_config(req: LLMConfigRequest):
    if req.endpoint is not None:
        _llm_config["endpoint"] = req.endpoint
    if req.model is not None:
        _llm_config["model"] = req.model
    if req.api_type is not None:
        _llm_config["api_type"] = req.api_type
    _save_llm_config()
    return _llm_config


# --- MCP Tool conversion to Ollama/OpenAI tool format ---

def _mcp_tool_to_openai(tool: dict) -> dict:
    """Convert MCP tool schema to OpenAI function calling format."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
        },
    }


# --- Chat endpoint with SSE streaming ---

SYSTEM_PROMPT = """You are a helpful MinIO storage assistant. You help users manage their MinIO object storage through available tools.

When the user asks about buckets, objects, storage status, or admin operations, use the available tools to get real data and provide accurate answers.

Keep responses concise and helpful. When showing tool results, summarize the key information clearly."""


@router.post("/api/demos/{demo_id}/minio/{cluster_id}/mcp/chat")
async def mcp_chat(demo_id: str, cluster_id: str, req: ChatRequest):
    """Stream a chat response with MCP tool access via local LLM."""
    # Verify MCP sidecar exists
    container_name = _resolve_mcp_container(demo_id, cluster_id)

    # Fetch available MCP tools
    try:
        tools_result = await _mcp_request(
            container_name,
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        mcp_tools = tools_result.get("tools", [])
    except Exception as e:
        logger.warning(f"Failed to fetch MCP tools: {e}")
        mcp_tools = []

    openai_tools = [_mcp_tool_to_openai(t) for t in mcp_tools]

    return StreamingResponse(
        _chat_stream(container_name, req.messages, openai_tools),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _chat_stream(container_name: str, messages: list[dict], tools: list[dict]):
    """Generator that streams chat responses, executing tool calls as needed."""
    endpoint = _llm_config["endpoint"]
    model = _llm_config["model"]
    api_type = _llm_config["api_type"]

    # Build the conversation with system prompt
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    # Determine API URL
    if api_type == "ollama":
        chat_url = f"{endpoint}/api/chat"
    else:
        chat_url = f"{endpoint}/v1/chat/completions"

    max_tool_rounds = 5
    for round_num in range(max_tool_rounds):
        try:
            if api_type == "ollama":
                body = {
                    "model": model,
                    "messages": full_messages,
                    "stream": True,
                    "tools": tools if tools else None,
                }
            else:
                body = {
                    "model": model,
                    "messages": full_messages,
                    "stream": True,
                    "tools": tools if tools else None,
                }
            # Remove None tools
            body = {k: v for k, v in body.items() if v is not None}

            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("POST", chat_url, json=body) as response:
                    if response.status_code != 200:
                        error_text = ""
                        async for chunk in response.aiter_text():
                            error_text += chunk
                        yield f"data: {json.dumps({'type': 'error', 'message': f'LLM request failed ({response.status_code}): {error_text[:200]}'})}\n\n"
                        return

                    accumulated_content = ""
                    tool_calls = []

                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue

                        # Ollama streams JSON objects, one per line
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if api_type == "ollama":
                            msg = chunk.get("message", {})
                            content = msg.get("content", "")
                            if content:
                                accumulated_content += content
                                yield f"data: {json.dumps({'type': 'text', 'content': content})}\n\n"

                            # Check for tool calls
                            if msg.get("tool_calls"):
                                for tc in msg["tool_calls"]:
                                    fn = tc.get("function", {})
                                    tool_calls.append({
                                        "name": fn.get("name", ""),
                                        "arguments": fn.get("arguments", {}),
                                    })

                            if chunk.get("done", False):
                                break
                        else:
                            # OpenAI-compatible streaming
                            choices = chunk.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    accumulated_content += content
                                    yield f"data: {json.dumps({'type': 'text', 'content': content})}\n\n"

                                if delta.get("tool_calls"):
                                    for tc in delta["tool_calls"]:
                                        fn = tc.get("function", {})
                                        tool_calls.append({
                                            "name": fn.get("name", ""),
                                            "arguments": json.loads(fn.get("arguments", "{}")),
                                        })

                    # If no tool calls, we're done
                    if not tool_calls:
                        yield f"data: {json.dumps({'type': 'done'})}\n\n"
                        return

                    # Execute tool calls via MCP
                    for tc in tool_calls:
                        yield f"data: {json.dumps({'type': 'tool_call', 'name': tc['name'], 'arguments': tc['arguments']})}\n\n"

                        try:
                            result = await _mcp_request(
                                container_name,
                                {
                                    "jsonrpc": "2.0",
                                    "id": 1,
                                    "method": "tools/call",
                                    "params": {"name": tc["name"], "arguments": tc["arguments"]},
                                },
                            )
                            # Extract text from MCP result
                            result_text = ""
                            if isinstance(result, dict):
                                for content_item in result.get("content", []):
                                    if content_item.get("type") == "text":
                                        result_text += content_item.get("text", "")
                            else:
                                result_text = str(result)

                            yield f"data: {json.dumps({'type': 'tool_result', 'name': tc['name'], 'result': result_text[:2000]})}\n\n"

                            # Add tool call + result to conversation for next round
                            full_messages.append({
                                "role": "assistant",
                                "content": accumulated_content,
                                "tool_calls": [{
                                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                                }],
                            })
                            full_messages.append({
                                "role": "tool",
                                "content": result_text[:2000],
                            })
                        except Exception as e:
                            yield f"data: {json.dumps({'type': 'tool_result', 'name': tc['name'], 'result': f'Error: {str(e)}'})}\n\n"
                            full_messages.append({
                                "role": "tool",
                                "content": f"Error: {str(e)}",
                            })

                    # Reset for next round (LLM will process tool results)
                    accumulated_content = ""
                    tool_calls = []

        except httpx.RequestError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Cannot reach LLM at {endpoint}: {str(e)}'})}\n\n"
            return
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

    yield f"data: {json.dumps({'type': 'done'})}\n\n"
