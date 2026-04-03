from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator

ALLOWED_EVENT_TYPES = {
    "demo_deployed",
    "demo_stopped",
    "demo_destroyed",
    "template_synced",
    "template_forked",
    "template_published",
    "manual_demo_created",
    "app_started",
    "app_stopped",
}


class FARegistrationRequest(BaseModel):
    fa_id: str
    fa_name: str
    api_key: str


class FAProfile(BaseModel):
    fa_id: str
    fa_name: str
    permissions: dict[str, Any]
    registered_at: str
    last_seen_at: str | None
    is_active: bool


class FAPermissions(BaseModel):
    manual_demo_creation: bool = True
    template_publish: bool = True
    template_fork: bool = True
    max_concurrent_demos: int = 5


class EventCreate(BaseModel):
    event_type: str
    payload: dict[str, Any] = {}
    timestamp: str

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        if v not in ALLOWED_EVENT_TYPES:
            raise ValueError(f"Unknown event type: {v}")
        return v


class EventResponse(BaseModel):
    id: int
    fa_id: str
    event_type: str
    payload: dict[str, Any]
    timestamp: str
    received_at: str


class FAListItem(BaseModel):
    fa_id: str
    fa_name: str
    is_active: bool
    last_seen_at: str | None
    registered_at: str
    event_count: int


class ActivityStats(BaseModel):
    total_fas: int
    active_fas: int
    total_events: int
    events_last_7_days: int
    events_last_30_days: int
    top_templates: list[dict[str, Any]]
    events_by_type: dict[str, int]


class StatusUpdate(BaseModel):
    is_active: bool


class BatchEventCreate(BaseModel):
    events: list[EventCreate]

    @field_validator("events")
    @classmethod
    def max_100(cls, v: list[EventCreate]) -> list[EventCreate]:
        if len(v) > 100:
            raise ValueError("Max 100 events per batch")
        return v
