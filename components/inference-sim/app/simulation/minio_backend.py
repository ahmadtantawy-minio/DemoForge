import os
import time
import random


class MinIOBackend:
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
    ) -> None:
        self.bucket = bucket
        self._connected = False

        if not endpoint:
            return

        try:
            import boto3
            from botocore.config import Config

            # Normalize endpoint — add http:// if missing scheme
            if not endpoint.startswith("http"):
                endpoint = f"http://{endpoint}"

            self._client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=Config(
                    connect_timeout=3,
                    read_timeout=10,
                    retries={"max_attempts": 1},
                ),
            )
            self._connected = True
        except Exception:
            self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def ensure_bucket(self) -> None:
        if not self._connected:
            return
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except Exception:
            try:
                self._client.create_bucket(Bucket=self.bucket)
            except Exception:
                pass

    def put_kv_block(
        self,
        session_id: str,
        block_seq: int,
        size_bytes: int,
        metadata: dict,
    ) -> float:
        """Write random bytes to S3. Returns actual latency in ms."""
        if not self._connected:
            return 0.0

        key = f"sessions/{session_id}/block-{block_seq}.kv"
        data = os.urandom(size_bytes)
        str_metadata = {k: str(v) for k, v in metadata.items()}

        t0 = time.monotonic()
        try:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                Metadata=str_metadata,
            )
        except Exception:
            pass
        return (time.monotonic() - t0) * 1000

    def get_kv_block(self, session_id: str, block_seq: int) -> float:
        """Read block from S3. Returns latency in ms."""
        if not self._connected:
            return 0.0

        key = f"sessions/{session_id}/block-{block_seq}.kv"
        t0 = time.monotonic()
        try:
            resp = self._client.get_object(Bucket=self.bucket, Key=key)
            resp["Body"].read()
        except Exception:
            pass
        return (time.monotonic() - t0) * 1000

    def delete_session(self, session_id: str) -> None:
        """Delete all objects under sessions/{session_id}/."""
        if not self._connected:
            return
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(
                Bucket=self.bucket, Prefix=f"sessions/{session_id}/"
            ):
                objects = page.get("Contents", [])
                if objects:
                    self._client.delete_objects(
                        Bucket=self.bucket,
                        Delete={"Objects": [{"Key": o["Key"]} for o in objects]},
                    )
        except Exception:
            pass

    def delete_all(self) -> None:
        """Delete all objects in bucket."""
        if not self._connected:
            return
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket):
                objects = page.get("Contents", [])
                if objects:
                    self._client.delete_objects(
                        Bucket=self.bucket,
                        Delete={"Objects": [{"Key": o["Key"]} for o in objects]},
                    )
        except Exception:
            pass

    def get_stats(self) -> dict:
        """Return object count and total size."""
        if not self._connected:
            return {"object_count": 0, "total_size_bytes": 0}
        count = 0
        total_bytes = 0
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket):
                for obj in page.get("Contents", []):
                    count += 1
                    total_bytes += obj.get("Size", 0)
        except Exception:
            pass
        return {"object_count": count, "total_size_bytes": total_bytes}
