import time
import os
import random
import io
import csv
import json
import datetime

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
DG_FORMAT = os.environ.get("DG_FORMAT", "parquet").lower()          # parquet | json | csv
DG_FILE_SIZE_ROWS = int(os.environ.get("DG_FILE_SIZE_ROWS", "1000"))  # rows per file
DG_RATE = float(os.environ.get("DG_RATE", "1"))                       # files per minute
DG_BATCH_SIZE = int(os.environ.get("DG_BATCH_SIZE", "10"))            # files per batch

# Backward-compatible: legacy env vars still honoured if new ones are absent and legacy are set
if "BATCH_SIZE" in os.environ and "DG_FILE_SIZE_ROWS" not in os.environ:
    DG_FILE_SIZE_ROWS = int(os.environ["BATCH_SIZE"])
if "INTERVAL_SECONDS" in os.environ and "DG_RATE" not in os.environ:
    interval_s = int(os.environ["INTERVAL_SECONDS"])
    DG_RATE = 60.0 / interval_s if interval_s > 0 else 1.0

INTERVAL_SECONDS = 60.0 / DG_RATE if DG_RATE > 0 else 60.0

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


def main():
    client = wait_for_minio(timeout=180)
    ensure_bucket(client, S3_BUCKET)

    order_id_counter = 1
    print(
        f"Starting generator: format={DG_FORMAT}, rows_per_file={DG_FILE_SIZE_ROWS}, "
        f"rate={DG_RATE} files/min (interval={INTERVAL_SECONDS:.1f}s), "
        f"batch_size={DG_BATCH_SIZE}, bucket={S3_BUCKET}, partition_by_date={PARTITION_BY_DATE}"
    )

    while True:
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
