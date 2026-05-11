import time
import os
import random
import io
import csv
import json
import datetime
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import boto3
import requests
from botocore.exceptions import ClientError, EndpointResolutionError, NoCredentialsError

# --- Config from environment ---
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "localhost:9000")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "minioadmin")
S3_BUCKET = os.environ.get("S3_BUCKET", "raw-data")
PARTITION_BY_DATE = os.environ.get("PARTITION_BY_DATE", "true").lower() == "true"

# New controls
DG_FORMAT = os.environ.get("DG_FORMAT", "parquet").lower()          # parquet | json | csv | iceberg | kafka
DG_FILE_SIZE_ROWS = int(os.environ.get("DG_FILE_SIZE_ROWS", "1000"))  # rows per file
DG_RATE = float(os.environ.get("DG_RATE", "1"))                       # files per minute
DG_BATCH_SIZE = int(os.environ.get("DG_BATCH_SIZE", "10"))            # files per batch

# Scenario controls
DG_SCENARIO = os.environ.get("DG_SCENARIO", "")                       # e.g. ecommerce-orders
DG_RATE_PROFILE = os.environ.get("DG_RATE_PROFILE", "medium").lower() # low | medium | high

# Backward-compatible: legacy env vars still honoured if new ones are absent and legacy are set
if "BATCH_SIZE" in os.environ and "DG_FILE_SIZE_ROWS" not in os.environ:
    DG_FILE_SIZE_ROWS = int(os.environ["BATCH_SIZE"])
if "INTERVAL_SECONDS" in os.environ and "DG_RATE" not in os.environ:
    interval_s = int(os.environ["INTERVAL_SECONDS"])
    DG_RATE = 60.0 / interval_s if interval_s > 0 else 1.0

INTERVAL_SECONDS = 60.0 / DG_RATE if DG_RATE > 0 else 60.0


def split_s3_bucket_and_prefix(raw: str) -> tuple[str, str]:
    """
    Split values like ``/raw/ecommerce-orders`` into a valid S3 bucket and object prefix.

    Bucket names cannot contain ``/``; users often paste a path into target bucket.
    Returns ``(bucket, key_prefix)`` where ``key_prefix`` is '' or ends with ``/``.
    """
    s = (raw or "").strip()
    if not s:
        return "", ""
    s = s.strip("/")
    if not s:
        return "", ""
    parts = [p for p in s.split("/") if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], "/".join(parts[1:]).rstrip("/") + "/"


# --- Legacy static data (used when DG_SCENARIO is not set) ---
PRODUCTS = [
    "Widget Pro", "Gadget X", "Smart Sensor", "Data Cable", "Cloud Key",
    "API Token Pack", "Storage Drive 1TB", "Network Switch", "Security Camera",
    "Power Bank", "USB Hub", "LED Monitor", "Keyboard Pro", "Mouse Wireless",
    "Laptop Stand", "Webcam HD", "Microphone USB", "Speaker Set",
    "Headphones BT", "Charger Fast",
]

REGIONS = ["US-East", "US-West", "EU-West", "EU-East", "APAC", "LATAM"]

SCHEMA = pa.schema([
    pa.field("order_id", pa.int64()),
    pa.field("customer_id", pa.int64()),
    pa.field("product_name", pa.string()),
    pa.field("quantity", pa.int32()),
    pa.field("unit_price", pa.float64()),
    pa.field("order_date", pa.timestamp("us")),
    pa.field("region", pa.string()),
])

FIELDNAMES = ["order_id", "customer_id", "product_name", "quantity", "unit_price", "order_date", "region"]


def make_s3_client():
    endpoint = S3_ENDPOINT if S3_ENDPOINT.startswith("http") else f"http://{S3_ENDPOINT}"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name="us-east-1",
    )


def wait_for_minio(timeout=60):
    print(f"Waiting for MinIO at {S3_ENDPOINT} (up to {timeout}s)...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            client = make_s3_client()
            client.list_buckets()
            print("MinIO is available.")
            return client
        except Exception as exc:
            print(f"  MinIO not ready: {exc}. Retrying in 3s...")
            time.sleep(3)
    raise RuntimeError(f"MinIO at {S3_ENDPOINT} did not become available within {timeout}s")


def ensure_bucket(client, bucket):
    try:
        client.head_bucket(Bucket=bucket)
        print(f"Bucket '{bucket}' already exists.")
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code in ("404", "NoSuchBucket"):
            client.create_bucket(Bucket=bucket)
            print(f"Created bucket '{bucket}'.")
        else:
            raise


def generate_rows(start_order_id, num_rows):
    now = datetime.datetime.utcnow()
    rows = []
    for i in range(num_rows):
        rows.append({
            "order_id": start_order_id + i,
            "customer_id": random.randint(1000, 9999),
            "product_name": random.choice(PRODUCTS),
            "quantity": random.randint(1, 50),
            "unit_price": round(random.uniform(5.99, 499.99), 2),
            "order_date": now - datetime.timedelta(seconds=random.randint(0, 3600)),
            "region": random.choice(REGIONS),
        })
    return rows


def rows_to_parquet_bytes(rows):
    order_ids = [r["order_id"] for r in rows]
    customer_ids = [r["customer_id"] for r in rows]
    product_names = [r["product_name"] for r in rows]
    quantities = [r["quantity"] for r in rows]
    unit_prices = [r["unit_price"] for r in rows]
    order_dates = [r["order_date"] for r in rows]
    regions = [r["region"] for r in rows]

    table = pa.table(
        {
            "order_id": pa.array(order_ids, type=pa.int64()),
            "customer_id": pa.array(customer_ids, type=pa.int64()),
            "product_name": pa.array(product_names, type=pa.string()),
            "quantity": pa.array(quantities, type=pa.int32()),
            "unit_price": pa.array(unit_prices, type=pa.float64()),
            "order_date": pa.array(order_dates, type=pa.timestamp("us")),
            "region": pa.array(regions, type=pa.string()),
        },
        schema=SCHEMA,
    )
    buf = io.BytesIO()
    pq.write_table(table, buf)
    buf.seek(0)
    return buf.read()


def rows_to_json_bytes(rows):
    lines = []
    for r in rows:
        rec = dict(r)
        rec["order_date"] = rec["order_date"].isoformat()
        lines.append(json.dumps(rec))
    return ("\n".join(lines) + "\n").encode("utf-8")


def rows_to_csv_bytes(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDNAMES)
    writer.writeheader()
    for r in rows:
        rec = dict(r)
        rec["order_date"] = rec["order_date"].isoformat()
        writer.writerow(rec)
    return buf.getvalue().encode("utf-8")


def serialize_rows(rows, fmt):
    if fmt == "parquet":
        return rows_to_parquet_bytes(rows), "parquet"
    elif fmt == "json":
        return rows_to_json_bytes(rows), "jsonl"
    elif fmt == "csv":
        return rows_to_csv_bytes(rows), "csv"
    else:
        raise ValueError(f"Unsupported format: {fmt}. Use parquet, json, or csv.")


def build_s3_key(now, ext):
    ts = now.strftime("%Y%m%d_%H%M%S_%f")
    if PARTITION_BY_DATE:
        return f"year={now.year}/month={now.month:02d}/day={now.day:02d}/orders_{ts}.{ext}"
    return f"orders_{ts}.{ext}"


# ---------------------------------------------------------------------------
# Scenario-driven main loop
# ---------------------------------------------------------------------------

def detect_bi_tool() -> str | None:
    """Check which BI tool is available on the network.

    Returns 'superset', 'metabase', or None.
    Superset takes priority when both respond.
    """
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


def _check_stop_file():
    """Return True if /tmp/gen.stop exists (graceful shutdown signal)."""
    return os.path.exists("/tmp/gen.stop")


def _clean_stop_file():
    """Remove stale stop file from previous runs."""
    try:
        os.remove("/tmp/gen.stop")
    except FileNotFoundError:
        pass

def _write_pid():
    _clean_stop_file()
    try:
        with open("/tmp/gen.pid", "w") as fh:
            fh.write(str(os.getpid()))
    except Exception:
        pass


def _get_writer(fmt: str):
    """Return the writer module for the given format.

    Falls back to raw Parquet/JSON/CSV file writers when no Iceberg catalog
    is available.
    """
    if fmt == "parquet":
        from src.writers import parquet_writer
        return parquet_writer
    elif fmt == "json":
        from src.writers import json_writer
        return json_writer
    elif fmt == "csv":
        from src.writers import csv_writer
        return csv_writer
    elif fmt == "kafka":
        from src.writers import kafka_writer
        return kafka_writer
    else:
        raise ValueError(f"Unsupported format for scenario writer: {fmt}")


def _get_iceberg_writer(scenario: dict):
    """Create an IcebergWriter (PyIceberg REST catalog) when ICEBERG_CATALOG_URI is set.

    Returns (writer, namespace, table_name) or (None, None, None) if unavailable.
    AIStor SigV4 uses the same writer with rest.sigv4-enabled (direct pool1 node URI).
    """
    catalog_uri = os.environ.get("ICEBERG_CATALOG_URI", "")
    if not catalog_uri:
        return None, None, None

    is_sigv4 = os.environ.get("ICEBERG_SIGV4", "").lower() in ("true", "1", "yes")

    try:
        from src.writers.iceberg_writer import IcebergWriter
        endpoint = S3_ENDPOINT if S3_ENDPOINT.startswith("http") else f"http://{S3_ENDPOINT}"
        iceberg_cfg = scenario.get("iceberg", {}) or {}
        wh = os.environ.get("ICEBERG_WAREHOUSE", iceberg_cfg.get("warehouse", "warehouse"))
        # AIStor Tables expects bare warehouse name (e.g. "analytics"),
        # external Iceberg REST expects s3:// URI (e.g. "s3://warehouse/")
        wh_uri = wh if is_sigv4 else (wh if wh.startswith("s3://") else f"s3://{wh}/")

        # For AIStor (SigV4), connect to the /_iceberg endpoint on the first pool node :9000
        # (nginx LB :80 often breaks SigV4; hostname must match compose: {cluster}-pool1-node-1, not ...-node-1).
        sigv4_uri = catalog_uri
        if is_sigv4 and "-lb:80" in catalog_uri:
            sigv4_uri = catalog_uri.replace("-lb:80", "-pool1-node-1:9000")
            print(f"[scenario] AIStor SigV4: using direct pool1 node {sigv4_uri}")

        writer = IcebergWriter(
            catalog_uri=sigv4_uri if is_sigv4 else catalog_uri,
            warehouse=wh_uri,
            s3_endpoint=endpoint,
            access_key=S3_ACCESS_KEY,
            secret_key=S3_SECRET_KEY,
            sigv4=is_sigv4,
        )
        namespace = iceberg_cfg.get("namespace", "demo")
        table_name = iceberg_cfg.get("table", "orders")
        return writer, namespace, table_name
    except Exception as exc:
        print(f"[scenario] IcebergWriter not available: {exc}")
        return None, None, None


def main_scenario(scenario_id: str, fmt: str, rate_profile: str):
    """
    Scenario-driven main loop. Loads scenario YAML and uses structured
    value generators and format-aware writers.
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from src.schema_loader import load_scenario, get_volume_profile, get_bucket, get_partitioning
    from src.value_generators import generate_batch

    _write_pid()

    # Start paused if configured (write stop file after _write_pid cleans it)
    if os.environ.get("DG_START_PAUSED", "").lower() in ("true", "1", "yes"):
        print(f"[scenario] DG_START_PAUSED=true — starting idle. Trigger start signal to begin generating.")
        open("/tmp/gen.stop", "w").close()

    print(f"[scenario] Loading scenario: {scenario_id}")
    scenario = load_scenario(scenario_id)
    columns = scenario["columns"]

    profile = get_volume_profile(scenario, rate_profile)
    rows_per_batch = profile.get("rows_per_batch", 500)
    batches_per_minute = profile.get("batches_per_minute", 12)
    interval_s = 60.0 / batches_per_minute if batches_per_minute > 0 else 5.0
    ramp_up_seconds = scenario.get("volume", {}).get("ramp_up_seconds", 0)

    # Use S3_BUCKET from edge config if explicitly set (not the default),
    # otherwise use the scenario-defined bucket name
    if S3_BUCKET and S3_BUCKET != "raw-data":
        bucket = S3_BUCKET
    else:
        bucket = get_bucket(scenario, fmt)
    bucket, s3_key_prefix = split_s3_bucket_and_prefix(bucket)
    if not bucket:
        bucket = get_bucket(scenario, fmt)
        bucket, s3_key_prefix = split_s3_bucket_and_prefix(bucket)
    partition_cfg = get_partitioning(scenario, fmt)

    print(
        f"[scenario] Starting: scenario={scenario_id}, format={fmt}, "
        f"rate_profile={rate_profile}, rows_per_batch={rows_per_batch}, "
        f"batches_per_minute={batches_per_minute}, bucket={bucket}"
        + (f", object_prefix={s3_key_prefix!r}" if s3_key_prefix else "")
    )
    print(f"STATUS: scenario={scenario_id} format={fmt} state=starting")

    # Kafka path — skip all MinIO/S3 setup
    use_kafka = fmt == "kafka"
    client = None
    use_iceberg = False
    iceberg_writer = None
    ice_ns = None
    ice_table = None
    writer = None

    write_mode = os.environ.get("DG_WRITE_MODE", "iceberg").lower()

    if use_kafka:
        kafka_bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        kafka_topic = os.environ.get("KAFKA_TOPIC", "data-generator")
        from src.writers.kafka_writer import KafkaWriter
        kafka_writer_instance = KafkaWriter(
            bootstrap_servers=kafka_bootstrap,
            topic=kafka_topic,
        )
        print(f"[scenario] Using Kafka writer → kafka://{kafka_topic}")
    else:
        client = wait_for_minio(timeout=180)

        # Ensure bucket exists
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchBucket"):
                client.create_bucket(Bucket=bucket)
                print(f"[scenario] Created bucket '{bucket}'.")

        if write_mode == "raw":
            # Raw file mode — write directly to S3, skip Iceberg catalog writes
            writer = _get_writer(fmt)
            base = f"s3://{bucket}/{s3_key_prefix}" if s3_key_prefix else f"s3://{bucket}/"
            print(f"[scenario] Using raw file writer ({fmt}) → {base}")
        else:
            # Iceberg mode (default) — PyIceberg REST; raw file writer if catalog/table unavailable

            iceberg_cfg = scenario.get("iceberg", {}) or {}
            trino_namespace = iceberg_cfg.get("namespace", "demo")

            # Run table setup (buckets + PyIceberg table when ICEBERG_CATALOG_URI is set)
            try:
                from src.table_setup import run_setup
                endpoint = S3_ENDPOINT if S3_ENDPOINT.startswith("http") else f"http://{S3_ENDPOINT}"
                run_setup(
                    scenario, fmt, endpoint, S3_ACCESS_KEY, S3_SECRET_KEY,
                    trino_namespace=trino_namespace,
                )
                print(f"[scenario] Table setup completed for {scenario_id}/{fmt}")
            except Exception as exc:
                print(f"[scenario] Table setup skipped: {exc}")

            # BI tool setup — detect and provision dashboards in background thread
            bi_tool = detect_bi_tool()
            if bi_tool == "superset":
                import threading
                def _run_superset_setup():
                    try:
                        import sys as _sys
                        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                        from src.superset_setup import setup_superset
                        setup_superset()
                    except Exception as _exc:
                        print(f"[scenario] Superset setup failed (non-fatal): {_exc}")
                threading.Thread(target=_run_superset_setup, daemon=True).start()
                print(f"[scenario] Superset detected — dashboard setup running in background")
            elif bi_tool == "metabase":
                print(f"[scenario] Metabase detected — dashboard setup handled by scenario YAML")
            else:
                print(f"[scenario] No BI tool detected — skipping dashboard setup")

            iceberg_writer, ice_ns, ice_table = _get_iceberg_writer(scenario)
            use_iceberg = iceberg_writer is not None
            if use_iceberg:
                try:
                    # Store data in the user-specified bucket, not the default warehouse
                    if bucket:
                        mid = f"{s3_key_prefix}{ice_table}/" if s3_key_prefix else f"{ice_table}/"
                        table_location = f"s3://{bucket}/{mid}"
                    else:
                        table_location = None
                    iceberg_writer.ensure_table(ice_ns, ice_table, columns, location=table_location)
                    print(f"[scenario] Using Iceberg writer → {ice_ns}.{ice_table} (location: {table_location or 'default'})")
                except Exception as exc:
                    print(f"[scenario] Iceberg table creation failed: {exc} — falling back to raw {fmt} writer")
                    use_iceberg = False
                    iceberg_writer = None

            if not use_iceberg:
                writer = _get_writer(fmt)

    rows_generated = 0
    batches_sent = 0
    errors = 0
    start_time = time.time()

    # Ramp-up phase
    if ramp_up_seconds > 0:
        print(f"STATUS: scenario={scenario_id} format={fmt} state=ramp_up")
        print(f"[scenario] Ramping up over {ramp_up_seconds}s...")

    print(f"STATUS: scenario={scenario_id} format={fmt} state=streaming")

    while True:
        if _check_stop_file():
            print(f"[scenario] Stop file detected — pausing.")
            print(f"STATUS: scenario={scenario_id} format={fmt} state=idle rows={rows_generated} rate=0 batches={batches_sent} errors={errors}")
            try:
                os.remove("/tmp/gen.stop")
                os.remove("/tmp/gen.pid")
            except Exception:
                pass
            # Stay alive but idle — don't exit (Docker would restart us)
            while not os.path.exists("/tmp/gen.start"):
                time.sleep(2)
            # Resume signal received
            os.remove("/tmp/gen.start")
            _write_pid()
            print(f"[scenario] Resuming generation...")
            print(f"STATUS: scenario={scenario_id} format={fmt} state=streaming")
            start_time = time.time()
            rows_generated = 0
            batches_sent = 0
            errors = 0
            continue

        batch_start = time.time()

        # During ramp-up, scale rows linearly from 10% to 100%
        elapsed = time.time() - start_time
        if ramp_up_seconds > 0 and elapsed < ramp_up_seconds:
            scale = 0.1 + 0.9 * (elapsed / ramp_up_seconds)
            effective_rows = max(1, int(rows_per_batch * scale))
        else:
            effective_rows = rows_per_batch

        try:
            rows = generate_batch(columns, effective_rows)

            if use_kafka:
                kafka_writer_instance.write_batch(rows, columns)
                key = f"kafka/{kafka_topic}"
            elif use_iceberg:
                count = iceberg_writer.write_batch(rows, columns, ice_ns, ice_table)
                key = f"iceberg/{ice_ns}.{ice_table}"
            else:
                key = writer.write_batch(
                    rows=rows,
                    columns=columns,
                    partition_cfg=partition_cfg,
                    s3_client=client,
                    bucket=bucket,
                    key_prefix=s3_key_prefix,
                )
            rows_generated += len(rows)
            batches_sent += 1

            elapsed_total = time.time() - start_time
            rows_per_sec = rows_generated / elapsed_total if elapsed_total > 0 else 0

            dest = f"kafka://{kafka_topic}" if use_kafka else (
                f"iceberg://{ice_ns}.{ice_table}" if use_iceberg else (
                    f"s3://{bucket}/{s3_key_prefix}{key}" if s3_key_prefix else f"s3://{bucket}/{key}"
                )
            )
            print(
                f"[scenario] Wrote {len(rows)} rows ({fmt}) to {dest} "
                f"| total={rows_generated} rate={rows_per_sec:.1f} rows/s"
            )
            print(
                f"STATUS: scenario={scenario_id} format={fmt} state=streaming "
                f"rows={rows_generated} rate={rows_per_sec:.1f} batches={batches_sent} errors={errors}"
            )

        except (ClientError, EndpointResolutionError, NoCredentialsError, Exception) as exc:
            errors += 1
            print(f"[scenario] Error writing batch: {exc}. errors={errors}")

        # Sleep for the remainder of the interval
        elapsed_batch = time.time() - batch_start
        sleep_time = max(0.0, interval_s - elapsed_batch)
        time.sleep(sleep_time)


def main():
    _write_pid()

    # Route to scenario-driven loop if DG_SCENARIO is set
    if DG_SCENARIO:
        main_scenario(DG_SCENARIO, DG_FORMAT, DG_RATE_PROFILE)
        return

    # --- Legacy behavior ---
    client = wait_for_minio(timeout=180)
    legacy_bucket, legacy_prefix = split_s3_bucket_and_prefix(S3_BUCKET)
    if not legacy_bucket:
        legacy_bucket = "raw-data"
    ensure_bucket(client, legacy_bucket)

    order_id_counter = 1
    print(
        f"Starting generator: format={DG_FORMAT}, rows_per_file={DG_FILE_SIZE_ROWS}, "
        f"rate={DG_RATE} files/min (interval={INTERVAL_SECONDS:.1f}s), "
        f"batch_size={DG_BATCH_SIZE}, bucket={legacy_bucket}"
        + (f", prefix={legacy_prefix!r}" if legacy_prefix else "")
        + f", partition_by_date={PARTITION_BY_DATE}"
    )

    while True:
        if _check_stop_file():
            print("Stop file detected — pausing.")
            try:
                os.remove("/tmp/gen.stop")
                os.remove("/tmp/gen.pid")
            except Exception:
                pass
            # Stay alive but idle
            while not os.path.exists("/tmp/gen.start"):
                time.sleep(2)
            os.remove("/tmp/gen.start")
            _write_pid()
            print("Resuming generation...")
            continue

        for _ in range(DG_BATCH_SIZE):
            try:
                now = datetime.datetime.utcnow()
                rows = generate_rows(order_id_counter, DG_FILE_SIZE_ROWS)
                data, ext = serialize_rows(rows, DG_FORMAT)
                key = legacy_prefix + build_s3_key(now, ext)
                file_size = len(data)

                client.put_object(Bucket=legacy_bucket, Key=key, Body=data)
                print(
                    f"Wrote {DG_FILE_SIZE_ROWS} rows ({DG_FORMAT}) to "
                    f"s3://{legacy_bucket}/{key} ({file_size} bytes)"
                )

                order_id_counter += DG_FILE_SIZE_ROWS
            except (ClientError, EndpointResolutionError, NoCredentialsError, Exception) as exc:
                print(f"Error uploading file: {exc}. Will retry next interval.")

            time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
