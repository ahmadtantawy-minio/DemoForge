"""
metabase_setup.py — Auto-create Metabase dashboards from scenario query packs.

Flow:
1. Authenticate with Metabase REST API.
2. Find the Trino database ID.
3. Create a native-query card for each scenario query.
4. Create the dashboard.
5. Add all cards to the dashboard in one PUT with layout positions.
"""

import requests


# Chart type → Metabase display type + extra settings
_CHART_TYPE_MAP = {
    "bar": ("bar", {}),
    "line": ("line", {}),
    "pie": ("pie", {}),
    "donut": ("pie", {"pie.show_legend": True, "pie.percent_visibility": "inside"}),
    "horizontal_bar": ("bar", {"graph.x_axis.axis_enabled": True, "bar.horizontal": True}),
    "scalar": ("scalar", {}),
    "stacked_area": ("area", {"stackable.stack_type": "stacked"}),
    "pivot_table": ("pivot", {}),
    "table": ("table", {}),
}


class MetabaseSetup:
    def __init__(self, metabase_url: str, admin_email: str, admin_password: str):
        self.base_url = metabase_url.rstrip("/")
        self.email = admin_email
        self.password = admin_password
        self._session_token = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        if self._session_token:
            return self._session_token
        resp = requests.post(
            f"{self.base_url}/api/session",
            json={"username": self.email, "password": self.password},
            timeout=15,
        )
        resp.raise_for_status()
        self._session_token = resp.json()["id"]
        return self._session_token

    def _headers(self) -> dict:
        return {"X-Metabase-Session": self._get_token(), "Content-Type": "application/json"}

    def _get(self, path: str) -> dict:
        resp = requests.get(f"{self.base_url}{path}", headers=self._headers(), timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        resp = requests.post(
            f"{self.base_url}{path}", json=body, headers=self._headers(), timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    def _put(self, path: str, body: dict) -> dict:
        resp = requests.put(
            f"{self.base_url}{path}", json=body, headers=self._headers(), timeout=30
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Database lookup
    # ------------------------------------------------------------------

    def find_database_id(self, db_name_hint: str = "Trino") -> int:
        """Return the numeric ID of the first database whose name contains db_name_hint."""
        data = self._get("/api/database")
        databases = data.get("data", data) if isinstance(data, dict) else data
        for db in databases:
            if db_name_hint.lower() in db.get("name", "").lower():
                return db["id"]
        raise RuntimeError(
            f"No Metabase database found matching '{db_name_hint}'. "
            f"Available: {[d.get('name') for d in databases]}"
        )

    # ------------------------------------------------------------------
    # Card creation
    # ------------------------------------------------------------------

    def _chart_settings(self, chart_type: str) -> tuple:
        return _CHART_TYPE_MAP.get(chart_type, ("table", {}))

    def create_card(
        self, query_def: dict, database_id: int, collection_id: int = None
    ) -> int:
        """Create a native-query card. Returns the card ID."""
        display_type, viz_settings = self._chart_settings(query_def.get("chart_type", "table"))
        chart_config = query_def.get("chart_config", {})
        if chart_config:
            viz_settings = dict(viz_settings)
            if "x" in chart_config:
                viz_settings["graph.x_axis.column"] = chart_config["x"]
            if "y" in chart_config:
                viz_settings["graph.y_axis.column"] = chart_config["y"]
            if "series" in chart_config and chart_config["series"]:
                viz_settings["graph.series_column"] = chart_config["series"]
            if "dimension" in chart_config:
                viz_settings["pie.dimension"] = chart_config["dimension"]
            if "metric" in chart_config:
                viz_settings["pie.metric"] = chart_config["metric"]

        body = {
            "name": query_def.get("name", query_def.get("id", "Untitled")),
            "display": display_type,
            "visualization_settings": viz_settings,
            "dataset_query": {
                "type": "native",
                "native": {"query": query_def.get("sql", "").strip()},
                "database": database_id,
            },
        }
        if collection_id is not None:
            body["collection_id"] = collection_id

        result = self._post("/api/card", body)
        return result["id"]

    # ------------------------------------------------------------------
    # Dashboard creation
    # ------------------------------------------------------------------

    def create_dashboard(self, name: str, description: str = "") -> int:
        """Create an empty dashboard. Returns the dashboard ID."""
        result = self._post(
            "/api/dashboard",
            {"name": name, "description": description},
        )
        return result["id"]

    def add_cards_to_dashboard(
        self,
        dashboard_id: int,
        card_ids: dict,
        layout: list,
    ) -> None:
        """
        Add all cards to the dashboard in a single PUT call.

        card_ids: {query_id -> card_id}
        layout: list of {query, row, col, width, height} from scenario YAML
        """
        dashcards = []
        for item in layout:
            query_id = item.get("query")
            card_id = card_ids.get(query_id)
            if card_id is None:
                print(f"[metabase_setup] Warning: no card for query '{query_id}' — skipping.")
                continue
            dashcards.append(
                {
                    "id": -(len(dashcards) + 1),  # negative temp IDs for new cards
                    "card_id": card_id,
                    "row": item.get("row", 0),
                    "col": item.get("col", 0),
                    "size_x": item.get("width", 4),
                    "size_y": item.get("height", 4),
                    "parameter_mappings": [],
                    "visualization_settings": {},
                }
            )

        self._put(f"/api/dashboard/{dashboard_id}", {"dashcards": dashcards})

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def setup_dashboard(
        self,
        scenario: dict,
        catalog: str,
        namespace: str,
        db_name_hint: str = "Trino",
        collection_id: int = None,
    ) -> dict:
        """
        Full setup: create cards + dashboard for the scenario.

        Returns: {dashboard_id, dashboard_url, cards_created}
        """
        dashboard_cfg = scenario.get("metabase_dashboard", {})
        if not dashboard_cfg:
            raise ValueError(
                f"Scenario '{scenario.get('id')}' has no metabase_dashboard config."
            )

        print(f"[metabase_setup] Finding Trino database in Metabase...")
        database_id = self.find_database_id(db_name_hint)
        print(f"[metabase_setup] Using database ID: {database_id}")

        # Resolve query placeholders
        from src.schema_loader import get_queries_resolved
        queries = get_queries_resolved(scenario, catalog, namespace)

        # Create cards
        card_ids = {}
        for q in queries:
            print(f"[metabase_setup] Creating card: {q.get('name')}")
            card_id = self.create_card(q, database_id, collection_id)
            card_ids[q["id"]] = card_id

        # Create dashboard
        dash_name = dashboard_cfg.get("name", f"{scenario.get('name')} Dashboard")
        dash_desc = dashboard_cfg.get("description", "")
        print(f"[metabase_setup] Creating dashboard: {dash_name}")
        dashboard_id = self.create_dashboard(dash_name, dash_desc)

        # Add cards with layout
        layout = dashboard_cfg.get("layout", [])
        self.add_cards_to_dashboard(dashboard_id, card_ids, layout)

        dashboard_url = f"{self.base_url}/dashboard/{dashboard_id}"
        print(f"[metabase_setup] Dashboard created: {dashboard_url}")

        return {
            "dashboard_id": dashboard_id,
            "dashboard_url": dashboard_url,
            "cards_created": len(card_ids),
        }


def run_setup(
    scenario: dict,
    metabase_url: str,
    metabase_email: str,
    metabase_password: str,
    trino_catalog: str = "native",
    trino_namespace: str = "demo",
    db_name_hint: str = "Trino",
    collection_id: int = None,
) -> dict:
    """Convenience wrapper. Returns the setup result dict."""
    setup = MetabaseSetup(metabase_url, metabase_email, metabase_password)
    return setup.setup_dashboard(
        scenario=scenario,
        catalog=trino_catalog,
        namespace=trino_namespace,
        db_name_hint=db_name_hint,
        collection_id=collection_id,
    )
