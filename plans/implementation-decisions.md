# Implementation decisions (reference)

Concise record of structural choices made during refactors and related work, for future maintainers.

## Backend: `app.api.instances`

- **Split:** Replaced monolithic `api/instances.py` with a package:
  - **`helpers.py`** — Shared logic: audit JSONL, replication cache/check, `_build_replication_state_cmd`, `_expand_demo_for_edges`, `_get_first_cluster_alias`, external-system on-demand meta, `_METABASE_CHART_MAP`, Superset position/spec builders.
  - **Route modules** — `list_lifecycle`, `edges_cluster`, `generator_external`, `exec_logs`, `minio_scenario`, `trino_tables`, `metabase_setup`, `superset_setup` each expose an `APIRouter`; **`core.py`** only merges them with `include_router`.
  - **`pool_decommission.py`** — Pool decommission + `apply-topology` kept separate from the large “core” surface area.
- **Imports:** Submodules under `api/instances/` use three-dot relative imports to `app.*` (`...state`, `...engine`, etc.); sibling `api` modules use `..demos`.
- **Public API:** `app.api.instances` still exports `router` and `_parse_mc_decommission_status` via `__init__.py` so tests and `main.py` stay stable.

## Backend: `app.engine.compose_generator`

- **Split:** Replaced single `compose_generator.py` with a package:
  - **`helpers.py`** — Path validation (`_validate_host_paths` on import), env/template helpers, event-processor / MinIO notify helpers.
  - **`generate.py`** — `generate_compose` implementation.
  - **`__init__.py`** — Re-exports `generate_compose` so `from app.engine.compose_generator import generate_compose` is unchanged.
- **Imports:** Submodules use `...models`, `...registry`, `...config`, `...network_manager` (one extra level vs old flat module).

## Frontend: properties UI

- **`PropertiesPanel.tsx`** — Orchestration only (selection, stores, debounced cluster topology apply, event-processor routing memo).
- **Extracted panels:** Edge, group, annotation, cluster (via `ClusterPropertiesRouter` → existing cluster sub-panels), sticky, canvas image, component node (`ComponentNodePropertiesPanel` + `DataGeneratorPanel`, RAG, Ollama, etc.).
- **`clusterConfigSchemas.ts`** — Cluster-level connection schemas not driven by component manifests.

## Tooling / repo hygiene

- **`.gitignore`** — `.venv/` / `venv/` for local Python environments.
- **Tests:** `backend/tests/test_refactor_wiring.py` asserts router wiring (instances + compose helpers); decommission parse tests import from `app.api.instances`.

## Intentionally not centralized here

- Parked product phases (Metabase BI layer, cloud tiers, Delta Sharing, etc.) remain described in **`plans/backlog-backup-2026-04-09.md`** and historical notes; they are roadmap, not ADRs for completed refactors.

---

*Last updated when backlog was cleared (see `plans/backlog.md`).*
