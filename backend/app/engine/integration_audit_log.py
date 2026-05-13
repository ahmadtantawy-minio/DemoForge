"""Append-only JSONL for the instances poll → LogViewer Integrations tab.

Used for mc / bucket / tiering / replication / edge actions. Keeps ``command`` and
``exit_code`` on each record when supplied. No imports from docker_manager (avoids cycles).
"""

from __future__ import annotations

import json
import os
import time
import uuid


def integration_audit_path(demo_id: str) -> str:
    demos_dir = os.environ.get("DEMOFORGE_DEMOS_DIR", "./demos")
    return os.path.join(demos_dir, demo_id, "integration_audit.jsonl")


def append_integration_audit_line(
    demo_id: str,
    level: str,
    kind: str,
    message: str,
    details: str = "",
    *,
    node_id: str | None = None,
    command: str | None = None,
    exit_code: int | None = None,
) -> None:
    path = integration_audit_path(demo_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rec: dict = {
            "id": str(uuid.uuid4()),
            "ts_ms": int(time.time() * 1000),
            "level": level,
            "kind": kind,
            "message": message,
            "details": details or "",
            "source": "backend",
            "node_id": node_id if node_id is not None else "setup-metabase",
        }
        if command is not None:
            rec["command"] = command
        if exit_code is not None:
            rec["exit_code"] = int(exit_code)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_integration_audit_tail(demo_id: str, limit: int = 400) -> list[dict]:
    path = integration_audit_path(demo_id)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        out: list[dict] = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if isinstance(rec, dict):
                    out.append(rec)
            except json.JSONDecodeError:
                continue
        return out
    except OSError:
        return []
