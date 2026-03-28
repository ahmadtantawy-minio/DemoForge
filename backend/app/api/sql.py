"""Execute SQL statements against Trino containers in a running demo."""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx

from ..state.store import state

router = APIRouter()


class SqlExecuteRequest(BaseModel):
    sql: str
    catalog: str = "iceberg"
    schema_name: str = "default"


class SqlColumn(BaseModel):
    name: str
    type: str


class SqlExecuteResponse(BaseModel):
    success: bool
    columns: list[SqlColumn] = []
    rows: list[list] = []
    row_count: int = 0
    error: str = ""
    execution_time_ms: int = 0


@router.post("/api/demos/{demo_id}/sql", response_model=SqlExecuteResponse)
async def execute_sql(demo_id: str, req: SqlExecuteRequest):
    """Execute SQL against the Trino node in a running demo."""
    running = state.get_demo(demo_id)
    if not running:
        raise HTTPException(404, "Demo not running")

    # Find the Trino container
    trino_container = None
    for node_id, container in running.containers.items():
        if container.component_id == "trino":
            trino_container = container
            break

    if not trino_container:
        raise HTTPException(400, "No Trino node found in this demo")

    trino_url = f"http://{trino_container.container_name}:8080"
    start = time.time()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Submit query to Trino HTTP API
            resp = await client.post(
                f"{trino_url}/v1/statement",
                content=req.sql,
                headers={
                    "X-Trino-User": "demoforge",
                    "X-Trino-Catalog": req.catalog,
                    "X-Trino-Schema": req.schema_name,
                },
            )
            result = resp.json()

            # Poll for results (Trino is async)
            columns: list[SqlColumn] = []
            rows: list[list] = []
            while True:
                if "columns" in result and not columns:
                    columns = [
                        SqlColumn(name=c["name"], type=c.get("type", "unknown"))
                        for c in result["columns"]
                    ]
                if "data" in result:
                    rows.extend(result["data"])

                next_uri = result.get("nextUri")
                if not next_uri:
                    break

                resp = await client.get(next_uri)
                result = resp.json()

            elapsed = int((time.time() - start) * 1000)

            if result.get("error"):
                return SqlExecuteResponse(
                    success=False,
                    error=result["error"].get("message", "Unknown error"),
                    execution_time_ms=elapsed,
                )

            return SqlExecuteResponse(
                success=True,
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_time_ms=elapsed,
            )

    except Exception as e:
        return SqlExecuteResponse(
            success=False,
            error=str(e),
            execution_time_ms=int((time.time() - start) * 1000),
        )
