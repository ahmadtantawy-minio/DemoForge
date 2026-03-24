# Claude Code Instruction: Dataset Catalog & Structured Data Generation

## Context

DemoForge is running. The current demo topology (see reference screenshot) has:

- **data-generator** (192.168.147.11) → "AIStor Tables Cluster" (192.168.147.17, 2 nodes, Tables enabled)
- **Data Generator** (192.168.147.5) → "AIStor Iceberg Cluster" (192.168.147.6, 2 nodes)
- **AIStor Iceberg Cluster** → **iceberg-rest** (192.168.147.9) → **Trino**
- **AIStor Tables Cluster** → **Trino** (direct via /_iceberg AIStor Tables)
- **Trino** → **Metabase** (for BI dashboards)
- **Prometheus** collecting metrics from both clusters

The `data-generator` component already exists and works. It currently pushes generic data. Your job is to upgrade it into a **scenario-driven structured data generator** with a dataset catalog, format-aware writers, pre-built queries, and auto-configured Metabase dashboards.

Read the existing `data-generator` codebase first. Understand its current config format, how it connects to MinIO (S3 endpoint, credentials), and how the DemoForge properties panel renders its settings. Then extend — don't replace.

---

## Deliverables

1. Three dataset scenario definition files (YAML)
2. Updated data-generator code: schema loader, value generators, format writers
3. Table setup automation (bucket creation, Iceberg DDL, Hive registration)
4. Metabase dashboard auto-creation from scenario query packs
5. UI changes to the data-generator properties panel
6. Test scenarios for the dual-cluster demo

---

## Task 1: Create dataset scenario files

Create these three files in the data-generator's configuration directory. Check where the existing data-generator stores its config (likely `components/data-generator/` or a mounted config volume) and put them in a `datasets/` subdirectory.

### File: `datasets/ecommerce-orders.yaml`

```yaml
id: ecommerce-orders
name: "E-commerce orders"
description: "Retail order stream — products, customers, regions. Good for bar charts, KPIs, time-series."

schema:
  columns:
    - name: order_id
      type: string
      generator: uuid

    - name: order_ts
      type: timestamp
      generator: now_jitter    # Current time ± 0-2 seconds jitter for realism

    - name: customer_id
      type: int64
      generator: {type: range, min: 1000, max: 9999}

    - name: customer_name
      type: string
      generator: {type: fake, method: name}

    - name: product_name
      type: string
      generator:
        type: weighted_enum
        values:
          "Wireless Headphones": 0.15
          "USB-C Hub": 0.12
          "Mechanical Keyboard": 0.10
          "4K Monitor": 0.08
          "Laptop Stand": 0.10
          "Webcam HD": 0.09
          "Portable SSD 2TB": 0.08
          "Smart Mouse": 0.07
          "Desk Lamp": 0.06
          "Cable Kit": 0.15

    - name: category
      type: string
      generator:
        type: derived_from
        source_column: product_name
        mapping:
          "Wireless Headphones": "Audio"
          "USB-C Hub": "Accessories"
          "Mechanical Keyboard": "Input Devices"
          "4K Monitor": "Displays"
          "Laptop Stand": "Accessories"
          "Webcam HD": "Video"
          "Portable SSD 2TB": "Storage"
          "Smart Mouse": "Input Devices"
          "Desk Lamp": "Office"
          "Cable Kit": "Accessories"

    - name: quantity
      type: int32
      generator: {type: range, min: 1, max: 10, distribution: exponential, lambda: 2.0}

    - name: unit_price
      type: float64
      generator:
        type: derived_from
        source_column: product_name
        mapping:
          "Wireless Headphones": 79.99
          "USB-C Hub": 45.99
          "Mechanical Keyboard": 129.99
          "4K Monitor": 449.99
          "Laptop Stand": 59.99
          "Webcam HD": 89.99
          "Portable SSD 2TB": 159.99
          "Smart Mouse": 39.99
          "Desk Lamp": 34.99
          "Cable Kit": 19.99

    - name: total_amount
      type: float64
      generator: {type: computed, expression: "quantity * unit_price"}

    - name: region
      type: string
      generator:
        type: weighted_enum
        values:
          "US-East": 0.30
          "US-West": 0.25
          "EU-West": 0.20
          "APAC": 0.15
          "LATAM": 0.10

    - name: payment_method
      type: string
      generator: {type: enum, values: ["Credit Card", "PayPal", "Wire Transfer", "Crypto"]}

    - name: status
      type: string
      generator:
        type: weighted_enum
        values:
          "completed": 0.75
          "processing": 0.15
          "refunded": 0.05
          "cancelled": 0.05

partitioning:
  parquet:
    keys: [region]
    time_column: order_ts
    time_granularity: day        # bucket/region=US-East/year=2026/month=03/day=24/*.parquet
  json: flat                      # bucket/*.ndjson
  csv: flat                       # bucket/*.csv

iceberg:
  warehouse: analytics
  namespace: demo
  table: orders
  partition_spec: "PARTITIONED BY (region, days(order_ts))"
  sort_order: "order_ts"

buckets:
  parquet: "orders-parquet"
  json: "orders-json"
  csv: "orders-csv"
  iceberg: null                   # Iceberg manages its own storage location

volume:
  default_rows_per_batch: 500
  default_batches_per_minute: 12  # ~100 rows/sec
  profiles:
    low:    {rows_per_batch: 100, batches_per_minute: 6}
    medium: {rows_per_batch: 500, batches_per_minute: 12}
    high:   {rows_per_batch: 2000, batches_per_minute: 30}
  ramp_up_seconds: 30             # Gradual start for demo effect

queries:
  - id: revenue_by_region
    name: "Revenue by region"
    sql: >
      SELECT region,
             ROUND(SUM(total_amount), 2) AS revenue,
             COUNT(*) AS order_count
      FROM {catalog}.{namespace}.orders
      GROUP BY region
      ORDER BY revenue DESC
    chart_type: bar
    chart_config:
      x: region
      y: revenue
      series: null

  - id: orders_per_minute
    name: "Orders per minute"
    sql: >
      SELECT date_trunc('minute', order_ts) AS minute,
             COUNT(*) AS orders
      FROM {catalog}.{namespace}.orders
      WHERE order_ts > current_timestamp - interval '30' minute
      GROUP BY 1
      ORDER BY 1
    chart_type: line
    chart_config:
      x: minute
      y: orders
    auto_refresh_seconds: 10

  - id: top_products
    name: "Top 10 products by quantity"
    sql: >
      SELECT product_name,
             SUM(quantity) AS total_qty,
             ROUND(SUM(total_amount), 2) AS total_revenue
      FROM {catalog}.{namespace}.orders
      GROUP BY product_name
      ORDER BY total_qty DESC
      LIMIT 10
    chart_type: horizontal_bar
    chart_config:
      x: total_qty
      y: product_name

  - id: category_revenue
    name: "Revenue by category"
    sql: >
      SELECT category,
             ROUND(SUM(total_amount), 2) AS revenue
      FROM {catalog}.{namespace}.orders
      GROUP BY category
    chart_type: pie
    chart_config:
      dimension: category
      metric: revenue

  - id: payment_distribution
    name: "Payment methods"
    sql: >
      SELECT payment_method,
             COUNT(*) AS count
      FROM {catalog}.{namespace}.orders
      GROUP BY payment_method
    chart_type: donut
    chart_config:
      dimension: payment_method
      metric: count

  - id: kpis
    name: "Key metrics"
    sql: >
      SELECT COUNT(*) AS total_orders,
             ROUND(SUM(total_amount), 2) AS total_revenue,
             ROUND(AVG(total_amount), 2) AS avg_order_value,
             COUNT(DISTINCT customer_id) AS unique_customers
      FROM {catalog}.{namespace}.orders
    chart_type: scalar
    chart_config:
      metrics: [total_orders, total_revenue, avg_order_value, unique_customers]

  - id: status_over_time
    name: "Order status over time"
    sql: >
      SELECT date_trunc('minute', order_ts) AS minute,
             status,
             COUNT(*) AS count
      FROM {catalog}.{namespace}.orders
      GROUP BY 1, 2
      ORDER BY 1
    chart_type: stacked_area
    chart_config:
      x: minute
      y: count
      series: status

  - id: region_time_heatmap
    name: "Volume by region and hour"
    sql: >
      SELECT region,
             hour(order_ts) AS hour_of_day,
             COUNT(*) AS orders
      FROM {catalog}.{namespace}.orders
      GROUP BY 1, 2
    chart_type: pivot_table
    chart_config:
      rows: region
      columns: hour_of_day
      values: orders

metabase_dashboard:
  name: "Live Orders Analytics"
  description: "Real-time e-commerce order monitoring"
  layout:
    - {query: kpis, row: 0, col: 0, width: 18, height: 3}
    - {query: orders_per_minute, row: 3, col: 0, width: 12, height: 5}
    - {query: revenue_by_region, row: 3, col: 12, width: 6, height: 5}
    - {query: top_products, row: 8, col: 0, width: 9, height: 5}
    - {query: category_revenue, row: 8, col: 9, width: 4, height: 5}
    - {query: payment_distribution, row: 8, col: 13, width: 5, height: 5}
    - {query: status_over_time, row: 13, col: 0, width: 12, height: 5}
    - {query: region_time_heatmap, row: 13, col: 12, width: 6, height: 5}
```

### File: `datasets/iot-telemetry.yaml`

```yaml
id: iot-telemetry
name: "IoT sensor telemetry"
description: "Industrial sensor readings — temperature, humidity, pressure, battery. High volume time-series."

schema:
  columns:
    - name: reading_id
      type: string
      generator: uuid

    - name: reading_ts
      type: timestamp
      generator: now_jitter

    - name: device_id
      type: string
      generator: {type: pattern, template: "sensor-{facility}-{seq:04d}", seq_range: [1, 200]}

    - name: facility
      type: string
      generator:
        type: weighted_enum
        values:
          "Plant-Alpha": 0.30
          "Plant-Beta": 0.25
          "Warehouse-East": 0.20
          "Warehouse-West": 0.15
          "HQ-Lab": 0.10

    - name: temperature_c
      type: float64
      generator:
        type: gaussian_per_group
        group_column: facility
        profiles:
          "Plant-Alpha": {mean: 45.0, stddev: 8.0}
          "Plant-Beta": {mean: 38.0, stddev: 6.0}
          "Warehouse-East": {mean: 22.0, stddev: 3.0}
          "Warehouse-West": {mean: 24.0, stddev: 3.5}
          "HQ-Lab": {mean: 21.0, stddev: 1.0}
        precision: 1

    - name: humidity_pct
      type: float64
      generator: {type: gaussian, mean: 55.0, stddev: 15.0, min: 10.0, max: 99.0, precision: 1}

    - name: pressure_hpa
      type: float64
      generator: {type: gaussian, mean: 1013.25, stddev: 10.0, precision: 2}

    - name: battery_pct
      type: int32
      generator: {type: range, min: 5, max: 100}

    - name: vibration_mm_s
      type: float64
      generator: {type: lognormal, mean: 1.0, sigma: 0.8, precision: 2}

    - name: alert_level
      type: string
      generator:
        type: weighted_enum
        values:
          "normal": 0.85
          "warning": 0.10
          "critical": 0.03
          "maintenance": 0.02

partitioning:
  parquet:
    keys: [facility]
    time_column: reading_ts
    time_granularity: hour
  json: flat
  csv: flat

iceberg:
  warehouse: analytics
  namespace: demo
  table: sensor_readings
  partition_spec: "PARTITIONED BY (facility, hours(reading_ts))"
  sort_order: "reading_ts"

buckets:
  parquet: "telemetry-parquet"
  json: "telemetry-json"
  csv: "telemetry-csv"

volume:
  default_rows_per_batch: 1000
  default_batches_per_minute: 20    # ~330 rows/sec — sensors report frequently
  profiles:
    low:    {rows_per_batch: 200, batches_per_minute: 6}
    medium: {rows_per_batch: 1000, batches_per_minute: 20}
    high:   {rows_per_batch: 5000, batches_per_minute: 60}
  ramp_up_seconds: 15

queries:
  - id: temp_by_facility
    name: "Avg temperature by facility"
    sql: >
      SELECT facility,
             ROUND(AVG(temperature_c), 1) AS avg_temp,
             ROUND(MIN(temperature_c), 1) AS min_temp,
             ROUND(MAX(temperature_c), 1) AS max_temp
      FROM {catalog}.{namespace}.sensor_readings
      GROUP BY facility
    chart_type: bar
    chart_config:
      x: facility
      y: avg_temp

  - id: readings_per_minute
    name: "Readings per minute"
    sql: >
      SELECT date_trunc('minute', reading_ts) AS minute,
             COUNT(*) AS readings
      FROM {catalog}.{namespace}.sensor_readings
      WHERE reading_ts > current_timestamp - interval '30' minute
      GROUP BY 1
      ORDER BY 1
    chart_type: line
    auto_refresh_seconds: 10

  - id: alert_breakdown
    name: "Alert levels"
    sql: >
      SELECT alert_level,
             COUNT(*) AS count
      FROM {catalog}.{namespace}.sensor_readings
      GROUP BY alert_level
    chart_type: donut

  - id: critical_over_time
    name: "Critical alerts over time"
    sql: >
      SELECT date_trunc('minute', reading_ts) AS minute,
             facility,
             COUNT(*) AS alerts
      FROM {catalog}.{namespace}.sensor_readings
      WHERE alert_level IN ('critical', 'warning')
      GROUP BY 1, 2
      ORDER BY 1
    chart_type: stacked_area
    auto_refresh_seconds: 15

  - id: battery_distribution
    name: "Battery levels"
    sql: >
      SELECT CASE
               WHEN battery_pct < 20 THEN 'Critical (<20%)'
               WHEN battery_pct < 50 THEN 'Low (20-50%)'
               WHEN battery_pct < 80 THEN 'Good (50-80%)'
               ELSE 'Full (80-100%)'
             END AS battery_range,
             COUNT(*) AS device_count
      FROM {catalog}.{namespace}.sensor_readings
      GROUP BY 1
    chart_type: bar

  - id: kpis
    name: "Sensor KPIs"
    sql: >
      SELECT COUNT(*) AS total_readings,
             COUNT(DISTINCT device_id) AS active_devices,
             ROUND(AVG(temperature_c), 1) AS avg_temperature,
             SUM(CASE WHEN alert_level = 'critical' THEN 1 ELSE 0 END) AS critical_alerts
      FROM {catalog}.{namespace}.sensor_readings
    chart_type: scalar

  - id: vibration_by_facility
    name: "Vibration levels"
    sql: >
      SELECT facility,
             ROUND(AVG(vibration_mm_s), 2) AS avg_vibration,
             ROUND(MAX(vibration_mm_s), 2) AS peak_vibration
      FROM {catalog}.{namespace}.sensor_readings
      GROUP BY facility
      ORDER BY avg_vibration DESC
    chart_type: horizontal_bar

metabase_dashboard:
  name: "IoT Sensor Monitoring"
  description: "Real-time industrial sensor telemetry"
  layout:
    - {query: kpis, row: 0, col: 0, width: 18, height: 3}
    - {query: readings_per_minute, row: 3, col: 0, width: 12, height: 5}
    - {query: alert_breakdown, row: 3, col: 12, width: 6, height: 5}
    - {query: temp_by_facility, row: 8, col: 0, width: 9, height: 5}
    - {query: vibration_by_facility, row: 8, col: 9, width: 9, height: 5}
    - {query: critical_over_time, row: 13, col: 0, width: 12, height: 5}
    - {query: battery_distribution, row: 13, col: 12, width: 6, height: 5}
```

### File: `datasets/financial-txn.yaml`

```yaml
id: financial-txn
name: "Financial transactions"
description: "Banking transactions with risk scoring and compliance flags. Compliance/audit demo."

schema:
  columns:
    - name: txn_id
      type: string
      generator: uuid

    - name: txn_ts
      type: timestamp
      generator: now_jitter

    - name: account_from
      type: string
      generator: {type: pattern, template: "ACC-{seq:06d}", seq_range: [100000, 999999]}

    - name: account_to
      type: string
      generator: {type: pattern, template: "ACC-{seq:06d}", seq_range: [100000, 999999]}

    - name: amount
      type: float64
      generator: {type: lognormal, mean: 5.5, sigma: 2.0, min: 0.50, max: 500000.0, precision: 2}

    - name: currency
      type: string
      generator:
        type: weighted_enum
        values:
          "USD": 0.40
          "EUR": 0.22
          "GBP": 0.12
          "AED": 0.10
          "JPY": 0.06
          "CHF": 0.05
          "SGD": 0.05

    - name: txn_type
      type: string
      generator:
        type: weighted_enum
        values:
          "transfer": 0.35
          "payment": 0.30
          "deposit": 0.20
          "withdrawal": 0.15

    - name: channel
      type: string
      generator:
        type: weighted_enum
        values:
          "mobile_app": 0.40
          "web_portal": 0.25
          "branch": 0.15
          "api": 0.12
          "atm": 0.08

    - name: country
      type: string
      generator:
        type: weighted_enum
        values:
          "US": 0.30
          "UK": 0.15
          "UAE": 0.12
          "DE": 0.10
          "SG": 0.08
          "JP": 0.08
          "CH": 0.07
          "FR": 0.05
          "Other": 0.05

    - name: risk_score
      type: float64
      generator: {type: beta, alpha: 2.0, beta: 8.0, precision: 3}
      # Beta(2,8) produces mostly low scores with a long right tail — realistic

    - name: flagged
      type: boolean
      generator: {type: computed, expression: "risk_score > 0.65"}

    - name: compliance_status
      type: string
      generator:
        type: computed
        expression: >
          CASE
            WHEN risk_score > 0.85 THEN 'blocked'
            WHEN risk_score > 0.65 THEN 'review'
            ELSE 'cleared'
          END

partitioning:
  parquet:
    keys: [currency]
    time_column: txn_ts
    time_granularity: day
  json: flat
  csv: flat

iceberg:
  warehouse: analytics
  namespace: demo
  table: transactions
  partition_spec: "PARTITIONED BY (currency, days(txn_ts))"
  sort_order: "txn_ts"

buckets:
  parquet: "txn-parquet"
  json: "txn-json"
  csv: "txn-csv"

volume:
  default_rows_per_batch: 300
  default_batches_per_minute: 10
  profiles:
    low:    {rows_per_batch: 50, batches_per_minute: 4}
    medium: {rows_per_batch: 300, batches_per_minute: 10}
    high:   {rows_per_batch: 1000, batches_per_minute: 20}
  ramp_up_seconds: 20

queries:
  - id: volume_by_currency
    name: "Transaction volume by currency"
    sql: >
      SELECT currency,
             COUNT(*) AS txn_count,
             ROUND(SUM(amount), 2) AS total_volume
      FROM {catalog}.{namespace}.transactions
      GROUP BY currency
      ORDER BY total_volume DESC
    chart_type: bar

  - id: txn_per_minute
    name: "Transactions per minute"
    sql: >
      SELECT date_trunc('minute', txn_ts) AS minute,
             COUNT(*) AS txns
      FROM {catalog}.{namespace}.transactions
      WHERE txn_ts > current_timestamp - interval '30' minute
      GROUP BY 1
      ORDER BY 1
    chart_type: line
    auto_refresh_seconds: 10

  - id: flagged_rate
    name: "Flagged transactions over time"
    sql: >
      SELECT date_trunc('minute', txn_ts) AS minute,
             compliance_status,
             COUNT(*) AS count
      FROM {catalog}.{namespace}.transactions
      GROUP BY 1, 2
      ORDER BY 1
    chart_type: stacked_area

  - id: channel_breakdown
    name: "Transactions by channel"
    sql: >
      SELECT channel,
             COUNT(*) AS count,
             ROUND(AVG(amount), 2) AS avg_amount
      FROM {catalog}.{namespace}.transactions
      GROUP BY channel
    chart_type: horizontal_bar

  - id: high_risk_accounts
    name: "High risk accounts"
    sql: >
      SELECT account_from,
             COUNT(*) AS flagged_txns,
             ROUND(SUM(amount), 2) AS total_flagged_amount,
             ROUND(MAX(risk_score), 3) AS max_risk
      FROM {catalog}.{namespace}.transactions
      WHERE flagged = true
      GROUP BY account_from
      ORDER BY flagged_txns DESC
      LIMIT 20
    chart_type: table

  - id: kpis
    name: "Transaction KPIs"
    sql: >
      SELECT COUNT(*) AS total_txns,
             ROUND(SUM(amount), 2) AS total_volume,
             ROUND(AVG(amount), 2) AS avg_txn_size,
             SUM(CASE WHEN flagged THEN 1 ELSE 0 END) AS flagged_count,
             ROUND(100.0 * SUM(CASE WHEN flagged THEN 1 ELSE 0 END) / COUNT(*), 2) AS flag_rate_pct
      FROM {catalog}.{namespace}.transactions
    chart_type: scalar

  - id: country_heatmap
    name: "Volume by country and type"
    sql: >
      SELECT country,
             txn_type,
             COUNT(*) AS txns
      FROM {catalog}.{namespace}.transactions
      GROUP BY 1, 2
    chart_type: pivot_table

metabase_dashboard:
  name: "Financial Transactions Monitor"
  description: "Real-time transaction monitoring with risk scoring"
  layout:
    - {query: kpis, row: 0, col: 0, width: 18, height: 3}
    - {query: txn_per_minute, row: 3, col: 0, width: 12, height: 5}
    - {query: volume_by_currency, row: 3, col: 12, width: 6, height: 5}
    - {query: flagged_rate, row: 8, col: 0, width: 12, height: 5}
    - {query: channel_breakdown, row: 8, col: 12, width: 6, height: 5}
    - {query: high_risk_accounts, row: 13, col: 0, width: 12, height: 5}
    - {query: country_heatmap, row: 13, col: 12, width: 6, height: 5}
```

---

## Task 2: Update data-generator code

Extend the existing data-generator. Do NOT rewrite from scratch. Read the current codebase first.

### New files to add

**`src/schema_loader.py`** (or `.ts` / `.js` — match existing language)

Parses a scenario YAML file and returns:
- A list of column definitions with their generator configs
- The volume profile
- The partitioning config for the selected format
- The Iceberg table definition
- The query pack

**`src/value_generators.py`**

Implements every generator type referenced in the scenarios above:

| Generator type | Behavior |
|---|---|
| `uuid` | Random UUID v4 string |
| `now_jitter` | `datetime.utcnow()` plus random 0-2 second offset |
| `range` | Uniform random int/float between min and max |
| `enum` | Uniform random pick from a list |
| `weighted_enum` | Weighted random pick (values map to probabilities, must sum to 1.0) |
| `fake` | Uses Faker library for realistic names, addresses, etc. Method specifies which faker |
| `pattern` | String template with `{seq:04d}` for zero-padded sequence and `{facility}` for referencing other columns |
| `gaussian` | Normal distribution with mean/stddev, optional min/max clamp and precision |
| `gaussian_per_group` | Different gaussian params per value of a group column (for facility-specific temperatures) |
| `lognormal` | Log-normal distribution with mean/sigma, optional min/max/precision |
| `beta` | Beta distribution with alpha/beta params (for risk scores skewed toward low values) |
| `derived_from` | Looks up value from another column via a static mapping dict |
| `computed` | Evaluates a simple expression referencing other columns in the same row |
| `weighted_bool` | Boolean with configurable true probability |

Implementation notes:
- Each generator is a function that takes the column config + the current row dict (for derived/computed columns) and returns a value
- Columns are generated in order — `derived_from` and `computed` columns MUST come after their source columns in the schema
- The `computed` expression evaluator needs to handle basic arithmetic (`quantity * unit_price`) and CASE expressions. Keep it simple — use `eval()` with a restricted namespace containing only the row's values, or implement a tiny expression parser. Do NOT use full SQL parsing.

**`src/writers/parquet_writer.py`**

- Takes a batch of rows (list of dicts) and writes a Parquet file to the target MinIO bucket
- Uses `pyarrow` for Parquet generation, `boto3` for S3 upload
- Applies partitioning from the scenario config: creates the partition path (e.g., `region=US-East/year=2026/month=03/day=24/`) and uploads the file there
- File naming: `{batch_timestamp_ms}.parquet` to avoid collisions
- Sets Parquet metadata: row group size, compression (snappy), column stats

**`src/writers/json_writer.py`**

- Writes NDJSON (one JSON object per line, newline-delimited)
- Uploads to the flat bucket path
- File naming: `{batch_timestamp_ms}.ndjson`
- Timestamps formatted as ISO 8601 strings

**`src/writers/csv_writer.py`**

- Standard CSV with header row
- Uploads to the flat bucket path
- File naming: `{batch_timestamp_ms}.csv`
- Timestamps formatted as ISO 8601 strings

**`src/writers/iceberg_writer.py`**

- Uses `pyiceberg` to write directly to an AIStor Tables endpoint OR external Iceberg REST Catalog
- Connection config (endpoint URL, warehouse, namespace) comes from the scenario YAML + the target MinIO node's connection info
- Creates the table if it doesn't exist (using the schema from the scenario)
- Appends rows as a PyArrow table via `table.append(pa_table)`
- This writer is used when format is set to `iceberg`

**`src/table_setup.py`**

Runs once at generator start, before streaming begins:

1. **Create buckets** — creates the buckets defined in the scenario's `buckets` config on the target MinIO. Skip if already exists.
2. **Create Iceberg table** — if format is `iceberg`, connect to the target catalog (AIStor Tables `/_iceberg` or external `iceberg-rest`) and create the table using the scenario's `iceberg` config. Use PyIceberg's `catalog.create_table()`. Skip if already exists.
3. **Register Hive/Trino table** — if format is `parquet`, `json`, or `csv` and the target path uses an external catalog, execute a `CREATE TABLE IF NOT EXISTS` DDL via the Trino connection to register the external table pointing at the bucket. The DDL depends on format:
   - Parquet: `CREATE TABLE ... WITH (format = 'PARQUET', external_location = 's3a://bucket/')`
   - JSON: `CREATE TABLE ... WITH (format = 'JSON', external_location = 's3a://bucket/')`
   - CSV: `CREATE TABLE ... WITH (format = 'CSV', external_location = 's3a://bucket/')`

**`src/metabase_setup.py`**

Runs after Metabase is healthy and the Trino database connection exists. Creates the dashboard from the scenario's `metabase_dashboard` config:

1. Get a Metabase session token via `POST /api/session`
2. Find the Trino database ID via `GET /api/database`
3. For each query in the scenario's `queries` list:
   a. Replace `{catalog}` and `{namespace}` placeholders with actual values from the demo config
   b. Create a Metabase "question" (native query card) via `POST /api/card` with the SQL, linked to the Trino database
   c. Set the visualization type based on `chart_type`: `bar` → "bar", `line` → "line", `pie` → "pie", `donut` → "pie" with donut setting, `horizontal_bar` → "bar" with horizontal setting, `scalar` → "scalar", `stacked_area` → "area" with stacking, `pivot_table` → "pivot", `table` → "table"
   d. If `auto_refresh_seconds` is set, note it for the dashboard config
4. Create the dashboard via `POST /api/dashboard` with the name and description
5. Add each card to the dashboard via `PUT /api/dashboard/{id}` with the layout positions from `metabase_dashboard.layout`

Implementation note: Metabase's API for adding cards to dashboards uses `PUT /api/dashboard/{id}` with the full dashboard body including `dashcards`. Build the full dashcards array and send it in one PUT, don't add cards one at a time.

---

## Task 3: UI changes to the data-generator properties panel

The data-generator's properties panel in DemoForge currently shows basic settings. Extend it with these new controls. Match the existing UI patterns — look at how other component properties panels are built.

### New settings in the properties panel (when a data-generator node is selected):

**Scenario selector** — dropdown, prominent at the top of the settings section

| Control | Type | Options | Default |
|---|---|---|---|
| Dataset scenario | Dropdown | "E-commerce orders", "IoT sensor telemetry", "Financial transactions" | E-commerce orders |

When the scenario changes, the panel should update to show that scenario's description text below the dropdown.

**Format selector** — dropdown, below scenario

| Control | Type | Options | Default |
|---|---|---|---|
| Output format | Dropdown | "Parquet", "JSON (NDJSON)", "CSV", "Iceberg (native)" | Parquet |

When "Iceberg (native)" is selected, show a note: "Writes directly to AIStor Tables via Iceberg REST API. Requires Tables-enabled MinIO target."

**Volume profile** — dropdown or segmented control

| Control | Type | Options | Default |
|---|---|---|---|
| Data rate | Segmented | Low / Medium / High | Medium |

Show the actual rows/sec below the control based on the selected scenario's volume profile. For example: "Medium: ~100 rows/sec (500 rows x 12 batches/min)"

**Generator status section** — visible when the demo is running

| Element | Type | Behavior |
|---|---|---|
| Status badge | Badge | "Idle" (gray), "Streaming" (green pulse), "Error" (red), "Ramping up" (amber) |
| Rows generated | Counter | Live count, updates every second |
| Current rate | Label | "124 rows/sec" — actual measured rate |
| Batches sent | Counter | Total batches written |
| Last batch | Timestamp | "3 seconds ago" |
| Errors | Counter | "0 errors" (green) or "3 errors" (red, clickable to see log) |

**Query preview section** — collapsible, below the status section

| Element | Type | Behavior |
|---|---|---|
| Header | Text | "Pre-built queries (8)" — count from the loaded scenario |
| Query list | Accordion | Each query shows: name, SQL (in a code block), chart type badge |
| "Run in Trino" button | Button per query | Opens a terminal tab and runs the query against the connected Trino, replacing `{catalog}` and `{namespace}` with actual values |
| "Create Metabase dashboard" button | Button (below list) | Triggers `metabase_setup.py` to build the dashboard from the query pack. Disabled if Metabase isn't deployed or not healthy. Shows "Dashboard created ✓" after success. |

### Updates to the data-generator node on the diagram canvas

The `ComponentNode` rendering for data-generator should show:
- The scenario name as a subtitle (e.g., "E-commerce orders")
- The format as a small badge (e.g., "Parquet" in amber, "Iceberg" in teal)
- When streaming: a row count indicator (e.g., "12.4K rows") that updates live
- The existing "Idle" / status badge should reflect the new states

### Connection edge labels

The edge from a data-generator to its target MinIO cluster should show the format in the edge label. Currently the screenshot shows "Data Push" and "JSON Data". These should update dynamically based on the selected format:
- "Parquet data" (when format is Parquet)
- "JSON data" (when format is JSON)
- "CSV data" (when format is CSV)
- "Iceberg writes" (when format is Iceberg native)

---

## Task 4: Generator API endpoints

The data-generator needs these API endpoints (accessible via the DemoForge proxy):

```
GET  /status
  → {state: "idle"|"streaming"|"error"|"ramp_up", scenario: "ecommerce-orders",
     format: "parquet", rows_generated: 12453, rows_per_sec: 124.5,
     batches_sent: 25, last_batch_ts: "2026-03-24T14:30:00Z", errors: 0}

POST /start
  Body: {scenario: "ecommerce-orders", format: "parquet", rate: "medium"}
  → Starts streaming. Returns {state: "ramp_up"}

POST /stop
  → Stops streaming. Returns {state: "idle"}

POST /pause
  → Pauses streaming (keeps state). Returns {state: "paused"}

POST /resume
  → Resumes from paused. Returns {state: "streaming"}

GET  /scenarios
  → Lists available scenarios: [{id, name, description, formats: [...], queries_count}]

GET  /scenarios/{id}
  → Full scenario definition including schema and queries

GET  /scenarios/{id}/queries
  → Just the queries array with {catalog} and {namespace} already replaced

POST /setup-metabase
  Body: {metabase_url: "...", trino_catalog: "native", trino_namespace: "demo"}
  → Runs metabase_setup.py, creates dashboard. Returns {dashboard_id, dashboard_url}
```

---

## Task 5: Test scenarios for the dual-cluster demo

These are end-to-end test flows that should work after implementation. Use the exact topology from the screenshot.

### Test 1: Parquet on external catalog path

1. Select the bottom data-generator (192.168.147.5)
2. Set scenario: "E-commerce orders"
3. Set format: "Parquet"
4. Set rate: "Medium"
5. Click Start
6. Verify: buckets `orders-parquet` created on AIStor Iceberg Cluster (192.168.147.6)
7. Verify: Parquet files appearing with correct partition paths: `orders-parquet/region=US-East/year=2026/...`
8. In Trino terminal: `SELECT count(*) FROM external.demo.orders` — returns growing count
9. In Trino terminal: `SELECT region, sum(total_amount) FROM external.demo.orders GROUP BY region` — returns grouped results
10. Verify: row counter in properties panel updates live

### Test 2: Iceberg native on AIStor Tables path

1. Select the top data-generator (192.168.147.11)
2. Set scenario: "E-commerce orders" (same scenario as Test 1)
3. Set format: "Iceberg (native)"
4. Set rate: "Medium"
5. Click Start
6. Verify: Iceberg table `demo.orders` created on AIStor Tables Cluster (192.168.147.17) via `/_iceberg`
7. In Trino terminal: `SELECT count(*) FROM native.demo.orders` — returns growing count
8. In Trino terminal: same revenue-by-region query — same column shapes as Test 1

### Test 3: Cross-catalog comparison

With both generators running (Tests 1 and 2):

1. In Trino terminal, run the cross-catalog join:
   ```sql
   SELECT 'native' AS source, region, count(*) AS orders, round(sum(total_amount),2) AS revenue
   FROM native.demo.orders GROUP BY region
   UNION ALL
   SELECT 'external' AS source, region, count(*) AS orders, round(sum(total_amount),2) AS revenue
   FROM external.demo.orders GROUP BY region
   ORDER BY source, revenue DESC
   ```
2. Verify: both sources return the same regions with similar distributions (not identical counts — different generators, but same weighted distribution)

### Test 4: Metabase dashboard creation

With Test 1 or Test 2 running:

1. Open the data-generator properties panel
2. Expand "Pre-built queries" section — verify 8 queries listed for E-commerce scenario
3. Click "Run in Trino" on "Revenue by region" — verify terminal tab opens, query runs, results appear
4. Click "Create Metabase dashboard"
5. Verify: dashboard created in Metabase with 8 cards matching the layout
6. Open Metabase via Control Plane → verify "Live Orders Analytics" dashboard shows charts
7. Wait 30 seconds → verify "Orders per minute" line chart shows new data points appearing
8. Verify: KPI cards show non-zero values for total_orders, total_revenue, etc.

### Test 5: Format switching

1. Stop the bottom generator
2. Change format from "Parquet" to "JSON (NDJSON)"
3. Start again
4. Verify: new bucket `orders-json` created, NDJSON files appearing
5. Verify: edge label on diagram changes from "Parquet data" to "JSON data"
6. Register the JSON table in Trino (table_setup should handle this automatically)
7. Query via Trino — same results, different underlying format

### Test 6: Scenario switching

1. Stop a generator
2. Change scenario from "E-commerce orders" to "IoT sensor telemetry"
3. Verify: properties panel updates — shows "Industrial sensor readings..." description, query count changes to 7
4. Start generator
5. Verify: new buckets created (telemetry-parquet or similar), new table schema
6. In Trino: `SELECT facility, avg(temperature_c) FROM native.demo.sensor_readings GROUP BY facility` — returns results
7. Click "Create Metabase dashboard" — creates "IoT Sensor Monitoring" dashboard

### Test 7: Rate profiles

1. Start a generator on "Low" rate
2. Note the actual rows/sec in the status section (~17 rows/sec for E-commerce Low)
3. Stop, change to "High", start
4. Note the new rate (~1000 rows/sec for E-commerce High)
5. Verify MinIO metrics in Prometheus show the throughput change

---

## What NOT to do

- Don't rewrite the data-generator from scratch — extend it
- Don't hardcode catalog names in queries — always use `{catalog}` and `{namespace}` placeholders
- Don't create Metabase dashboards manually — the query pack drives everything programmatically
- Don't add new scenario formats beyond the 3 defined here (more can be added later by just dropping a YAML file)
- Don't modify the MinIO, Trino, or Metabase component manifests — this work is entirely within the data-generator component plus UI updates
- Don't build a custom data-generator Docker image if the current one can be extended via config + mounted code — check how the existing one is structured first

---

## Dependency additions

The data-generator container will need these packages (add to its requirements/package file):

- `pyarrow` — Parquet generation
- `pyiceberg` — Iceberg table writes via REST Catalog
- `faker` — realistic name/address generation
- `boto3` — S3 uploads (likely already present)
- `pyyaml` — scenario file parsing (likely already present)
- `requests` or `httpx` — Metabase API calls

Check what's already installed before adding duplicates.
