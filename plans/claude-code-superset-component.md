# DemoForge: Apache Superset Component — Full Implementation

## Overview

Add Apache Superset as an alternative BI/visualization component in DemoForge, replacing or complementing Metabase. Superset connects to Trino, which queries Iceberg tables stored in MinIO. The component includes a custom Docker image, a component manifest, an API-driven seed script that provisions 5 dashboards on startup, and integration with existing demo templates.

**This file is fully self-contained. Do not reference other instruction files.**

---

## PHASE 0: Pre-Implementation Architect Review

**Agent: Architect (read-only investigation)**

Before writing any code, review the current codebase to confirm assumptions and identify integration points. Report findings before proceeding.

### 0.1 — Investigate current Metabase implementation

```
Find and read these files:
- components/data-generator/src/metabase_setup.py (the existing Metabase seed script — this is our blueprint)
- The Metabase component manifest YAML (search manifests/ or components/ for metabase)
- Any scenario YAML files that reference metabase dashboard provisioning
- The data-generator Dockerfile and entrypoint to understand how metabase_setup.py gets called

Document:
1. How metabase_setup.py is invoked (entrypoint? sidecar? init container? separate service?)
2. The exact REST API flow it uses (auth → database → questions → dashboard)
3. How it waits for Metabase to be ready (polling? health check?)
4. How dashboard SQL queries are defined (inline in Python? external SQL files? YAML?)
5. The full list of charts per dashboard with their SQL queries
6. How the Metabase component manifest defines ports, env vars, health checks, dependencies
7. How demo template YAMLs reference/enable the Metabase component
```

### 0.2 — Investigate data generator table setup

```
Find and read:
- components/data-generator/src/table_setup.py
- Any SQL files or DDL templates in the data-generator component
- The data-generator component manifest YAML

Document:
1. Exact Trino catalog/schema/table names created (confirm: iceberg.demo.orders, iceberg.demo.sensor_readings, iceberg.demo.transactions, iceberg.demo.clickstream, iceberg.default.customer_360)
2. Exact column names, types, and partition specs per table
3. The order of operations: does table_setup run before or after the BI tool setup?
4. MinIO bucket names used (confirm: analytics, warehouse)
```

### 0.3 — Investigate component manifest structure

```
Find and read:
- 3-5 existing component manifest YAML files to understand the schema
- The manifest loader code (how does DemoForge parse and use manifests?)
- How components declare dependencies on other components
- How components declare ports, volumes, environment variables
- How components declare health checks
- How image references work (vendor images vs custom demoforge/ images)

Document the manifest YAML schema with a concrete example.
```

### 0.4 — Investigate demo template structure

```
Find and read:
- 2-3 demo template YAMLs that include Metabase
- How templates reference components (by name? by manifest path?)
- How templates can offer alternative components (e.g., "use Superset instead of Metabase")
- How template-specific configuration overrides work

Document how we would add Superset as an option in existing templates.
```

### 0.5 — Architect Review Gate

**STOP HERE. Present all findings from 0.1–0.4 before proceeding.**

The findings will likely reveal:
- The exact metabase_setup.py API flow to mirror
- Whether the setup script runs as part of the data-generator or as a separate init process
- The manifest schema we need to follow
- Any patterns or conventions we should match

Confirm or correct these assumptions before Phase 1:
- Superset will be a standalone component (not bundled into data-generator)
- The seed script (superset_setup.py) will live in the data-generator component alongside metabase_setup.py
- Superset will run as a single container with SQLite metadata (no Postgres/Redis/Celery)
- The connection URI to Trino is: `trino://demoforge@trino:8080/iceberg`
- We need 5 seed dashboards matching the 5 datasets

---

## PHASE 1: Custom Docker Image

**Agent: Backend engineer**

### 1.1 — Create the Dockerfile

Location: `components/superset/Dockerfile`

```dockerfile
FROM apache/superset:4.1.2

USER root

# Install Trino SQLAlchemy driver
RUN pip install --no-cache-dir trino[sqlalchemy]

# Copy bootstrap config
COPY superset_config.py /app/superset_config.py
ENV SUPERSET_CONFIG_PATH=/app/superset_config.py

# Copy init script
COPY superset-init.sh /app/superset-init.sh
RUN chmod +x /app/superset-init.sh

USER superset

EXPOSE 8088

ENTRYPOINT ["/app/superset-init.sh"]
```

### 1.2 — Create superset_config.py

Location: `components/superset/superset_config.py`

This configures Superset for single-container demo mode:

```python
import os

# ---------------------------------------------------------
# Superset DemoForge Configuration
# Single-container mode: SQLite metadata, no Redis, sync queries
# ---------------------------------------------------------

# Secret key (not security-sensitive for local demos)
SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY", "demoforge-superset-secret-key-change-in-prod")

# SQLite metadata database (no external Postgres needed)
SQLALCHEMY_DATABASE_URI = "sqlite:////app/superset_home/superset.db"

# Disable Redis/Celery — run queries synchronously
class CeleryConfig:
    pass

CELERY_CONFIG = None
RESULTS_BACKEND = None

# Cache config — use simple in-memory cache
CACHE_CONFIG = {
    "CACHE_TYPE": "SimpleCache",
    "CACHE_DEFAULT_TIMEOUT": 300,
}

DATA_CACHE_CONFIG = {
    "CACHE_TYPE": "SimpleCache",
    "CACHE_DEFAULT_TIMEOUT": 300,
}

# Disable CSRF for API access (local demo only)
WTF_CSRF_ENABLED = False

# Enable embedding and public dashboards
ENABLE_CORS = True
PUBLIC_ROLE_LIKE = "Gamma"
FEATURE_FLAGS = {
    "DASHBOARD_NATIVE_FILTERS": True,
    "DASHBOARD_CROSS_FILTERS": True,
    "EMBEDDABLE_CHARTS": True,
    "EMBEDDED_SUPERSET": True,
    "ENABLE_TEMPLATE_PROCESSING": True,
}

# Auto-refresh defaults
SUPERSET_DASHBOARD_PERIODICAL_REFRESH_LIMIT = 0  # no limit
SUPERSET_DASHBOARD_PERIODICAL_REFRESH_WARNING = 0

# Trino-specific: increase row limit for live demos
ROW_LIMIT = 50000
SQL_MAX_ROW = 100000

# Logging
LOG_LEVEL = os.environ.get("SUPERSET_LOG_LEVEL", "WARNING")

# Listen on all interfaces
SUPERSET_WEBSERVER_PORT = 8088
```

### 1.3 — Create superset-init.sh

Location: `components/superset/superset-init.sh`

```bash
#!/bin/bash
set -e

echo "[superset-init] Initializing Superset database..."
superset db upgrade

echo "[superset-init] Creating admin user..."
superset fab create-admin \
  --username admin \
  --firstname DemoForge \
  --lastname Admin \
  --email admin@demoforge.local \
  --password admin \
  2>/dev/null || true

echo "[superset-init] Initializing roles and permissions..."
superset init

echo "[superset-init] Starting Superset server..."
exec superset run \
  --host 0.0.0.0 \
  --port 8088 \
  --with-threads \
  --reload
```

### 1.4 — Verify the image builds and starts

```bash
cd components/superset
docker build -t demoforge/superset:latest .
docker run -d --name superset-test -p 8088:8088 demoforge/superset:latest

# Wait for startup
sleep 30

# Verify health
curl -s http://localhost:8088/health | grep -q "OK"

# Verify login works
curl -s -X POST http://localhost:8088/api/v1/security/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin","provider":"db","refresh":true}' \
  | grep -q "access_token"

# Cleanup
docker rm -f superset-test
```

---

## PHASE 2: Component Manifest

**Agent: Backend engineer**

### 2.1 — Create the Superset component manifest

Location: Follow the same directory/naming convention as existing manifests (discovered in Phase 0).

The manifest must include:

```yaml
# Match the exact schema discovered in Phase 0.3
# Below is the expected content — adjust field names to match actual schema

name: superset
display_name: Apache Superset
description: "Open-source BI and data visualization platform. Connects to Trino to query Iceberg tables and provides interactive dashboards with auto-refresh."
category: visualization  # or whatever category Metabase uses
icon: superset  # or a URL to an icon

image: demoforge/superset:latest
image_size_mb: 1800  # approximate, verify after build

ports:
  - container_port: 8088
    host_port: 8088
    protocol: http
    label: Superset UI

environment:
  SUPERSET_SECRET_KEY: "demoforge-superset-secret-key"
  SUPERSET_LOG_LEVEL: "WARNING"

health_check:
  endpoint: /health
  port: 8088
  interval: 10
  timeout: 5
  retries: 30  # Superset takes ~30-45s to start
  start_period: 45

dependencies:
  - trino  # must be running before Superset

volumes: []  # SQLite DB is ephemeral — fine for demos

# Tags for template gallery filtering
tags:
  - bi
  - visualization
  - dashboards
  - reporting

# Alternative to Metabase — same role, different tool
alternatives:
  - metabase
```

### 2.2 — Verify manifest loads correctly

After creating the manifest, run whatever validation the manifest loader uses (discovered in Phase 0.3) to confirm it parses without errors.

---

## PHASE 3: Seed Dashboard Script (superset_setup.py)

**Agent: Backend engineer — this is the largest and most critical phase**

### 3.0 — Location and invocation

Place `superset_setup.py` alongside `metabase_setup.py` in the data-generator component. Follow the exact same invocation pattern discovered in Phase 0.1.

The script must:
- Detect whether Superset or Metabase is running (check which port responds)
- Call the appropriate setup function
- Be idempotent (safe to run multiple times)
- Wait for Superset to be fully ready before provisioning

### 3.1 — Superset REST API helper class

```python
"""
superset_setup.py — Provision seed dashboards in Apache Superset via REST API.

Mirrors the functionality of metabase_setup.py but targets Superset.
Creates 5 dashboards with ~34 charts total across all datasets.

Usage:
    Called by data-generator entrypoint when Superset is detected.
    Requires: SUPERSET_URL env var (default: http://superset:8088)
"""

import os
import sys
import time
import json
import logging
import requests
from typing import Optional

logger = logging.getLogger("superset_setup")

SUPERSET_URL = os.environ.get("SUPERSET_URL", "http://superset:8088")
SUPERSET_USER = os.environ.get("SUPERSET_USER", "admin")
SUPERSET_PASS = os.environ.get("SUPERSET_PASS", "admin")
TRINO_URI = os.environ.get("TRINO_URI", "trino://demoforge@trino:8080/iceberg")


class SupersetClient:
    """REST API client for Apache Superset."""

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.access_token = None
        self.csrf_token = None
        self._login(username, password)

    def _login(self, username: str, password: str):
        """Authenticate and obtain JWT + CSRF tokens."""
        resp = self.session.post(
            f"{self.base_url}/api/v1/security/login",
            json={
                "username": username,
                "password": password,
                "provider": "db",
                "refresh": True,
            },
        )
        resp.raise_for_status()
        self.access_token = resp.json()["access_token"]
        self.session.headers.update({
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        })
        # Get CSRF token
        csrf_resp = self.session.get(f"{self.base_url}/api/v1/security/csrf_token/")
        if csrf_resp.ok:
            self.csrf_token = csrf_resp.json().get("result")
            if self.csrf_token:
                self.session.headers["X-CSRFToken"] = self.csrf_token

    def _api(self, method: str, endpoint: str, **kwargs):
        """Make an API call with error handling."""
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"
        resp = self.session.request(method, url, **kwargs)
        if resp.status_code == 422:
            logger.warning(f"422 on {method} {endpoint}: {resp.text}")
            return None
        resp.raise_for_status()
        return resp.json()

    def get(self, endpoint: str, **kwargs):
        return self._api("GET", endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs):
        return self._api("POST", endpoint, **kwargs)

    def put(self, endpoint: str, **kwargs):
        return self._api("PUT", endpoint, **kwargs)

    # ── Database ─────────────────────────────────────────

    def create_database(self, name: str, sqlalchemy_uri: str) -> int:
        """Create or find a database connection. Returns database ID."""
        # Check if already exists
        existing = self.get("database/", params={"q": json.dumps({"filters": [{"col": "database_name", "opr": "eq", "value": name}]})})
        if existing and existing.get("count", 0) > 0:
            db_id = existing["result"][0]["id"]
            logger.info(f"Database '{name}' already exists (id={db_id})")
            return db_id

        result = self.post("database/", json={
            "database_name": name,
            "sqlalchemy_uri": sqlalchemy_uri,
            "expose_in_sqllab": True,
            "allow_ctas": False,
            "allow_cvas": False,
            "allow_dml": False,
            "allow_run_async": False,
            "extra": json.dumps({
                "engine_params": {
                    "connect_args": {
                        "http_scheme": "http",
                    }
                },
                "metadata_params": {},
                "schemas_allowed_for_file_upload": [],
            }),
        })
        db_id = result["id"]
        logger.info(f"Created database '{name}' (id={db_id})")
        return db_id

    # ── Dataset ──────────────────────────────────────────

    def create_dataset(self, database_id: int, schema: str, table_name: str) -> int:
        """Create or find a dataset. Returns dataset ID."""
        # Check if already exists
        existing = self.get("dataset/", params={"q": json.dumps({"filters": [
            {"col": "table_name", "opr": "eq", "value": table_name},
            {"col": "schema", "opr": "eq", "value": schema},
        ]})})
        if existing and existing.get("count", 0) > 0:
            ds_id = existing["result"][0]["id"]
            logger.info(f"Dataset '{schema}.{table_name}' already exists (id={ds_id})")
            return ds_id

        result = self.post("dataset/", json={
            "database": database_id,
            "schema": schema,
            "table_name": table_name,
        })
        ds_id = result["id"]
        logger.info(f"Created dataset '{schema}.{table_name}' (id={ds_id})")
        return ds_id

    # ── Chart ────────────────────────────────────────────

    def create_chart(
        self,
        name: str,
        viz_type: str,
        datasource_id: int,
        params: dict,
        query_context: Optional[dict] = None,
    ) -> int:
        """Create a chart. Returns chart ID."""
        # Check if already exists
        existing = self.get("chart/", params={"q": json.dumps({"filters": [{"col": "slice_name", "opr": "eq", "value": name}]})})
        if existing and existing.get("count", 0) > 0:
            chart_id = existing["result"][0]["id"]
            logger.info(f"Chart '{name}' already exists (id={chart_id})")
            return chart_id

        payload = {
            "slice_name": name,
            "viz_type": viz_type,
            "datasource_id": datasource_id,
            "datasource_type": "table",
            "params": json.dumps(params),
        }
        if query_context:
            payload["query_context"] = json.dumps(query_context)

        result = self.post("chart/", json=payload)
        chart_id = result["id"]
        logger.info(f"Created chart '{name}' (id={chart_id})")
        return chart_id

    # ── Dashboard ────────────────────────────────────────

    def create_dashboard(
        self,
        title: str,
        slug: str,
        chart_ids: list[int],
        position_json: dict,
        css: str = "",
        json_metadata: Optional[dict] = None,
    ) -> int:
        """Create a dashboard with positioned charts. Returns dashboard ID."""
        # Check if already exists
        existing = self.get("dashboard/", params={"q": json.dumps({"filters": [{"col": "slug", "opr": "eq", "value": slug}]})})
        if existing and existing.get("count", 0) > 0:
            dash_id = existing["result"][0]["id"]
            logger.info(f"Dashboard '{title}' already exists (id={dash_id})")
            return dash_id

        metadata = json_metadata or {
            "timed_refresh_immune_slices": [],
            "expanded_slices": {},
            "refresh_frequency": 10,
            "default_filters": "{}",
            "color_scheme": "supersetColors",
        }

        result = self.post("dashboard/", json={
            "dashboard_title": title,
            "slug": slug,
            "position_json": json.dumps(position_json),
            "css": css,
            "json_metadata": json.dumps(metadata),
            "published": True,
        })
        dash_id = result["id"]
        logger.info(f"Created dashboard '{title}' (id={dash_id})")
        return dash_id
```

### 3.2 — Dashboard position layout helper

Superset uses a 12-column grid. Each chart is placed in a `CHART-{id}` key within the position JSON. Build a helper to generate layouts:

```python
def build_position_json(chart_layout: list[dict]) -> dict:
    """
    Build Superset dashboard position JSON from a simplified layout spec.

    chart_layout: list of dicts with keys:
        - chart_id: int
        - row: int (0-indexed row in grid)
        - col: int (0-11 column position)
        - width: int (1-12 columns)
        - height: int (grid units, typically 8-16)

    Returns the full position_json dict for the dashboard API.
    """
    position = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {
            "type": "GRID",
            "id": "GRID_ID",
            "children": [],  # filled below
            "parents": ["ROOT_ID"],
        },
        "HEADER_ID": {
            "type": "HEADER",
            "id": "HEADER_ID",
            "meta": {"text": ""},
        },
    }

    # Group charts by row
    rows = {}
    for item in chart_layout:
        r = item["row"]
        if r not in rows:
            rows[r] = []
        rows[r].append(item)

    for row_idx in sorted(rows.keys()):
        row_id = f"ROW-row{row_idx}"
        position["GRID_ID"]["children"].append(row_id)
        position[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": [],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }

        for item in sorted(rows[row_idx], key=lambda x: x["col"]):
            chart_key = f"CHART-{item['chart_id']}"
            position[row_id]["children"].append(chart_key)
            position[chart_key] = {
                "type": "CHART",
                "id": chart_key,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "meta": {
                    "width": item["width"],
                    "height": item["height"],
                    "chartId": item["chart_id"],
                    "sliceName": item.get("name", ""),
                },
            }

    return position
```

### 3.3 — Dashboard 1: Live Orders Analytics

**Dataset**: `iceberg.demo.orders`
**Charts** (8 total):

```python
def create_orders_dashboard(client: SupersetClient, db_id: int, ds_id: int) -> int:
    """Create the Live Orders Analytics dashboard with 8 charts."""

    charts = []

    # ── KPI 1: Total Orders ──
    charts.append(client.create_chart(
        name="Orders: Total Count",
        viz_type="big_number_total",
        datasource_id=ds_id,
        params={
            "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Total Orders"},
            "header_font_size": 0.4,
            "subheader_font_size": 0.15,
            "y_axis_format": "SMART_NUMBER",
        },
    ))

    # ── KPI 2: Total Revenue ──
    charts.append(client.create_chart(
        name="Orders: Total Revenue",
        viz_type="big_number_total",
        datasource_id=ds_id,
        params={
            "metric": {"expressionType": "SQL", "sqlExpression": "SUM(total_amount)", "label": "Revenue"},
            "header_font_size": 0.4,
            "subheader_font_size": 0.15,
            "y_axis_format": "$,.2f",
        },
    ))

    # ── KPI 3: Avg Order Value ──
    charts.append(client.create_chart(
        name="Orders: Avg Order Value",
        viz_type="big_number_total",
        datasource_id=ds_id,
        params={
            "metric": {"expressionType": "SQL", "sqlExpression": "AVG(total_amount)", "label": "Avg Order"},
            "header_font_size": 0.4,
            "subheader_font_size": 0.15,
            "y_axis_format": "$,.2f",
        },
    ))

    # ── Orders per Minute (line) ──
    charts.append(client.create_chart(
        name="Orders: Orders/min",
        viz_type="echarts_timeseries_line",
        datasource_id=ds_id,
        params={
            "x_axis": "order_ts",
            "time_grain_sqla": "PT1M",
            "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "orders/min"}],
            "row_limit": 1000,
            "truncate_metric": True,
            "show_legend": False,
            "rich_tooltip": True,
            "x_axis_time_format": "%H:%M",
        },
    ))

    # ── Revenue by Region (bar) ──
    charts.append(client.create_chart(
        name="Orders: Revenue by Region",
        viz_type="echarts_bar",
        datasource_id=ds_id,
        params={
            "x_axis": "region",
            "metrics": [{"expressionType": "SQL", "sqlExpression": "SUM(total_amount)", "label": "Revenue"}],
            "groupby": ["region"],
            "row_limit": 10,
            "y_axis_format": "$,.0f",
            "color_scheme": "supersetColors",
            "show_legend": False,
        },
    ))

    # ── Top 5 Products (horizontal bar) ──
    charts.append(client.create_chart(
        name="Orders: Top Products",
        viz_type="echarts_bar",
        datasource_id=ds_id,
        params={
            "x_axis": "product_name",
            "metrics": [{"expressionType": "SQL", "sqlExpression": "SUM(total_amount)", "label": "Revenue"}],
            "groupby": ["product_name"],
            "row_limit": 5,
            "order_desc": True,
            "orientation": "horizontal",
            "y_axis_format": "$,.0f",
            "show_legend": False,
        },
    ))

    # ── Category Breakdown (pie) ──
    charts.append(client.create_chart(
        name="Orders: Categories",
        viz_type="pie",
        datasource_id=ds_id,
        params={
            "groupby": ["category"],
            "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Orders"},
            "donut": True,
            "show_labels": True,
            "label_type": "key_percent",
            "color_scheme": "supersetColors",
        },
    ))

    # ── Payment Method (donut) ──
    charts.append(client.create_chart(
        name="Orders: Payment Methods",
        viz_type="pie",
        datasource_id=ds_id,
        params={
            "groupby": ["payment_method"],
            "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Orders"},
            "donut": True,
            "show_labels": True,
            "label_type": "key_percent",
            "color_scheme": "supersetColors",
        },
    ))

    # ── Build dashboard layout (12-col grid) ──
    # Row 0: 3 KPIs (4 cols each)
    # Row 1: Orders/min line (full width)
    # Row 2: Revenue by Region (6) + Top Products (6)
    # Row 3: Categories pie (6) + Payment donut (6)
    layout = [
        {"chart_id": charts[0], "row": 0, "col": 0, "width": 4, "height": 8, "name": "Total Orders"},
        {"chart_id": charts[1], "row": 0, "col": 4, "width": 4, "height": 8, "name": "Total Revenue"},
        {"chart_id": charts[2], "row": 0, "col": 8, "width": 4, "height": 8, "name": "Avg Order Value"},
        {"chart_id": charts[3], "row": 1, "col": 0, "width": 12, "height": 12, "name": "Orders/min"},
        {"chart_id": charts[4], "row": 2, "col": 0, "width": 6, "height": 12, "name": "Revenue by Region"},
        {"chart_id": charts[5], "row": 2, "col": 6, "width": 6, "height": 12, "name": "Top Products"},
        {"chart_id": charts[6], "row": 3, "col": 0, "width": 6, "height": 12, "name": "Categories"},
        {"chart_id": charts[7], "row": 3, "col": 6, "width": 6, "height": 12, "name": "Payment Methods"},
    ]

    return client.create_dashboard(
        title="Live Orders Analytics",
        slug="live-orders",
        chart_ids=charts,
        position_json=build_position_json(layout),
    )
```

### 3.4 — Dashboard 2: IoT Sensor Monitoring

**Dataset**: `iceberg.demo.sensor_readings`
**Charts** (7 total):

```python
def create_iot_dashboard(client: SupersetClient, db_id: int, ds_id: int) -> int:
    """Create the IoT Sensor Monitoring dashboard with 7 charts."""

    charts = []

    # ── KPI 1: Total Readings ──
    charts.append(client.create_chart(
        name="IoT: Total Readings",
        viz_type="big_number_total",
        datasource_id=ds_id,
        params={
            "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Readings"},
            "header_font_size": 0.4,
            "y_axis_format": "SMART_NUMBER",
        },
    ))

    # ── KPI 2: Active Sensors ──
    charts.append(client.create_chart(
        name="IoT: Active Sensors",
        viz_type="big_number_total",
        datasource_id=ds_id,
        params={
            "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(DISTINCT device_id)", "label": "Sensors"},
            "header_font_size": 0.4,
            "y_axis_format": "SMART_NUMBER",
        },
    ))

    # ── KPI 3: Critical Alerts ──
    charts.append(client.create_chart(
        name="IoT: Critical Alerts",
        viz_type="big_number_total",
        datasource_id=ds_id,
        params={
            "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*) FILTER (WHERE alert_level = 'critical')", "label": "Critical"},
            "header_font_size": 0.4,
            "y_axis_format": "SMART_NUMBER",
        },
    ))

    # ── Readings per Minute (line) ──
    charts.append(client.create_chart(
        name="IoT: Readings/min",
        viz_type="echarts_timeseries_line",
        datasource_id=ds_id,
        params={
            "x_axis": "reading_ts",
            "time_grain_sqla": "PT1M",
            "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "readings/min"}],
            "row_limit": 1000,
            "show_legend": False,
            "x_axis_time_format": "%H:%M",
        },
    ))

    # ── Alert Level Distribution (donut) ──
    charts.append(client.create_chart(
        name="IoT: Alert Levels",
        viz_type="pie",
        datasource_id=ds_id,
        params={
            "groupby": ["alert_level"],
            "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Count"},
            "donut": True,
            "show_labels": True,
            "label_type": "key_percent",
            "color_scheme": "supersetColors",
        },
    ))

    # ── Avg Temperature by Facility (bar) ──
    charts.append(client.create_chart(
        name="IoT: Temp by Facility",
        viz_type="echarts_bar",
        datasource_id=ds_id,
        params={
            "x_axis": "facility",
            "metrics": [{"expressionType": "SQL", "sqlExpression": "ROUND(AVG(temperature_c), 1)", "label": "Avg Temp (°C)"}],
            "groupby": ["facility"],
            "y_axis_format": ",.1f",
            "show_legend": False,
        },
    ))

    # ── Battery Distribution (bar) ──
    charts.append(client.create_chart(
        name="IoT: Battery Levels",
        viz_type="echarts_bar",
        datasource_id=ds_id,
        params={
            "x_axis": "battery_pct",
            "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Sensors"}],
            "groupby": ["battery_pct"],
            "row_limit": 100,
            "show_legend": False,
        },
    ))

    layout = [
        {"chart_id": charts[0], "row": 0, "col": 0, "width": 4, "height": 8, "name": "Total Readings"},
        {"chart_id": charts[1], "row": 0, "col": 4, "width": 4, "height": 8, "name": "Active Sensors"},
        {"chart_id": charts[2], "row": 0, "col": 8, "width": 4, "height": 8, "name": "Critical Alerts"},
        {"chart_id": charts[3], "row": 1, "col": 0, "width": 12, "height": 12, "name": "Readings/min"},
        {"chart_id": charts[4], "row": 2, "col": 0, "width": 4, "height": 12, "name": "Alert Levels"},
        {"chart_id": charts[5], "row": 2, "col": 4, "width": 4, "height": 12, "name": "Temp by Facility"},
        {"chart_id": charts[6], "row": 2, "col": 8, "width": 4, "height": 12, "name": "Battery Levels"},
    ]

    return client.create_dashboard(
        title="IoT Sensor Monitoring",
        slug="iot-sensors",
        chart_ids=charts,
        position_json=build_position_json(layout),
    )
```

### 3.5 — Dashboard 3: Financial Transactions Monitor

**Dataset**: `iceberg.demo.transactions`
**Charts** (7 total):

```python
def create_financial_dashboard(client: SupersetClient, db_id: int, ds_id: int) -> int:
    """Create the Financial Transactions Monitor dashboard with 7 charts."""

    charts = []

    # ── KPI 1: Total Transactions ──
    charts.append(client.create_chart(
        name="Fin: Total Transactions",
        viz_type="big_number_total",
        datasource_id=ds_id,
        params={
            "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Transactions"},
            "header_font_size": 0.4,
            "y_axis_format": "SMART_NUMBER",
        },
    ))

    # ── KPI 2: Total Volume ──
    charts.append(client.create_chart(
        name="Fin: Total Volume",
        viz_type="big_number_total",
        datasource_id=ds_id,
        params={
            "metric": {"expressionType": "SQL", "sqlExpression": "SUM(amount)", "label": "Volume"},
            "header_font_size": 0.4,
            "y_axis_format": "$,.0f",
        },
    ))

    # ── KPI 3: Flagged Rate ──
    charts.append(client.create_chart(
        name="Fin: Flagged %",
        viz_type="big_number_total",
        datasource_id=ds_id,
        params={
            "metric": {"expressionType": "SQL", "sqlExpression": "ROUND(100.0 * COUNT(*) FILTER (WHERE flagged = true) / NULLIF(COUNT(*), 0), 2)", "label": "Flagged %"},
            "header_font_size": 0.4,
            "y_axis_format": ",.2f",
        },
    ))

    # ── Transactions per Minute (line) ──
    charts.append(client.create_chart(
        name="Fin: Txns/min",
        viz_type="echarts_timeseries_line",
        datasource_id=ds_id,
        params={
            "x_axis": "txn_ts",
            "time_grain_sqla": "PT1M",
            "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "txns/min"}],
            "row_limit": 1000,
            "show_legend": False,
            "x_axis_time_format": "%H:%M",
        },
    ))

    # ── Volume by Currency (bar) ──
    charts.append(client.create_chart(
        name="Fin: Volume by Currency",
        viz_type="echarts_bar",
        datasource_id=ds_id,
        params={
            "x_axis": "currency",
            "metrics": [{"expressionType": "SQL", "sqlExpression": "SUM(amount)", "label": "Volume"}],
            "groupby": ["currency"],
            "order_desc": True,
            "y_axis_format": "$,.0f",
            "show_legend": False,
        },
    ))

    # ── Channel Breakdown (donut) ──
    charts.append(client.create_chart(
        name="Fin: Channels",
        viz_type="pie",
        datasource_id=ds_id,
        params={
            "groupby": ["channel"],
            "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Txns"},
            "donut": True,
            "show_labels": True,
            "label_type": "key_percent",
        },
    ))

    # ── High-Risk Accounts (table) ──
    charts.append(client.create_chart(
        name="Fin: High-Risk Accounts",
        viz_type="table",
        datasource_id=ds_id,
        params={
            "query_mode": "raw",
            "all_columns": ["account_from", "country", "risk_score", "compliance_status", "amount", "txn_type"],
            "adhoc_filters": [{
                "expressionType": "SQL",
                "sqlExpression": "risk_score > 0.65",
                "clause": "WHERE",
            }],
            "order_by_cols": [json.dumps(["risk_score", False])],
            "row_limit": 50,
            "page_length": 15,
        },
    ))

    layout = [
        {"chart_id": charts[0], "row": 0, "col": 0, "width": 4, "height": 8, "name": "Total Txns"},
        {"chart_id": charts[1], "row": 0, "col": 4, "width": 4, "height": 8, "name": "Total Volume"},
        {"chart_id": charts[2], "row": 0, "col": 8, "width": 4, "height": 8, "name": "Flagged %"},
        {"chart_id": charts[3], "row": 1, "col": 0, "width": 12, "height": 12, "name": "Txns/min"},
        {"chart_id": charts[4], "row": 2, "col": 0, "width": 6, "height": 12, "name": "Volume by Currency"},
        {"chart_id": charts[5], "row": 2, "col": 6, "width": 6, "height": 12, "name": "Channels"},
        {"chart_id": charts[6], "row": 3, "col": 0, "width": 12, "height": 14, "name": "High-Risk Accounts"},
    ]

    return client.create_dashboard(
        title="Financial Transactions Monitor",
        slug="financial-txns",
        chart_ids=charts,
        position_json=build_position_json(layout),
    )
```

### 3.6 — Dashboard 4: Real-time Clickstream

**Dataset**: `iceberg.demo.clickstream`
**Charts** (5 total):

```python
def create_clickstream_dashboard(client: SupersetClient, db_id: int, ds_id: int) -> int:
    """Create the Real-time Clickstream dashboard with 5 charts."""

    charts = []

    # ── KPI 1: Total Events ──
    charts.append(client.create_chart(
        name="Click: Total Events",
        viz_type="big_number_total",
        datasource_id=ds_id,
        params={
            "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Events"},
            "header_font_size": 0.4,
            "y_axis_format": "SMART_NUMBER",
        },
    ))

    # ── KPI 2: Unique Sessions ──
    charts.append(client.create_chart(
        name="Click: Unique Sessions",
        viz_type="big_number_total",
        datasource_id=ds_id,
        params={
            "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(DISTINCT session_id)", "label": "Sessions"},
            "header_font_size": 0.4,
            "y_axis_format": "SMART_NUMBER",
        },
    ))

    # ── Events per Minute (line) ──
    charts.append(client.create_chart(
        name="Click: Events/min",
        viz_type="echarts_timeseries_line",
        datasource_id=ds_id,
        params={
            "x_axis": "event_ts",
            "time_grain_sqla": "PT1M",
            "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "events/min"}],
            "row_limit": 1000,
            "show_legend": False,
            "x_axis_time_format": "%H:%M",
        },
    ))

    # ── Device Type (donut) ──
    charts.append(client.create_chart(
        name="Click: Device Types",
        viz_type="pie",
        datasource_id=ds_id,
        params={
            "groupby": ["device_type"],
            "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Events"},
            "donut": True,
            "show_labels": True,
            "label_type": "key_percent",
        },
    ))

    # ── Top Pages (horizontal bar) ──
    charts.append(client.create_chart(
        name="Click: Top Pages",
        viz_type="echarts_bar",
        datasource_id=ds_id,
        params={
            "x_axis": "page_url",
            "metrics": [{"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Hits"}],
            "groupby": ["page_url"],
            "row_limit": 10,
            "order_desc": True,
            "orientation": "horizontal",
            "show_legend": False,
        },
    ))

    layout = [
        {"chart_id": charts[0], "row": 0, "col": 0, "width": 6, "height": 8, "name": "Total Events"},
        {"chart_id": charts[1], "row": 0, "col": 6, "width": 6, "height": 8, "name": "Unique Sessions"},
        {"chart_id": charts[2], "row": 1, "col": 0, "width": 12, "height": 12, "name": "Events/min"},
        {"chart_id": charts[3], "row": 2, "col": 0, "width": 4, "height": 12, "name": "Device Types"},
        {"chart_id": charts[4], "row": 2, "col": 4, "width": 8, "height": 12, "name": "Top Pages"},
    ]

    return client.create_dashboard(
        title="Real-time Clickstream",
        slug="clickstream",
        chart_ids=charts,
        position_json=build_position_json(layout),
    )
```

### 3.7 — Dashboard 5: Customer 360 Overview

**Dataset**: `iceberg.default.customer_360` (NOTE: schema is `default`, not `demo`)
**Charts** (6 total — new dashboard, no Metabase equivalent):

```python
def create_customer360_dashboard(client: SupersetClient, db_id: int, ds_id: int) -> int:
    """Create the Customer 360 Overview dashboard with 6 charts."""

    charts = []

    # ── KPI 1: Total Customers ──
    charts.append(client.create_chart(
        name="C360: Total Customers",
        viz_type="big_number_total",
        datasource_id=ds_id,
        params={
            "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(DISTINCT customer_id)", "label": "Customers"},
            "header_font_size": 0.4,
            "y_axis_format": "SMART_NUMBER",
        },
    ))

    # ── KPI 2: Total Volume ──
    charts.append(client.create_chart(
        name="C360: Total Volume",
        viz_type="big_number_total",
        datasource_id=ds_id,
        params={
            "metric": {"expressionType": "SQL", "sqlExpression": "SUM(amount)", "label": "Volume"},
            "header_font_size": 0.4,
            "y_axis_format": "$,.0f",
        },
    ))

    # ── KPI 3: Avg Transaction ──
    charts.append(client.create_chart(
        name="C360: Avg Transaction",
        viz_type="big_number_total",
        datasource_id=ds_id,
        params={
            "metric": {"expressionType": "SQL", "sqlExpression": "ROUND(AVG(amount), 2)", "label": "Avg Txn"},
            "header_font_size": 0.4,
            "y_axis_format": "$,.2f",
        },
    ))

    # ── Spend by Segment (bar) ──
    charts.append(client.create_chart(
        name="C360: Spend by Segment",
        viz_type="echarts_bar",
        datasource_id=ds_id,
        params={
            "x_axis": "segment",
            "metrics": [{"expressionType": "SQL", "sqlExpression": "SUM(amount)", "label": "Total Spend"}],
            "groupby": ["segment"],
            "y_axis_format": "$,.0f",
            "show_legend": False,
        },
    ))

    # ── Country Distribution (pie, MENA-weighted) ──
    charts.append(client.create_chart(
        name="C360: Countries",
        viz_type="pie",
        datasource_id=ds_id,
        params={
            "groupby": ["country"],
            "metric": {"expressionType": "SQL", "sqlExpression": "COUNT(*)", "label": "Transactions"},
            "donut": True,
            "show_labels": True,
            "label_type": "key_percent",
        },
    ))

    # ── Top Merchants (horizontal bar) ──
    charts.append(client.create_chart(
        name="C360: Top Merchants",
        viz_type="echarts_bar",
        datasource_id=ds_id,
        params={
            "x_axis": "merchant",
            "metrics": [{"expressionType": "SQL", "sqlExpression": "SUM(amount)", "label": "Revenue"}],
            "groupby": ["merchant"],
            "row_limit": 10,
            "order_desc": True,
            "orientation": "horizontal",
            "y_axis_format": "$,.0f",
            "show_legend": False,
        },
    ))

    layout = [
        {"chart_id": charts[0], "row": 0, "col": 0, "width": 4, "height": 8, "name": "Total Customers"},
        {"chart_id": charts[1], "row": 0, "col": 4, "width": 4, "height": 8, "name": "Total Volume"},
        {"chart_id": charts[2], "row": 0, "col": 8, "width": 4, "height": 8, "name": "Avg Transaction"},
        {"chart_id": charts[3], "row": 1, "col": 0, "width": 6, "height": 12, "name": "Spend by Segment"},
        {"chart_id": charts[4], "row": 1, "col": 6, "width": 6, "height": 12, "name": "Countries"},
        {"chart_id": charts[5], "row": 2, "col": 0, "width": 12, "height": 12, "name": "Top Merchants"},
    ]

    return client.create_dashboard(
        title="Customer 360 Overview",
        slug="customer-360",
        chart_ids=charts,
        position_json=build_position_json(layout),
    )
```

### 3.8 — Main orchestrator

```python
def wait_for_superset(base_url: str, timeout: int = 120):
    """Poll Superset health endpoint until ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{base_url}/health", timeout=5)
            if resp.status_code == 200:
                logger.info("Superset is ready")
                return True
        except requests.ConnectionError:
            pass
        logger.info(f"Waiting for Superset at {base_url}...")
        time.sleep(5)
    raise TimeoutError(f"Superset not ready after {timeout}s")


def wait_for_data(client: SupersetClient, db_id: int, table: str, schema: str = "demo", timeout: int = 120):
    """Wait until a table has data (data generator has started writing)."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            result = client.post("sqllab/execute/", json={
                "database_id": db_id,
                "sql": f"SELECT COUNT(*) as cnt FROM iceberg.{schema}.{table}",
                "schema": schema,
            })
            if result and result.get("data", [{}])[0].get("cnt", 0) > 0:
                logger.info(f"Table {schema}.{table} has data")
                return True
        except Exception:
            pass
        time.sleep(5)
    logger.warning(f"Table {schema}.{table} has no data after {timeout}s — proceeding anyway")
    return False


def setup_superset():
    """Main entry point: provision all seed dashboards in Superset."""
    logger.info("=" * 60)
    logger.info("DemoForge Superset Setup")
    logger.info("=" * 60)

    # 1. Wait for Superset
    wait_for_superset(SUPERSET_URL)

    # 2. Authenticate
    client = SupersetClient(SUPERSET_URL, SUPERSET_USER, SUPERSET_PASS)
    logger.info("Authenticated with Superset")

    # 3. Create Trino database connection
    db_id = client.create_database("DemoForge Trino", TRINO_URI)

    # 4. Create datasets (all 5 tables)
    datasets = {
        "orders": client.create_dataset(db_id, "demo", "orders"),
        "sensor_readings": client.create_dataset(db_id, "demo", "sensor_readings"),
        "transactions": client.create_dataset(db_id, "demo", "transactions"),
        "clickstream": client.create_dataset(db_id, "demo", "clickstream"),
        "customer_360": client.create_dataset(db_id, "default", "customer_360"),
    }
    logger.info(f"Registered {len(datasets)} datasets")

    # 5. Wait for at least one table to have data
    wait_for_data(client, db_id, "orders", "demo", timeout=60)

    # 6. Create all 5 dashboards
    dashboards = {}
    dashboards["orders"] = create_orders_dashboard(client, db_id, datasets["orders"])
    dashboards["iot"] = create_iot_dashboard(client, db_id, datasets["sensor_readings"])
    dashboards["financial"] = create_financial_dashboard(client, db_id, datasets["transactions"])
    dashboards["clickstream"] = create_clickstream_dashboard(client, db_id, datasets["clickstream"])
    dashboards["customer_360"] = create_customer360_dashboard(client, db_id, datasets["customer_360"])

    logger.info("=" * 60)
    logger.info(f"Setup complete: {len(dashboards)} dashboards created")
    for name, dash_id in dashboards.items():
        logger.info(f"  {name}: {SUPERSET_URL}/superset/dashboard/{dash_id}/")
    logger.info("=" * 60)

    return dashboards


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    try:
        setup_superset()
    except Exception as e:
        logger.error(f"Superset setup failed: {e}", exc_info=True)
        sys.exit(1)
```

---

## PHASE 4: Integration with Data Generator

**Agent: Backend engineer**

### 4.1 — Modify data-generator entrypoint

The data-generator currently calls `metabase_setup.py` when Metabase is detected. Add Superset detection alongside it.

Find the entrypoint code (discovered in Phase 0.1) and add:

```python
# Detect which BI tool is running
def detect_bi_tool() -> str | None:
    """Check which BI tool is available."""
    superset_url = os.environ.get("SUPERSET_URL", "http://superset:8088")
    metabase_url = os.environ.get("METABASE_URL", "http://metabase:3000")

    try:
        resp = requests.get(f"{superset_url}/health", timeout=5)
        if resp.status_code == 200:
            return "superset"
    except Exception:
        pass

    try:
        resp = requests.get(f"{metabase_url}/api/health", timeout=5)
        if resp.status_code == 200:
            return "metabase"
    except Exception:
        pass

    return None


# In the main startup flow, after table_setup:
bi_tool = detect_bi_tool()
if bi_tool == "superset":
    from superset_setup import setup_superset
    setup_superset()
elif bi_tool == "metabase":
    from metabase_setup import setup_metabase
    setup_metabase()
else:
    logger.warning("No BI tool detected — skipping dashboard setup")
```

### 4.2 — Add requests to data-generator requirements

Ensure `requests` is in the data-generator's `requirements.txt` (it likely already is for Metabase setup).

---

## PHASE 5: Demo Template Integration

**Agent: Backend engineer**

### 5.1 — Update existing templates

For each demo template that currently includes Metabase, add Superset as an alternative. The exact mechanism depends on what Phase 0.4 revealed, but the pattern should be:

```yaml
# In demo template YAML (example — adjust to actual schema)
components:
  # ... existing components ...

  # BI layer — one of these will be active
  - name: metabase
    enabled: true  # default
    category: visualization

  - name: superset
    enabled: false  # alternative — FA can toggle
    category: visualization
```

### 5.2 — Create a Superset-specific demo template

Create one new demo template that uses Superset as the default BI tool instead of Metabase. This serves as a showcase template:

```yaml
name: lakehouse-superset
display_name: "Data Lakehouse with Superset"
description: "Modern data lakehouse with MinIO, Trino, Iceberg, and Apache Superset dashboards. Features 5 live-updating dashboards across e-commerce, IoT, financial, clickstream, and customer analytics datasets."
category: analytics
tags:
  - lakehouse
  - superset
  - trino
  - iceberg

components:
  - minio
  - hive-metastore
  - trino
  - data-generator
  - superset  # Superset instead of Metabase
```

---

## PHASE 6: Testing

**Agent: QA / Testing engineer**

### 6.1 — Unit test the setup script

Create `tests/test_superset_setup.py`:

```python
"""
Test superset_setup.py logic without requiring a running Superset instance.
Uses mocked HTTP responses.
"""
import pytest
from unittest.mock import patch, MagicMock

# Test: build_position_json generates valid Superset layout
# Test: SupersetClient handles 422 (already exists) gracefully
# Test: wait_for_superset times out correctly
# Test: detect_bi_tool prefers Superset when both are running
# Test: create_*_dashboard functions produce correct chart count
# Test: idempotency — running setup twice doesn't create duplicates
```

### 6.2 — Integration test (requires Docker)

```bash
# Start the full stack locally
make dev  # or equivalent

# Verify Superset is accessible
curl -s http://localhost:8088/health

# Verify dashboards were created
TOKEN=$(curl -s -X POST http://localhost:8088/api/v1/security/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin","provider":"db","refresh":true}' \
  | jq -r '.access_token')

# Should return 5 dashboards
curl -s http://localhost:8088/api/v1/dashboard/ \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.count'

# Verify each dashboard has charts
for slug in live-orders iot-sensors financial-txns clickstream customer-360; do
  echo "Dashboard: $slug"
  curl -s "http://localhost:8088/api/v1/dashboard/?q=$(python3 -c "import json; print(json.dumps({'filters':[{'col':'slug','opr':'eq','value':'$slug'}]}))")" \
    -H "Authorization: Bearer $TOKEN" \
    | jq '.result[0].dashboard_title'
done

# Verify charts query successfully (open each dashboard in browser)
echo "Open http://localhost:8088/superset/dashboard/live-orders/ in browser"
```

### 6.3 — Test checklist

```
[ ] Superset container starts in < 60s
[ ] Admin login works (admin/admin)
[ ] Trino database connection is created
[ ] All 5 datasets are registered
[ ] Dashboard 1 (Orders): 8 charts render with data
[ ] Dashboard 2 (IoT): 7 charts render with data
[ ] Dashboard 3 (Financial): 7 charts render with data
[ ] Dashboard 4 (Clickstream): 5 charts render with data
[ ] Dashboard 5 (Customer 360): 6 charts render with data
[ ] Auto-refresh works (charts update every 10s)
[ ] Running setup twice is idempotent (no duplicate charts/dashboards)
[ ] Metabase still works if Superset is not present
[ ] Component manifest loads without errors
[ ] Demo template with Superset deploys correctly
[ ] Image size is < 2GB (verify with docker images)
[ ] Container runs on both arm64 and amd64 (OrbStack on M-series Mac)
```

---

## PHASE 7: Post-Implementation Architect Review

**Agent: Architect (review all work)**

### 7.1 — Code review checklist

```
Review all created/modified files and verify:

1. CONSISTENCY
   - superset_setup.py follows the same patterns as metabase_setup.py
   - Component manifest follows the same schema as other manifests
   - File locations match DemoForge conventions
   - Naming conventions are consistent (demoforge-, snake_case, etc.)

2. CORRECTNESS
   - All 5 Trino table references match actual table_setup.py DDL
   - Column names in chart SQL match actual schema
   - Dataset schemas are correct (demo vs default for customer_360)
   - Superset chart viz_type values are valid Superset types
   - Position JSON uses correct Superset v2 grid format

3. ROBUSTNESS
   - Setup script handles Superset not being ready (polling)
   - Setup script handles Trino not having data yet (waiting)
   - Setup script is idempotent (checks before creating)
   - Error handling doesn't crash data-generator if Superset setup fails
   - Health check timing is sufficient for cold start

4. SECURITY
   - No sensitive credentials hardcoded (only demo defaults)
   - CSRF disabled only for local demo mode
   - No external network calls from Superset config

5. DEMO EXPERIENCE
   - Dashboards auto-refresh (10s interval)
   - Charts are visually balanced in the grid layout
   - KPIs are at the top of every dashboard
   - Time-series charts use appropriate granularity
   - Dashboard titles are clear and professional
   - Chart names won't confuse FAs

6. INTEGRATION
   - Data-generator correctly detects Superset vs Metabase
   - Demo templates correctly reference the Superset component
   - Superset component declares Trino as a dependency
   - No conflicts with Metabase when both manifests exist
```

### 7.2 — Architecture review

```
Verify the overall design is sound:

1. Single-container Superset with SQLite is appropriate for demo use
2. No unnecessary complexity (no Redis, no Celery, no Postgres)
3. Custom image is minimal (base + one pip install)
4. Setup script mirrors Metabase pattern for maintainability
5. Dashboard layout grid math is correct (all widths sum to 12)
6. Chart SQL queries will work on streaming data (no assumptions about data completeness)
7. The 5 dashboards cover all datasets and tell a coherent story
8. Customer 360 dashboard (new) is appropriate for MENA-focused data
```

### 7.3 — Sign-off

Present final summary:
- Files created/modified (with paths)
- Image size
- Startup time
- Dashboard URLs
- Any open issues or follow-ups

---

## File Summary

After all phases, the following files should exist:

```
components/superset/
├── Dockerfile
├── superset_config.py
└── superset-init.sh

components/data-generator/src/
├── metabase_setup.py          (existing, unchanged)
├── superset_setup.py          (NEW — 400-500 lines)
└── [entrypoint modified to detect BI tool]

manifests/ (or wherever manifests live)
└── superset.yaml              (NEW)

demo-templates/ (or wherever templates live)
└── lakehouse-superset.yaml    (NEW)

tests/
└── test_superset_setup.py     (NEW)
```

---

## Key Constants Reference

| Item | Value |
|------|-------|
| Superset image | `apache/superset:4.1.2` |
| Custom image | `demoforge/superset:latest` |
| Superset port | `8088` |
| Admin credentials | `admin` / `admin` |
| Trino URI | `trino://demoforge@trino:8080/iceberg` |
| Orders dataset | `iceberg.demo.orders` |
| Sensors dataset | `iceberg.demo.sensor_readings` |
| Transactions dataset | `iceberg.demo.transactions` |
| Clickstream dataset | `iceberg.demo.clickstream` |
| Customer 360 dataset | `iceberg.default.customer_360` |
| Dashboard refresh | `10 seconds` |
| Grid columns | `12` (Superset standard) |

---

## Agent Assignment Summary

| Phase | Agent | Mode | Description |
|-------|-------|------|-------------|
| 0 | Architect | Read-only | Investigate current state, confirm assumptions |
| 0.5 | Architect | Gate | Review findings, approve/correct before coding |
| 1 | Backend | Write | Dockerfile, config, init script |
| 2 | Backend | Write | Component manifest YAML |
| 3 | Backend | Write | superset_setup.py (largest phase) |
| 4 | Backend | Write | Data-generator integration |
| 5 | Backend | Write | Demo template integration |
| 6 | QA | Test | Unit + integration tests |
| 7 | Architect | Review | Final code + architecture review |
