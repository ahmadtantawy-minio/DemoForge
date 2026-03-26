import json
import uuid
import logging
from datetime import datetime, timezone
from .ingestion import get_s3_client, ensure_bucket
from ..config import settings

logger = logging.getLogger(__name__)


def log_query(question: str, answer: str, sources: list[dict], latency_ms: int):
    try:
        client = get_s3_client()
        ensure_bucket(client, settings.AUDIT_BUCKET)

        now = datetime.now(timezone.utc)
        date_prefix = now.strftime("%Y-%m-%d")
        timestamp = now.strftime("%H%M%S")
        record_id = str(uuid.uuid4())[:8]
        key = f"{date_prefix}/{timestamp}_{record_id}.json"

        record = {
            "timestamp": now.isoformat(),
            "question": question,
            "answer": answer,
            "sources": [{"filename": s.get("filename", ""), "score": s.get("score", 0)} for s in sources],
            "latency_ms": latency_ms,
        }

        client.put_object(
            Bucket=settings.AUDIT_BUCKET,
            Key=key,
            Body=json.dumps(record, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        logger.info(f"Audit log written: {key}")
    except Exception as e:
        logger.warning(f"Failed to write audit log: {e}")
