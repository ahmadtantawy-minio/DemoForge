"""Append-only JSONL log for Dev Logs → Integrations (backend polls /tmp/demoforge_integration.jsonl)."""
from __future__ import annotations

import json
import sys
import time
import uuid
from typing import Any

INTEGRATION_LOG_PATH = "/tmp/demoforge_integration.jsonl"


def append(level: str, kind: str, message: str, details: str = "") -> dict[str, Any]:
    rec: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "ts_ms": int(time.time() * 1000),
        "level": level,
        "kind": kind,
        "message": message,
        "details": details or "",
    }
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with open(INTEGRATION_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)
    return rec


def main() -> None:
    if len(sys.argv) < 4:
        print("usage: integration_log.py LEVEL KIND MESSAGE [DETAILS]", file=sys.stderr)
        sys.exit(2)
    level = sys.argv[1]
    kind = sys.argv[2]
    message = sys.argv[3]
    details = sys.argv[4] if len(sys.argv) > 4 else ""
    append(level, kind, message, details)


if __name__ == "__main__":
    main()
