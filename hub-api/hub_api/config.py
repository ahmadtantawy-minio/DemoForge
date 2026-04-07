from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_path: str = "/data/hub-api/demoforge-hub.db"
    admin_api_key: str = "changeme"
    sync_secret_key: str = ""   # read-only MinIO sync credentials for FA distribution
    sync_endpoint: str = ""     # HUB_API_SYNC_ENDPOINT — internal MinIO URL (e.g. http://10.10.0.2:9000)
    sync_bucket: str = "demoforge-templates"
    sync_prefix: str = "templates/"
    connector_key: str = ""     # shared gateway connector auth key — returned via bootstrap
    log_level: str = "INFO"
    default_permissions: dict[str, Any] = {
        "manual_demo_creation": False,
        "template_publish": False,
        "template_fork": False,
        "max_concurrent_demos": 5,
    }

    model_config = {"env_prefix": "HUB_API_"}


settings = Settings()
