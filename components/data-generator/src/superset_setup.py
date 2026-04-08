"""
superset_setup.py — Provision seed dashboards in Apache Superset via REST API.

Mirrors the functionality of metabase_setup.py but targets Superset.
Creates 5 dashboards with ~33 charts total across all datasets.

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
        chart_ids: list,
        position_json: dict,
        css: str = "",
        json_metadata: Optional[dict] = None,
    ) -> int:
        """Create a dashboard with positioned charts. Returns dashboard ID."""
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


def build_position_json(chart_layout: list) -> dict:
    """
    Build Superset dashboard position JSON from a simplified layout spec.

    chart_layout: list of dicts with keys:
        - chart_id: int
        - row: int (0-indexed row in grid)
        - col: int (0-11 column position)
        - width: int (1-12 columns)
        - height: int (grid units, typically 8-16)
        - name: str (optional)

    Returns the full position_json dict for the dashboard API.
    """
    position = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {
            "type": "GRID",
            "id": "GRID_ID",
            "children": [],
            "parents": ["ROOT_ID"],
        },
        "HEADER_ID": {
            "type": "HEADER",
            "id": "HEADER_ID",
            "meta": {"text": ""},
        },
    }

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


# ── Dashboard 1: Live Orders Analytics ──────────────────────────────────────

def create_orders_dashboard(client: SupersetClient, db_id: int, ds_id: int) -> int:
    """Create the Live Orders Analytics dashboard with 8 charts."""

    charts = []

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


# ── Dashboard 2: IoT Sensor Monitoring ───────────────────────────────────────

def create_iot_dashboard(client: SupersetClient, db_id: int, ds_id: int) -> int:
    """Create the IoT Sensor Monitoring dashboard with 7 charts."""

    charts = []

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


# ── Dashboard 3: Financial Transactions Monitor ───────────────────────────────

def create_financial_dashboard(client: SupersetClient, db_id: int, ds_id: int) -> int:
    """Create the Financial Transactions Monitor dashboard with 7 charts."""

    charts = []

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


# ── Dashboard 4: Real-time Clickstream ───────────────────────────────────────

def create_clickstream_dashboard(client: SupersetClient, db_id: int, ds_id: int) -> int:
    """Create the Real-time Clickstream dashboard with 5 charts."""

    charts = []

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


# ── Dashboard 5: Customer 360 Overview ───────────────────────────────────────

def create_customer360_dashboard(client: SupersetClient, db_id: int, ds_id: int) -> int:
    """Create the Customer 360 Overview dashboard with 6 charts."""

    charts = []

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


# ── Orchestrator ─────────────────────────────────────────────────────────────

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
