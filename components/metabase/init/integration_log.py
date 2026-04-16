"""Append-only JSONL for Integrations tab (backend polls /tmp/demoforge_integration.jsonl in metabase-init). Offline-only — local file, no network."""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

INTEGRATION_LOG_PATH = os.environ.get("METABASE_INTEGRATION_LOG", "/tmp/demoforge_integration.jsonl")


def append(level: str, kind: str, message: str, details: str = "") -> dict[str, Any]:
    rec: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "ts_ms": int(time.time() * 1000),
        "level": level,
        "kind": kind,
        "message": message,
        "details": details or "",
        "source": "metabase-init",
    }
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    try:
        with open(INTEGRATION_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    return rec
