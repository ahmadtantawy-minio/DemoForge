# External System Scenario Schema

This document describes the YAML schema for scenarios consumed by the `external-system` engine.

```yaml
scenario:
  id: string              # kebab-case unique id, e.g. "soc-firewall-events"
  name: string            # human-readable
  description: string
  category: string        # e.g. "cybersecurity"

display:
  default_name: string        # default node label rendered on the canvas
  default_subtitle: string    # optional secondary label

datasets:                 # list, processed SEQUENTIALLY in order
  - id: string
    target: "table" | "object"

    # --- when target == "table" ---
    namespace: string         # Iceberg namespace (schema), e.g. "soc"
    table_name: string
    format: "parquet"
    partition_by: [col, ...]  # optional partition columns

    # --- when target == "object" ---
    bucket: string            # MinIO bucket name (auto-created)
    prefix: string            # object key prefix
    object_format: "json" | "binary" | "text"
    object_size_min: int      # binary: min bytes per object
    object_size_max: int      # binary: max bytes per object

    # Optional: extract fields from generated objects into an Iceberg table
    mirror_to_table:
      namespace: string
      table_name: string
      fields: [name, ...]     # which schema field names to mirror

    schema:
      - name: string
        type: string          # string | integer | long | float | double | boolean | timestamp | date
        nullable: bool        # default true
        generator: string     # see generator library
        params: {}            # generator-specific params

    generation:
      mode: "batch" | "stream" | "batch_then_stream"
      seed_rows: int          # for tables in batch mode
      seed_count: int         # for objects
      stream_rate: "25/s"     # rows/sec for stream modes
      stream_duration: "forever" | "30m"

      # Optional: offline on-demand bursts (polls ES_ON_DEMAND_DIR, default /tmp/es-on-demand)
      on_demand:
        enabled: bool           # when true, engine watches for *.json request files after initial batch
        inherit_from: string    # optional dataset id — on-demand writes use that dataset’s batch S3 target (table: raw_landing bucket/prefix; object: bucket/prefix) so paths stay consistent
        default_count: int      # objects per trigger, or CSV files for landing_only tables
        max_count: int          # cap per request (objects or csv files)
        rows_per_csv_file: int  # landing_only: rows per CSV (defaults to raw_landing.batch_size)
        max_csv_files: int      # landing_only: cap files per request

reference_data:
  - id: string                # referenced by ref_lookup generator
    description: string
    format: "inline"
    columns: [col, ...]
    rows: [[v, v, ...], ...]

correlations:
  - name: string
    source_dataset: string
    source_field: string
    target_dataset: string
    target_field: string
    ratio: float              # fraction of target rows that pull from source

dashboards:
  - id: string
    title: string
    layout: "auto" | "2-column" | "3-column"
    charts:
      - id: string
        title: string
        type: "time_series" | "bar" | "number" | "table" | "pie"
        query: |              # Trino SQL
          SELECT ...
        position: {row, col, width, height}
        settings:
          x_axis: string
          y_axis: string | [string]
          group_by: string

saved_queries:
  collection: string          # Metabase collection name
  queries:
    - id: string
      title: string
      description: string
      order: int              # display order
      visualization: "table" | "bar" | "number" | "line"
      query: |                # Trino SQL
        SELECT ...
```

## Generator library

| Generator          | Params                                                                                    |
|--------------------|-------------------------------------------------------------------------------------------|
| `uuid`             | —                                                                                         |
| `auto_increment`   | `start`, `step`                                                                           |
| `timestamp`        | `pattern: realistic\|uniform\|business_hours`, `start`, `end`, `timezone`                  |
| `time_series`      | alias for `timestamp`                                                                     |
| `date`             | `start`, `end`, `from_field`                                                              |
| `ip_address`       | `ranges: [CIDR,...]`, `known_bad_ratio`                                                   |
| `weighted_choice`  | `choices: {value: weight}`                                                                |
| `uniform_choice`   | `values: [...]`                                                                           |
| `distribution`     | `type: normal\|lognormal\|uniform\|exponential`, `mean`, `sigma`, `min`, `max`, `precision` |
| `faker`            | `method`, `locale`                                                                         |
| `ref_lookup`       | `ref`, `column`, `distribution`, `match_field`, `match_value_from`                         |
| `ioc`              | `ioc_type: ipv4\|domain\|sha256\|md5\|url` or `type_field`                                |
| `pattern`          | `format: "{category}-{seq:04d}"`, `categories`, `seq_start`                               |
| `conditional`      | `field`, `conditions: [{when, generator, params}]`, `default`                             |
| `nullable`         | `generator`, `params`, `null_ratio`                                                        |
| `constant`         | `value`                                                                                    |
| `sequence_from`    | `values`                                                                                    |
| `json_object`      | `fields: [{name, generator, params}]`                                                      |
| `text_block`       | `min_words`, `max_words`                                                                   |
| `geo_coordinate`   | `region: us\|eu\|apac\|global`                                                             |
| `mac_address`      | `prefix`                                                                                   |

## Env vars

| Variable               | Purpose                                             |
|------------------------|-----------------------------------------------------|
| `ES_SCENARIO`          | scenario ID to run                                   |
| `ES_STARTUP_DELAY`     | seconds to wait before generating                    |
| `S3_ENDPOINT`          | MinIO endpoint                                       |
| `S3_ACCESS_KEY`        | MinIO access key                                     |
| `S3_SECRET_KEY`        | MinIO secret key                                     |
| `ICEBERG_CATALOG_URI`  | Iceberg REST catalog URL                             |
| `ICEBERG_SIGV4`        | `true` for AIStor Tables SigV4                       |
| `TRINO_HOST`           | Trino host:port for fallback writes + correlation    |
| `METABASE_URL`         | Metabase URL (default `http://metabase:3000`)        |
| `METABASE_USER`        | default `admin@demoforge.local`                      |
| `METABASE_PASSWORD`    | default `DemoForge123!`                              |
| `ES_ON_DEMAND_DIR`     | directory polled for `*.json` on-demand triggers (default `/tmp/es-on-demand`) |
| `ES_ON_DEMAND_POLL_SEC`| poll interval seconds (default `5`)                |

## On-demand generation (batch scenarios)

After the initial batch/stream phase, datasets with `generation.on_demand.enabled: true` keep the container in a **poll loop** on `ES_ON_DEMAND_DIR`. Drop a `*.json` file; it is consumed and moved to `processed/`.

**Request body** (any of):

- `{}` — run `default_count` for **every** on-demand dataset.
- `{"count": N}` — when exactly one dataset has `on_demand`, generate `N` objects (or `N` CSV files for `landing_only`).
- `{"malware_scan_sim": 2}` — per-dataset counts by id.
- `{"generate": [{"dataset": "malware_scan_sim", "count": 2}]}` — explicit list.
