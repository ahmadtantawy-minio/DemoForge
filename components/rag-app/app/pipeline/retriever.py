import uuid
import logging
from datetime import datetime, timezone
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from ..config import settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "documents"
VECTOR_DIM = 768


def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.QDRANT_ENDPOINT)


def ensure_collection(client: QdrantClient):
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in collections:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
        )
        logger.info(f"Created collection '{COLLECTION_NAME}' ({VECTOR_DIM} dims, cosine)")


def store_vectors(client: QdrantClient, chunks_with_vectors: list[tuple[dict, list[float]]], filename: str):
    ensure_collection(client)
    points = []
    now = datetime.now(timezone.utc).isoformat()
    for chunk, vector in chunks_with_vectors:
        point_id = str(uuid.uuid4())
        points.append(PointStruct(
            id=point_id,
            vector=vector,
            payload={
                "text": chunk["text"],
                "filename": filename,
                "chunk_index": chunk["index"],
                "ingested_at": now,
            },
        ))
    if points:
        client.upsert(collection_name=COLLECTION_NAME, points=points)
        logger.info(f"Stored {len(points)} vectors for '{filename}'")


def search(client: QdrantClient, query_vector: list[float], top_k: int = 5) -> list[dict]:
    ensure_collection(client)
    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_vector,
        limit=top_k,
    )
    return [
        {
            "text": hit.payload.get("text", ""),
            "filename": hit.payload.get("filename", ""),
            "score": hit.score,
        }
        for hit in results
    ]


def get_collection_info(client: QdrantClient) -> dict:
    try:
        info = client.get_collection(collection_name=COLLECTION_NAME)
        return {"points_count": info.points_count, "status": info.status.value}
    except Exception:
        return {"points_count": 0, "status": "not_found"}


def delete_collection(client: QdrantClient):
    try:
        client.delete_collection(collection_name=COLLECTION_NAME)
        logger.info(f"Deleted collection '{COLLECTION_NAME}'")
    except Exception as e:
        logger.warning(f"Failed to delete collection: {e}")
