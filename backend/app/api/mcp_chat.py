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

from __future__ import annotations

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

# --- LLM Configuration ---

_llm_config = {
    "endpoint": os.environ.get("DEMOFORGE_LLM_ENDPOINT", "http://host.docker.internal:11434"),
    "model": os.environ.get("DEMOFORGE_LLM_MODEL", "qwen2.5:14b"),
    "api_type": os.environ.get("DEMOFORGE_LLM_API_TYPE", "ollama"),
}

LLM_SETTINGS_FILE = os.path.join(
    os.environ.get("DEMOFORGE_DATA_DIR", "./data"), "llm_settings.json"
)


def _load_llm_config():
    try:
        if os.path.exists(LLM_SETTINGS_FILE):
            with open(LLM_SETTINGS_FILE) as f:
                _llm_config.update(json.load(f))
    except Exception:
        pass


def _save_llm_config():
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
    api_type: str | None = None


class ChatRequest(BaseModel):
    messages: list[dict[str, str]]


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


def _mcp_tool_to_openai(tool: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
        },
    }


SYSTEM_PROMPT = """You are a helpful MinIO storage assistant. You MUST always respond in English.

You help users manage their MinIO object storage through available tools. When the user asks about buckets, objects, storage status, or admin operations, use the available tools to get real data and provide accurate answers.

Keep responses concise and helpful. When showing tool results, summarize the key information clearly. Always respond in English."""


@router.post("/api/demos/{demo_id}/minio/{cluster_id}/mcp/chat")
async def mcp_chat(demo_id: str, cluster_id: str, req: ChatRequest):
    container_name = _resolve_mcp_container(demo_id, cluster_id)

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


async def _ollama_chat(endpoint: str, model: str, messages: list, tools: list) -> dict:
    """Non-streaming Ollama call — reliable for tool calling."""
    body = {"model": model, "messages": messages, "stream": False}
    if tools:
        body["tools"] = tools
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{endpoint}/api/chat", json=body)
        resp.raise_for_status()
        return resp.json()


async def _ollama_stream(endpoint: str, model: str, messages: list):
    """Streaming Ollama call — for final text-only response."""
    body = {"model": model, "messages": messages, "stream": True}
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", f"{endpoint}/api/chat", json=body) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
                if chunk.get("done", False):
                    break


async def _chat_stream(container_name: str, messages: list[dict], tools: list[dict]):
    """Generator: uses non-streaming for tool rounds, streaming for final answer."""
    endpoint = _llm_config["endpoint"]
    model = _llm_config["model"]

    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    max_tool_rounds = 5
    for round_num in range(max_tool_rounds):
        try:
            # Non-streaming call to handle tool calling reliably
            result = await _ollama_chat(endpoint, model, full_messages, tools)
        except httpx.RequestError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Cannot reach LLM at {endpoint}: {e}'})}\n\n"
            return
        except httpx.HTTPStatusError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'LLM error: {e.response.status_code}'})}\n\n"
            return

        msg = result.get("message", {})
        tool_calls = msg.get("tool_calls", [])

        if not tool_calls:
            # No tool calls — stream the final text content
            content = msg.get("content", "")
            if content:
                # Re-do as streaming for nice UX
                full_messages.append({"role": "assistant", "content": content})
                # Stream the already-generated content word by word for smooth UX
                words = content.split(" ")
                for i, word in enumerate(words):
                    token = word if i == 0 else " " + word
                    yield f"data: {json.dumps({'type': 'text', 'content': token})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        # Process tool calls
        assistant_content = msg.get("content", "")
        full_messages.append({
            "role": "assistant",
            "content": assistant_content,
            "tool_calls": tool_calls,
        })

        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            tool_args = fn.get("arguments", {})

            yield f"data: {json.dumps({'type': 'tool_call', 'name': tool_name, 'arguments': tool_args})}\n\n"

            try:
                mcp_result = await _mcp_request(
                    container_name,
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": tool_args},
                    },
                )
                result_text = ""
                if isinstance(mcp_result, dict):
                    for item in mcp_result.get("content", []):
                        if item.get("type") == "text":
                            result_text += item.get("text", "")
                else:
                    result_text = str(mcp_result)

                yield f"data: {json.dumps({'type': 'tool_result', 'name': tool_name, 'result': result_text[:2000]})}\n\n"

                full_messages.append({
                    "role": "tool",
                    "content": result_text[:2000],
                })
            except Exception as e:
                error_msg = f"Error: {str(e)}"
                yield f"data: {json.dumps({'type': 'tool_result', 'name': tool_name, 'result': error_msg})}\n\n"
                full_messages.append({"role": "tool", "content": error_msg})

    yield f"data: {json.dumps({'type': 'done'})}\n\n"
