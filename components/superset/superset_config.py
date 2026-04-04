import os

# ---------------------------------------------------------
# Superset DemoForge Configuration
# Single-container mode: SQLite metadata, no Redis, sync queries
# ---------------------------------------------------------

SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY", "demoforge-superset-secret-key-change-in-prod")

SQLALCHEMY_DATABASE_URI = "sqlite:////app/superset_home/superset.db"

CELERY_CONFIG = None
RESULTS_BACKEND = None

CACHE_CONFIG = {
    "CACHE_TYPE": "SimpleCache",
    "CACHE_DEFAULT_TIMEOUT": 300,
}

DATA_CACHE_CONFIG = {
    "CACHE_TYPE": "SimpleCache",
    "CACHE_DEFAULT_TIMEOUT": 300,
}

# CSRF disabled for local demo only — do not use in production
WTF_CSRF_ENABLED = False

ENABLE_CORS = True
PUBLIC_ROLE_LIKE = "Gamma"
FEATURE_FLAGS = {
    "DASHBOARD_NATIVE_FILTERS": True,
    "DASHBOARD_CROSS_FILTERS": True,
    "EMBEDDABLE_CHARTS": True,
    "EMBEDDED_SUPERSET": True,
    "ENABLE_TEMPLATE_PROCESSING": True,
}

SUPERSET_DASHBOARD_PERIODICAL_REFRESH_LIMIT = 0
SUPERSET_DASHBOARD_PERIODICAL_REFRESH_WARNING = 0

ROW_LIMIT = 50000
SQL_MAX_ROW = 100000

LOG_LEVEL = os.environ.get("SUPERSET_LOG_LEVEL", "WARNING")

SUPERSET_WEBSERVER_PORT = 8088
