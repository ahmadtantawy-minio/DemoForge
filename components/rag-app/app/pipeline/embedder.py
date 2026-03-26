import logging
import httpx
from ..config import settings

logger = logging.getLogger(__name__)


async def embed_text(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.OLLAMA_ENDPOINT}/api/embeddings",
            json={"model": settings.EMBEDDING_MODEL, "prompt": text},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["embedding"]


async def embed_chunks(chunks: list[dict]) -> list[tuple[dict, list[float]]]:
    results = []
    for chunk in chunks:
        try:
            vector = await embed_text(chunk["text"])
            results.append((chunk, vector))
        except Exception as e:
            logger.warning(f"Failed to embed chunk {chunk.get('index', '?')}: {e}")
    return results
