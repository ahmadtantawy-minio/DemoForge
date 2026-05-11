"""Instances API: composable routers (list/lifecycle, edges, SQL setup, etc.)."""
from fastapi import APIRouter

from .list_lifecycle import router as list_lifecycle_router
from .edges_cluster import router as edges_cluster_router
from .generator_external import router as generator_external_router
from .exec_logs import router as exec_logs_router
from .minio_scenario import router as minio_scenario_router
from .trino_tables import router as trino_tables_router
from .metabase_setup import router as metabase_setup_router
from .superset_setup import router as superset_setup_router
from .spark_etl_job import router as spark_etl_job_router

router = APIRouter()
router.include_router(list_lifecycle_router)
router.include_router(edges_cluster_router)
router.include_router(generator_external_router)
router.include_router(exec_logs_router)
router.include_router(minio_scenario_router)
router.include_router(trino_tables_router)
router.include_router(metabase_setup_router)
router.include_router(superset_setup_router)
router.include_router(spark_etl_job_router)
