import time
import os
import random
import io
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
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "500"))
INTERVAL_SECONDS = int(os.environ.get("INTERVAL_SECONDS", "5"))
PARTITION_BY_DATE = os.environ.get("PARTITION_BY_DATE", "true").lower() == "true"

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


def make_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=f"http://{S3_ENDPOINT}",
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


def generate_batch(start_order_id, batch_size):
    now = datetime.datetime.utcnow()
    order_ids = list(range(start_order_id, start_order_id + batch_size))
    customer_ids = [random.randint(1000, 9999) for _ in range(batch_size)]
    product_names = [random.choice(PRODUCTS) for _ in range(batch_size)]
    quantities = [random.randint(1, 50) for _ in range(batch_size)]
    unit_prices = [round(random.uniform(5.99, 499.99), 2) for _ in range(batch_size)]
    order_dates = [
        now - datetime.timedelta(seconds=random.randint(0, 3600))
        for _ in range(batch_size)
    ]
    regions = [random.choice(REGIONS) for _ in range(batch_size)]

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
    return table


def table_to_parquet_bytes(table):
    buf = io.BytesIO()
    pq.write_table(table, buf)
    buf.seek(0)
    return buf.read()


def build_s3_key(now):
    ts = now.strftime("%Y%m%d_%H%M%S_%f")
    if PARTITION_BY_DATE:
        return f"year={now.year}/month={now.month:02d}/day={now.day:02d}/orders_{ts}.parquet"
    return f"orders_{ts}.parquet"


def main():
    client = wait_for_minio(timeout=60)
    ensure_bucket(client, S3_BUCKET)

    order_id_counter = 1
    print(
        f"Starting generator: batch_size={BATCH_SIZE}, interval={INTERVAL_SECONDS}s, "
        f"bucket={S3_BUCKET}, partition_by_date={PARTITION_BY_DATE}"
    )

    while True:
        try:
            now = datetime.datetime.utcnow()
            table = generate_batch(order_id_counter, BATCH_SIZE)
            data = table_to_parquet_bytes(table)
            key = build_s3_key(now)
            file_size = len(data)

            client.put_object(Bucket=S3_BUCKET, Key=key, Body=data)
            print(f"Wrote {BATCH_SIZE} orders to s3://{S3_BUCKET}/{key} ({file_size} bytes)")

            order_id_counter += BATCH_SIZE
        except (ClientError, EndpointResolutionError, NoCredentialsError, Exception) as exc:
            print(f"Error uploading batch: {exc}. Will retry next interval.")

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
