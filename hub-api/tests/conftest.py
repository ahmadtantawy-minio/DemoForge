import json
import os
from datetime import datetime
from typing import Optional

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ["HUB_API_DATABASE_PATH"] = ":memory:"
os.environ["HUB_API_ADMIN_API_KEY"] = "test-admin-key"

from hub_api.config import settings  # noqa: E402
from hub_api.database import _create_tables, get_db  # noqa: E402
from hub_api.main import app  # noqa: E402

import aiosqlite  # noqa: E402

_test_db: Optional[aiosqlite.Connection] = None


async def _get_test_db():
    global _test_db
    yield _test_db


@pytest_asyncio.fixture()
async def client():
    global _test_db
    _test_db = await aiosqlite.connect(":memory:")
    _test_db.row_factory = aiosqlite.Row
    await _create_tables(_test_db)

    app.dependency_overrides[get_db] = _get_test_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await _test_db.close()
    _test_db = None


@pytest_asyncio.fixture()
async def registered_fa(client: AsyncClient):
    now = datetime.utcnow().isoformat() + "Z"
    permissions = json.dumps(settings.default_permissions)
    global _test_db
    await _test_db.execute(
        """INSERT INTO field_architects (fa_id, fa_name, api_key, permissions, registered_at, is_active)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("test-fa@minio.io", "Test FA", "df-test-key", permissions, now, 1),
    )
    await _test_db.commit()
    return {
        "fa_id": "test-fa@minio.io",
        "fa_name": "Test FA",
        "api_key": "df-test-key",
        "permissions": settings.default_permissions,
        "registered_at": now,
    }
