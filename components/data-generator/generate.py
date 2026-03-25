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
from botocore.exceptions import ClientError, EndpointResolutionError, NoCredentialsError

# --- Config from environment ---
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "localhost:9000")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "minioadmin")
S3_BUCKET = os.environ.get("S3_BUCKET", "raw-data")
PARTITION_BY_DATE = os.environ.get("PARTITION_BY_DATE", "true").lower() == "true"

# New controls
DG_FORMAT = os.environ.get("DG_FORMAT", "parquet").lower()          # parquet | json | csv | iceberg
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
    """Return the writer module for the given format."""
    if fmt == "parquet":
        from src.writers import parquet_writer
        return parquet_writer
    elif fmt == "json":
        from src.writers import json_writer
        return json_writer
    elif fmt == "csv":
        from src.writers import csv_writer
        return csv_writer
    else:
        raise ValueError(f"Unsupported format for scenario writer: {fmt}")


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
    partition_cfg = get_partitioning(scenario, fmt)

    print(
        f"[scenario] Starting: scenario={scenario_id}, format={fmt}, "
        f"rate_profile={rate_profile}, rows_per_batch={rows_per_batch}, "
        f"batches_per_minute={batches_per_minute}, bucket={bucket}"
    )
    print(f"STATUS: scenario={scenario_id} format={fmt} state=starting")

    client = wait_for_minio(timeout=180)

    # Ensure bucket exists
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchBucket"):
            client.create_bucket(Bucket=bucket)
            print(f"[scenario] Created bucket '{bucket}'.")

    # Run table setup (create Iceberg tables, register in Trino if available)
    try:
        from src.table_setup import run_setup
        endpoint = S3_ENDPOINT if S3_ENDPOINT.startswith("http") else f"http://{S3_ENDPOINT}"
        run_setup(scenario, fmt, endpoint, S3_ACCESS_KEY, S3_SECRET_KEY)
        print(f"[scenario] Table setup completed for {scenario_id}/{fmt}")
    except Exception as exc:
        print(f"[scenario] Table setup skipped: {exc}")

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
            print(f"[scenario] Stop file detected — shutting down.")
            print(f"STATUS: scenario={scenario_id} format={fmt} state=idle")
            try:
                os.remove("/tmp/gen.stop")
            except Exception:
                pass
            break

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
            key = writer.write_batch(
                rows=rows,
                columns=columns,
                partition_cfg=partition_cfg,
                s3_client=client,
                bucket=bucket,
            )
            rows_generated += len(rows)
            batches_sent += 1

            elapsed_total = time.time() - start_time
            rows_per_sec = rows_generated / elapsed_total if elapsed_total > 0 else 0

            print(
                f"[scenario] Wrote {len(rows)} rows ({fmt}) to s3://{bucket}/{key} "
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
    ensure_bucket(client, S3_BUCKET)

    order_id_counter = 1
    print(
        f"Starting generator: format={DG_FORMAT}, rows_per_file={DG_FILE_SIZE_ROWS}, "
        f"rate={DG_RATE} files/min (interval={INTERVAL_SECONDS:.1f}s), "
        f"batch_size={DG_BATCH_SIZE}, bucket={S3_BUCKET}, partition_by_date={PARTITION_BY_DATE}"
    )

    while True:
        if _check_stop_file():
            print("Stop file detected — shutting down.")
            try:
                os.remove("/tmp/gen.stop")
            except Exception:
                pass
            break

        for _ in range(DG_BATCH_SIZE):
            try:
                now = datetime.datetime.utcnow()
                rows = generate_rows(order_id_counter, DG_FILE_SIZE_ROWS)
                data, ext = serialize_rows(rows, DG_FORMAT)
                key = build_s3_key(now, ext)
                file_size = len(data)

                client.put_object(Bucket=S3_BUCKET, Key=key, Body=data)
                print(
                    f"Wrote {DG_FILE_SIZE_ROWS} rows ({DG_FORMAT}) to "
                    f"s3://{S3_BUCKET}/{key} ({file_size} bytes)"
                )

                order_id_counter += DG_FILE_SIZE_ROWS
            except (ClientError, EndpointResolutionError, NoCredentialsError, Exception) as exc:
                print(f"Error uploading file: {exc}. Will retry next interval.")

            time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
