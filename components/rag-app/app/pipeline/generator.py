import logging
import httpx
from ..config import settings

logger = logging.getLogger(__name__)


async def generate_answer(question: str, context_chunks: list[dict]) -> dict:
    context_text = "\n\n".join(
        f"[Source: {c['filename']}]\n{c['text']}" for c in context_chunks
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful assistant. Answer the user's question based ONLY on the provided context. "
                "If the context doesn't contain enough information, say so. "
                "Always cite which source document(s) your answer comes from using [Source: filename] format."
            ),
        },
        {
            "role": "user",
            "content": f"Context:\n{context_text}\n\nQuestion: {question}",
        },
    ]

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{settings.OLLAMA_ENDPOINT}/api/chat",
            json={
                "model": settings.CHAT_MODEL,
                "messages": messages,
                "stream": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    answer = data.get("message", {}).get("content", "")
    tokens = data.get("eval_count", 0)

    return {"answer": answer, "tokens": tokens}
