import io
import logging
import boto3
import pandas as pd
import pyarrow.parquet as pq
from botocore.config import Config as BotoConfig
from ..config import settings

logger = logging.getLogger(__name__)


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.MINIO_ENDPOINT,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name="us-east-1",
    )


def ensure_bucket(client, bucket: str):
    try:
        client.head_bucket(Bucket=bucket)
    except Exception:
        client.create_bucket(Bucket=bucket)


def load_training_data(source_bucket: str = "raw-data") -> pd.DataFrame:
    """Read all Parquet files from the source bucket and concatenate into a DataFrame."""
    client = get_s3_client()
    frames = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=source_bucket):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".parquet"):
                continue
            resp = client.get_object(Bucket=source_bucket, Key=key)
            table = pq.read_table(io.BytesIO(resp["Body"].read()))
            frames.append(table.to_pandas())
    if not frames:
        raise ValueError(f"No Parquet files found in bucket '{source_bucket}'")
    return pd.concat(frames, ignore_index=True)


def prepare_train_test(df: pd.DataFrame, test_fraction: float = 0.2) -> dict:
    """Split data into train/test sets and upload to the training bucket."""
    from sklearn.model_selection import train_test_split
    train_df, test_df = train_test_split(df, test_size=test_fraction, random_state=42)

    client = get_s3_client()
    ensure_bucket(client, settings.TRAINING_BUCKET)

    # Write train set
    train_buf = io.BytesIO()
    train_df.to_parquet(train_buf, index=False)
    train_buf.seek(0)
    client.put_object(Bucket=settings.TRAINING_BUCKET, Key="train.parquet", Body=train_buf.getvalue())

    # Write test set
    test_buf = io.BytesIO()
    test_df.to_parquet(test_buf, index=False)
    test_buf.seek(0)
    client.put_object(Bucket=settings.TRAINING_BUCKET, Key="test.parquet", Body=test_buf.getvalue())

    return {"train_rows": len(train_df), "test_rows": len(test_df), "columns": list(df.columns)}


def load_split(split: str = "train") -> pd.DataFrame:
    """Load train or test split from the training bucket."""
    client = get_s3_client()
    resp = client.get_object(Bucket=settings.TRAINING_BUCKET, Key=f"{split}.parquet")
    return pd.read_parquet(io.BytesIO(resp["Body"].read()))
