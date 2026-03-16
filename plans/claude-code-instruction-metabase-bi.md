# Claude Code Instruction: Add Metabase BI Layer + AIStor Tables Demo Paths

## Context

DemoForge is an existing, working demo environment generator for MinIO. It uses a visual diagram editor (React Flow) to compose topologies, generates Docker Compose files, deploys sandboxed containers (no host port exposure), and provides a Control Plane with a reverse proxy gateway for accessing component web UIs and terminals.

The component registry lives in `components/`, each with a `manifest.yaml`. Demo templates live in `demos/`. The compose generator reads manifests and produces `docker-compose.yml` files. The proxy gateway routes `/proxy/{demo}/{node}/{ui_name}/*` to internal container ports.

**Your job:** Add Metabase as a BI visualization component and create three demo templates that showcase different ways to connect Metabase to MinIO data — from basic S3 queries to the new AIStor Tables (native Iceberg). This includes the Metabase component itself, Trino catalog configuration templates, structured-data traffic generator profiles, a pre-seeded dashboard, and init scripts.

Read the existing codebase first to understand the project conventions (manifest schema, template format, init script patterns, compose generation logic, traffic generator profiles) before making changes. Match the existing patterns exactly.

---

## Reference Document

The full specification for this work is in **Addendum A** of `minio-demo-generator-plan.md` (sections A.1 through A.9). That document is the authoritative source. What follows is the task list derived from it.

---

## Tasks

### 1. Add Metabase component manifest

Create `components/metabase/manifest.yaml`:

- **Image:** `metabase/metabase:latest`
- **Category:** `analytics`
- **Resources:** 512m memory, 0.5 cpu
- **Single port:** 3000 (web)
- **Environment:** `MB_DB_TYPE=h2`, `MB_JETTY_PORT=3000`, `JAVA_TIMEZONE=UTC`, `JAVA_OPTS="-Xmx384m -Xms256m"`
- **Health check:** `GET /api/health` on port 3000, interval 15s, timeout 10s
- **Secrets:** `MB_ADMIN_EMAIL` (default: `admin@demoforge.local`), `MB_ADMIN_PASSWORD` (default: `DemoForge123!`) — both optional
- **Web UI:** name `dashboard`, port 3000, path `/`
- **Terminal:** shell `/bin/sh`, quick actions for `curl -s localhost:3000/api/health` and `curl -s localhost:3000/api/database`
- **Connections accepts:** `jdbc`, `trino`
- **Variants:** `standard` (embedded H2, no external deps), `with-postgres` (external PostgreSQL for metadata)

Follow the exact manifest schema used by the existing components (look at `components/minio/manifest.yaml` as the reference).

### 2. Add Trino catalog configuration templates

Create config templates that the compose generator can inject into the Trino container depending on which demo path is being used. These go in `components/trino/templates/` (or wherever existing Trino config templates live — check the codebase):

**a) `catalog-iceberg-hive.properties.j2`** — for Path 1 (Lakehouse Classic):
```properties
connector.name=iceberg
iceberg.catalog.type=hive_metastore
hive.metastore.uri=thrift://{{ hive_metastore_host }}:9083
hive.s3.endpoint=http://{{ minio_host }}:9000
hive.s3.aws-access-key={{ minio_access_key }}
hive.s3.aws-secret-key={{ minio_secret_key }}
hive.s3.path-style-access=true
```

**b) `catalog-iceberg-rest.properties.j2`** — for Path 2 (AIStor Tables):
```properties
connector.name=iceberg
iceberg.catalog.type=rest
iceberg.rest-catalog.uri=http://{{ minio_host }}:9000/_iceberg
iceberg.rest-catalog.warehouse={{ warehouse_name | default('analytics') }}
iceberg.rest-catalog.security=OAUTH2
iceberg.rest-catalog.vended-credentials-enabled=true
```

**c) `catalog-hive-s3.properties.j2`** — for Path 3 (Direct S3 Query):
```properties
connector.name=hive
hive.metastore.uri=thrift://{{ hive_metastore_host }}:9083
hive.s3.endpoint=http://{{ minio_host }}:9000
hive.s3.aws-access-key={{ minio_access_key }}
hive.s3.aws-secret-key={{ minio_secret_key }}
hive.s3.path-style-access=true
```

Make sure the compose generator or init runner knows how to mount/inject these into the Trino container at the right path (typically `/etc/trino/catalog/`). Check how existing Trino catalog configs are handled and follow that pattern.

### 3. Add Metabase init script and pre-seeded dashboard

Create `components/metabase/init/setup-metabase.sh`:

This script runs after Metabase passes its health check. It does:
1. Wait for Metabase to be fully ready (poll `/api/health`)
2. Complete Metabase first-run setup via API (create admin user with the configured email/password, skip the welcome wizard)
3. Add a Trino database connection (parameterized — the Trino hostname, catalog name, and schema should come from the demo's edge/connection config, not be hardcoded)
4. Import the pre-built dashboard

Create `components/metabase/dashboards/live-orders.json`:

This is a Metabase collection export containing a dashboard called **"Live Orders Analytics"** with these cards:
- Orders per minute (line chart)
- Revenue by region (bar chart, grouped by `region` column)
- Top products (horizontal bar, ranked by `quantity`)
- Order volume trend (area chart, daily aggregation on `order_date`)
- Three KPI cards: Total orders, Total revenue, Avg order value

The dashboard queries should reference a table called `orders` in the connected Trino catalog with columns: `order_id`, `customer_id`, `product_name`, `quantity`, `unit_price`, `order_date`, `region`.

**Important:** Metabase's export format is specific. The cleanest approach is to:
1. Stand up a temporary Metabase + Trino + MinIO stack manually
2. Create the dashboard in Metabase's UI
3. Export it via `GET /api/collection/root/export` 
4. Save the resulting JSON as the seed file

If that's not practical, create the dashboard programmatically in the init script using the Metabase API (`POST /api/card` for each question, `POST /api/dashboard` for the dashboard, `POST /api/dashboard/{id}/cards` to add cards). The init script approach is more portable and doesn't depend on Metabase's export format staying stable.

### 4. Add structured-data traffic generator profiles

Add these workload profiles to the traffic generator (check where existing profiles are defined — likely in the traffic generator component directory or a profiles config):

**a) `parquet-structured`** — writes Parquet files to MinIO via S3 API:
- Schema: `order_id` (int64), `customer_id` (int64), `product_name` (string, random from a list of ~20 products), `quantity` (int32, 1-100), `unit_price` (float64, 5.00-500.00), `order_date` (timestamp, current time), `region` (string, one of US-East/US-West/EU/APAC)
- Bucket: `raw-data`
- Partition by `order_date` into daily folders: `raw-data/year=YYYY/month=MM/day=DD/`
- Batch size: 1000 rows per file
- Interval: new file every 5 seconds
- Uses `pyarrow` for Parquet generation and `boto3` for S3 upload

**b) `iceberg-native`** — writes directly to AIStor Tables via the Iceberg REST API:
- Same schema as above
- Uses `pyiceberg` library to connect to `http://{minio_host}:9000/_iceberg`
- Warehouse: `analytics`, namespace: `demo`, table: `orders`
- Creates the table if it doesn't exist (with the schema above)
- Batch size: 500 rows, interval: 3 seconds
- This profile only works with Path 2 (AIStor Tables)

**c) `csv-flat`** — writes CSV files for simple demos:
- Same schema
- Bucket: `csv-data`
- No partitioning, flat files
- Batch size: 500 rows, interval: 10 seconds

### 5. Add three demo templates

Add these to the `demos/` directory (or wherever pre-built templates are stored):

**a) `demos/lakehouse-classic.yaml`** — Path 1: Lakehouse Classic
- Components: minio (single), spark (single), hive-metastore, postgresql, trino, metabase, traffic-generator
- Traffic generator config: `workload_profile: parquet-structured`
- Trino config: use `catalog-iceberg-hive.properties` template
- Metabase connects to Trino, catalog `iceberg`
- 7 nodes, 7 edges showing the full data flow
- Layout positions should arrange nodes in a left-to-right flow: TrafficGen → MinIO → Spark → Hive/PG (below) → Trino → Metabase

**b) `demos/aistor-tables.yaml`** — Path 2: AIStor Tables
- Components: minio (single, with `MINIO_ENABLE_TABLES: "on"`), trino, metabase, traffic-generator
- Traffic generator config: `workload_profile: iceberg-native`
- Trino config: use `catalog-iceberg-rest.properties` template pointing to MinIO's `/_iceberg` endpoint
- Metabase connects to Trino, catalog `aistor-tables`
- 4 nodes, 3 edges — the simplest topology
- Add a `notes` field: "Requires AIStor enterprise license and RELEASE.2026-02-02 or later"
- Add a `license_required: true` flag (or whatever mechanism the existing template schema uses to flag license requirements)

**c) `demos/s3-direct-query.yaml`** — Path 3: Direct S3 Query  
- Components: minio (single), hive-metastore, postgresql, trino, metabase, traffic-generator
- Traffic generator config: `workload_profile: parquet-structured`
- Trino config: use `catalog-hive-s3.properties` template
- Metabase connects to Trino, catalog `minio-s3`
- 6 nodes, 5 edges

### 6. Update the compose generator for Metabase + Trino integration

Check how the compose generator currently handles inter-component configuration. The key integration points:

**a) Metabase → Trino connection:** When a Metabase node has an edge to a Trino node, the compose generator (or init runner) needs to know the Trino hostname and catalog name to configure Metabase's database connection in the init script. This should be derived from the edge metadata and the Trino node's config.

**b) Trino catalog injection:** When a Trino node is deployed, the compose generator needs to mount the correct catalog `.properties` file based on the node's `config.CATALOG_TYPE` value:
- `iceberg-hive` → render `catalog-iceberg-hive.properties.j2` and mount to `/etc/trino/catalog/iceberg.properties`
- `iceberg-rest` → render `catalog-iceberg-rest.properties.j2` and mount to `/etc/trino/catalog/aistor.properties`
- `hive-s3` → render `catalog-hive-s3.properties.j2` and mount to `/etc/trino/catalog/minio.properties`

Template variables should be resolved from the connected MinIO and Hive Metastore nodes in the demo definition.

**c) Metabase init timing:** The Metabase init script should only run after BOTH Metabase and Trino are healthy. Check how the existing init runner handles multi-dependency ordering and add Metabase's setup to that system.

### 7. License gating for AIStor Tables template

When the `aistor-tables` demo template is selected:
- Check the secret vault for `MINIO_LICENSE_KEY`
- If not present, show a warning in the UI: "AIStor Tables requires an enterprise license. The /_iceberg endpoint will not be available without one."
- Still allow deployment (the user might be entering the license key through MinIO's console or environment), but surface the warning prominently
- If the MinIO container starts but the `/_iceberg` health check fails, surface "AIStor Tables endpoint unavailable — check license" in the Control Plane rather than a generic error

---

## What NOT to do

- Don't modify the core DemoForge engine (proxy gateway, terminal bridge, diagram editor, component registry loader) — those work. Just add new components and templates that plug into the existing system.
- Don't add the side-by-side comparison mode yet — that's a future UI feature.
- Don't build a custom Metabase Docker image — use the stock `metabase/metabase:latest` image and configure everything via API calls in the init script.
- Don't hardcode Trino connection details in Metabase's init script — derive them from the demo's node/edge configuration.

---

## Verification

After implementation, these scenarios should work end-to-end:

1. **Template gallery:** All three new templates (lakehouse-classic, aistor-tables, s3-direct-query) appear in the demo template list with correct descriptions and node counts.

2. **Path 3 deploy:** Select "Direct S3 Query" → Deploy → Traffic generator writes Parquet to MinIO → Trino queries the files → Metabase dashboard shows live-updating charts via the DemoForge proxy.

3. **Path 1 deploy:** Select "Lakehouse Classic" → Deploy → Traffic generator writes to MinIO → Spark ETL creates Iceberg tables → Trino queries Iceberg → Metabase shows the same dashboard structure.

4. **Path 2 deploy (with license):** Select "AIStor Tables" → Deploy → Traffic generator writes via PyIceberg to AIStor's /_iceberg → Trino reads from AIStor REST Catalog → Metabase shows dashboards. Only 4 containers running.

5. **Path 2 without license:** Select "AIStor Tables" → Deploy → Warning shown → MinIO starts but /_iceberg returns 403 → Control Plane shows clear error message about missing license.

6. **Metabase proxy access:** Click Metabase's "dashboard" link in Control Plane → opens proxied Metabase UI at `/proxy/{demo}/metabase-1/dashboard/` → login works → dashboards are pre-loaded.

7. **Metabase auto-refresh:** Set a Metabase dashboard to 1-minute auto-refresh → new data appears in charts as traffic generator runs.
