"""Demo/container instance API routes (core + pool decommission)."""

from __future__ import annotations

from fastapi import APIRouter

from .core import router as core_router
from .pool_decommission import _parse_mc_decommission_status, router as pool_router

router = APIRouter()
router.include_router(core_router)
router.include_router(pool_router)

__all__ = ["router", "_parse_mc_decommission_status"]
