from __future__ import annotations

from typing import Any

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_path: str = "/data/hub-api/demoforge-hub.db"
    admin_api_key: str = "changeme"
    log_level: str = "INFO"
    default_permissions: dict[str, Any] = {
        "manual_demo_creation": True,
        "template_publish": True,
        "template_fork": True,
        "max_concurrent_demos": 5,
    }

    model_config = {"env_prefix": "HUB_API_"}


settings = Settings()
